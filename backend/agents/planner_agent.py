from __future__ import annotations

import asyncio
import json
import logging
import re
from uuid import uuid4

from app.config import Settings
from app.models import TaskPlan, TaskStep

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

PLAN_GENERATION_PROMPT = """You are a highly specific DIY task planner. Given a user's goal and a visual description of their surroundings, generate a tailored step-by-step repair or setup plan.

Rules:
- Be EXTREMELY SPECIFIC. Do not give generic advice. If the visual context mentions a "red cable" or a "TP-Link router", use those exact terms in the steps.
- Generate 3-6 steps. Each step must be small, safe, and actionable.
- ALWAYS include safety precautions as the first step if the task involves electricity, gas, water, sharp tools, or heat.
- If the task is beyond basic DIY (main electrical panel, gas lines, structural work), set "needs_professional" to true and include only 1 step telling them to call a professional.
- Each step must have: title (short), instruction (1-2 sentences), validation_hint (Specific visual evidence to confirm the step is done, e.g., "The green power LED should be solid" or "The yellow ethernet cable should be clicked into the WAN port").
- Return valid JSON only. No markdown, no commentary.
- If no visual context is provided, ask the user to show the device in the first step.

Output format:
{
  "goal": "cleaned up version of the user's goal",
  "needs_professional": false,
  "safety_warning": "optional safety note or null",
  "steps": [
    {
      "title": "Step title",
      "instruction": "What to do and why",
      "validation_hint": "What should be visible when done"
    }
  ]
}

Examples of tasks and categories:
- "my kitchen faucet is dripping" → Plumbing (shut off water, check washer, replace if needed)
- "light switch not working" → Electrical (turn off breaker, check wiring, test with multimeter)
- "microwave not heating" → Kitchen appliance (check door switch, test outlet, reset)
- "assemble this shelf" → Furniture (lay out parts, follow order, secure to wall)
- "router internet light is red" → Electronics (restart modem, check cables, factory reset)
- "fix the main breaker panel" → PROFESSIONAL REQUIRED

User's goal: {goal}
Visual context: {visual_context}
"""


