from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from gemini_client import GeminiClientFactory
from memory.ltm import LongTermMemory
from memory.memory_manager import MemoryManager
from agents.planner_agent import PlannerAgent
from vision_client import VisionAnalyzer
from websocket_server import HoneyWebSocketServer

settings = get_settings()

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
origins = settings.allowed_origins
# If wildcard is present, we must disable allow_credentials for it to be valid
allow_all = "*" in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if not allow_all else ["*"],
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

ltm = LongTermMemory(settings.sqlite_path)
memory_manager = MemoryManager(ltm=ltm, stm_limit=settings.stm_limit)
gemini_factory = GeminiClientFactory(settings=settings)
vision_analyzer = VisionAnalyzer(settings=settings)
planner = PlannerAgent(settings=settings)
ws_server = HoneyWebSocketServer(memory_manager=memory_manager, gemini_factory=gemini_factory, vision_analyzer=vision_analyzer, settings=settings)

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None


@app.on_event("startup")
async def startup() -> None:
    await ltm.initialize()


@app.get("/api/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "gemini_enabled": settings.enable_gemini_live,
    }


@app.get("/api/config")
async def config() -> dict[str, str | int]:
    return {
        "appName": settings.app_name,
        "geminiModel": settings.gemini_model,
        "stmLimit": settings.stm_limit,
        "visionModel": settings.vision_model,
    }


@app.post("/api/live/token")
async def create_live_token() -> dict[str, Any]:
    if not settings.enable_gemini_live or not settings.google_api_key:
        raise HTTPException(status_code=503, detail="Gemini Live is not configured on the server.")
    if genai is None or types is None:
        raise HTTPException(status_code=503, detail="google-genai SDK is not available on the server.")

    client = genai.Client(api_key=settings.google_api_key, http_options={"api_version": "v1alpha"})

    try:
        token = await asyncio.to_thread(
            client.auth_tokens.create,
            config=types.CreateAuthTokenConfig(
                uses=6,
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to create Gemini Live ephemeral token")
        raise HTTPException(status_code=502, detail="Failed to create Gemini Live token.") from exc

    return {
        "token": token.name,
        "model": settings.gemini_model,
        "voiceName": settings.gemini_voice_name,
        "visionModel": settings.vision_model,
        "expireTime": getattr(token, "expire_time", None),
        "newSessionExpireTime": getattr(token, "new_session_expire_time", None),
    }


@app.websocket("/ws/live")
async def live_session(websocket: WebSocket) -> None:
    await ws_server.handle(websocket)


class DiyPlanRequest(BaseModel):
    goal: str
    imageDescription: str | None = None


@app.post("/api/diy/plan")
async def create_diy_plan(body: DiyPlanRequest) -> dict[str, Any]:
    plan = await planner.create_plan_async(body.goal, image_description=body.imageDescription)
    return plan.model_dump(mode="json")


class DiyStepValidationRequest(BaseModel):
    image: str
    mimeType: str
    step: Any  # Any to relax validation if frontend sends extra fields, will access attributes


@app.post("/api/diy/validate-step")
async def create_diy_step_validation(body: DiyStepValidationRequest) -> dict[str, Any]:
    # Extract step details, handle if step is passed as dict or object
    step = body.step
    if isinstance(step, dict):
        title = step.get("title", "")
        instruction = step.get("instruction", "")
        validation_hint = step.get("validation_hint", "")
    else:
        title = getattr(step, "title", "")
        instruction = getattr(step, "instruction", "")
        validation_hint = getattr(step, "validation_hint", "")

    result = await vision_analyzer.validate_step(
        image_b64=body.image,
        mime_type=body.mimeType,
        step_title=title,
        step_instruction=instruction,
        validation_hint=validation_hint,
    )
    return result