class PlannerAgent:
    """Generates DIY task plans using Gemini AI with hardcoded fallbacks."""

    ROUTER_KEYWORDS = {"router", "wifi", "wi-fi", "modem", "internet"}
    COMPUTER_KEYWORDS = {"computer", "pc", "laptop", "printer", "monitor"}
    COOKING_KEYWORDS = {"cook", "recipe", "oven", "stove", "pan"}
    ELECTRICAL_KEYWORDS = {"outlet", "switch", "breaker", "light fixture", "wiring", "bulb", "lamp", "fuse"}
    PLUMBING_KEYWORDS = {"faucet", "leak", "drain", "pipe", "tap", "sink", "toilet", "plumbing"}
    APPLIANCE_KEYWORDS = {"washer", "washing machine", "fridge", "refrigerator", "ac", "air conditioner", "water heater", "dishwasher", "microwave"}
    FURNITURE_KEYWORDS = {"shelf", "table", "chair", "desk", "cabinet", "assemble", "mount", "hanging", "anchor"}

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self._client = None
        if settings and settings.google_api_key and genai:
            self._client = genai.Client(api_key=settings.google_api_key)

    async def create_plan_async(self, user_goal: str, image_description: str | None = None) -> TaskPlan:
        """Generate a plan using AI, falling back to hardcoded plans on failure."""
        if self._client and types:
            try:
                plan = await self._generate_ai_plan(user_goal, image_description)
                if plan:
                    return plan
            except Exception:
                logger.exception("AI plan generation failed, falling back to hardcoded plan")

        return self.create_plan(user_goal)

    def create_plan(self, user_goal: str) -> TaskPlan:
        """Hardcoded fallback plan generation (keyword-based)."""
        normalized = user_goal.lower()

        if any(kw in normalized for kw in self.ELECTRICAL_KEYWORDS):
            steps = self._electrical_plan()
        elif any(kw in normalized for kw in self.PLUMBING_KEYWORDS):
            steps = self._plumbing_plan()
        elif any(kw in normalized for kw in self.APPLIANCE_KEYWORDS):
            steps = self._appliance_plan()
        elif any(kw in normalized for kw in self.FURNITURE_KEYWORDS):
            steps = self._furniture_plan()
        elif any(kw in normalized for kw in self.ROUTER_KEYWORDS):
            steps = self._router_plan()
        elif any(kw in normalized for kw in self.COMPUTER_KEYWORDS):
            steps = self._computer_plan()
        elif any(kw in normalized for kw in self.COOKING_KEYWORDS):
            steps = self._cooking_plan()
        else:
            steps = self._generic_plan(user_goal)

        steps[0].status = "in_progress"
        return TaskPlan(goal=self._clean_goal(user_goal), steps=steps, current_step_id=steps[0].id)

    async def _generate_ai_plan(self, user_goal: str, image_description: str | None) -> TaskPlan | None:
        assert self._client is not None and types is not None

        visual_context = image_description or "No visual context provided."
        prompt = PLAN_GENERATION_PROMPT.format(goal=user_goal, visual_context=visual_context)

        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self.settings.vision_model if self.settings else "gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )

        text = getattr(response, "text", None)
        if not text:
            return None

        # Clean potential markdown wrapping
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        data = json.loads(text)

        steps: list[TaskStep] = []
        for step_data in data.get("steps", []):
            steps.append(
                TaskStep(
                    id=str(uuid4()),
                    title=step_data.get("title", "Step"),
                    instruction=step_data.get("instruction", ""),
                    validation_hint=step_data.get("validation_hint", ""),
                )
            )

        if not steps:
            return None

        steps[0].status = "in_progress"
        goal = data.get("goal", user_goal)
        plan = TaskPlan(goal=self._clean_goal(goal), steps=steps, current_step_id=steps[0].id)

        # Attach safety metadata
        safety_warning = data.get("safety_warning")
        needs_pro = data.get("needs_professional", False)
        if safety_warning or needs_pro:
            plan_dict = plan.model_dump()
            plan_dict["safety_warning"] = safety_warning
            plan_dict["needs_professional"] = needs_pro
            # Store as extra fields via model_dump reconstruction
            plan = TaskPlan.model_validate(plan_dict)

        return plan

    # ── Hardcoded fallback plans ──────────────────────────────────────────

    def _clean_goal(self, user_goal: str) -> str:
        return re.sub(r"\s+", " ", user_goal).strip().capitalize()

    def _step(self, title: str, instruction: str, validation_hint: str) -> TaskStep:
        return TaskStep(
            id=str(uuid4()),
            title=title,
            instruction=instruction,
            validation_hint=validation_hint,
        )

    def _electrical_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Safety first",
                "Switch off the circuit breaker for the affected area. If unsure which breaker, turn off the main breaker.",
                "The breaker should be in the OFF position and no power at the outlet/switch.",
            ),
            self._step(
                "Inspect the problem area",
                "Point the camera at the switch, outlet, or fixture so I can see the current state.",
                "I should be able to see the device and any visible damage or loose parts.",
            ),
            self._step(
                "Apply the fix",
                "Follow the corrective action I provide based on what I see.",
                "The component should be properly seated, connected, or replaced.",
            ),
            self._step(
                "Test safely",
                "Turn the breaker back on and test the switch or outlet.",
                "The device should function normally with no sparking or unusual behavior.",
            ),
        ]

    def _plumbing_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Shut off water supply",
                "Find and close the shut-off valve for the affected fixture. It's usually under the sink or behind the toilet.",
                "The valve handle should be fully closed and water should stop flowing.",
            ),
            self._step(
                "Inspect the issue",
                "Show me the leaking or problematic area so I can identify the type of fitting and what needs attention.",
                "I should be able to see the joint, washer, or area where water is escaping.",
            ),
            self._step(
                "Fix or replace the part",
                "Follow my guidance to tighten, wrap with plumber's tape, or replace the faulty component.",
                "The connection should be hand-tight and properly sealed.",
            ),
            self._step(
                "Test for leaks",
                "Turn the water supply back on slowly and check for any drips.",
                "No water should be visible at the repaired joint after 30 seconds.",
            ),
        ]

    def _appliance_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Unplug the appliance",
                "Disconnect the appliance from power before any inspection.",
                "The power cord should be fully unplugged from the outlet.",
            ),
            self._step(
                "Check for obvious issues",
                "Show me the appliance — look for error codes on the display, unusual sounds, or visible damage.",
                "I should see the front panel, any error codes, and the general condition.",
            ),
            self._step(
                "Clean or reset",
                "Follow my instructions to clean filters, clear blockages, or perform a factory reset.",
                "The appliance should be clean and reset, ready for testing.",
            ),
            self._step(
                "Reconnect and test",
                "Plug the appliance back in and run a test cycle.",
                "The appliance should start normally without error codes or unusual behavior.",
            ),
        ]

    def _furniture_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Lay out all parts",
                "Spread out all parts, hardware, and tools. Show me the instruction sheet if available.",
                "All pieces should be visible and accounted for.",
            ),
            self._step(
                "Assemble the frame",
                "Start with the main structural pieces. Follow the numbered order in the manual.",
                "The base or frame should be standing and stable.",
            ),
            self._step(
                "Attach remaining pieces",
                "Add shelves, doors, drawers, or panels as instructed.",
                "All components should be attached and aligned properly.",
            ),
            self._step(
                "Secure and level",
                "Tighten all fasteners, check for wobble, and anchor to the wall if required.",
                "The furniture should be stable, level, and safe.",
            ),
        ]

    def _router_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Identify hardware",
                "Point the camera at the router and power adapter so I can help identify ports and labels.",
                "I should be able to see the router model area, power jack, and the rear port panel.",
            ),
            self._step(
                "Connect power",
                "Plug the router into power and wait for the main status light to stabilize.",
                "The power LED should turn on and stop rapidly blinking after boot.",
            ),
            self._step(
                "Connect internet cable",
                "Insert the ISP or modem cable into the WAN or Internet port, which is often a different color.",
                "I should see the cable seated in the WAN/Internet port.",
            ),
            self._step(
                "Connect local device",
                "Connect a laptop or desktop to a LAN port or prepare to join the default Wi-Fi network.",
                "A LAN light or client connection indicator should appear.",
            ),
            self._step(
                "Verify status lights",
                "Show me the front LEDs so I can verify power, internet, and Wi-Fi indicators.",
                "The expected lights should be steady or blinking normally, without red warning lights.",
            ),
        ]

    def _computer_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Inspect the device",
                "Show the full device and the affected area so I can identify cables, ports, and indicators.",
                "The camera view should clearly include the device and the problem area.",
            ),
            self._step(
                "Check power and connections",
                "Verify power, display, and peripheral cables are fully connected.",
                "Loose or missing cables should be ruled out visually.",
            ),
            self._step(
                "Capture the symptom",
                "Show error lights, on-screen messages, or any unusual behavior.",
                "I should have enough visual evidence to identify the failure mode.",
            ),
            self._step(
                "Apply the fix",
                "Follow the corrective action I provide for the issue we identify.",
                "The original symptom should no longer be present.",
            ),
        ]

    def _cooking_plan(self) -> list[TaskStep]:
        return [
            self._step(
                "Gather ingredients",
                "Lay out the ingredients and tools in view so I can verify you have what you need.",
                "Ingredients and cookware should be visible and identifiable.",
            ),
            self._step(
                "Prepare the station",
                "Preheat the appliance if needed and prepare the cutting or mixing area.",
                "The station should be organized and safe before cooking starts.",
            ),
            self._step(
                "Cook step by step",
                "Carry out each cooking step while keeping the pan, pot, or tray visible when possible.",
                "Texture, color, or timing cues should match the target result.",
            ),
            self._step(
                "Final check",
                "Show the finished dish so I can verify doneness and presentation.",
                "The food should look finished and safely cooked.",
            ),
        ]

    def _generic_plan(self, user_goal: str) -> list[TaskStep]:
        return [
            self._step(
                "Assess the setup",
                f"Show me the item or workspace involved in: {user_goal}.",
                "The camera should clearly show the device, tool, or area involved.",
            ),
            self._step(
                "Prepare safely",
                "Before touching anything, confirm power, heat, or sharp tools are handled safely.",
                "The task should be in a safe state before we continue.",
            ),
            self._step(
                "Complete the next action",
                "Follow the next instruction I provide and keep the work area visible.",
                "I should be able to visually validate the change you made.",
            ),
            self._step(
                "Verify outcome",
                "Show the result so I can confirm the task is completed correctly.",
                "The device or task outcome should match the requested goal.",
            ),
        ]
