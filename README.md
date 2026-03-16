# HoneyAI Live: Your Multimodal Smart Mentor

HoneyAI Live is a cutting-edge, real-time AI assistant designed to provide hands-free guidance for physical and digital tasks. Powered by **Google Gemini Live**, it acts as a digital pair of eyes and ears, watching your camera feed or screen to provide instant, verbal mentoring.

Whether you're fixing a leaking faucet, navigating a complex UI, or debugging code, HoneyAI Live provides immediate visual feedback, generates custom action plans, and validates your progress as you work.

---

## ✨ Key Features

- **🧠 Smart Mentor & Live Screen Understanding**: Streams your display content directly to Gemini Live for instant feedback on programming, form filling, or UI navigation. No copy-pasting errors—HoneyAI sees them as you do.
- **🛠️ Dynamic DIY Planning**: Generates hyper-specific, step-by-step repair plans on the fly based on the specific device or task in view.
- **🎙️ Human-like Voice Interruption**: Features natural conversational "barge-in"—the AI stops talking immediately to listen to your question or feedback, just like a real mentor.
- **👁️ Visual Auto-Validation**: Periodically analyzes your camera or screen feed to confirm if you've completed a physical or digital step and automatically advances the project plan.
- **💾 Persistent Long-Term Memory**: Remembers past sessions and project history using a local SQLite database, ensuring a seamless experience across days.
- **🚀 Hands-Free Active Listening**: Optimized for a 100% hands-free experience. Once a session starts, the AI listens and watches continuously.

---

## 🛠️ Built With

- **AI Engine**: [Google Gemini Live API](https://ai.google.dev/gemini-api/docs/live-api) & Gemini 1.5 Flash
- **Frontend**: [Next.js 15](https://nextjs.org/) (App Router), TypeScript, Tailwind CSS
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python), aiosqlite
- **Media Processing**: Custom Web Audio Worklets (16kHz PCM), Screen Capture API
- **Deployment**: Google Cloud Run (Serverless Containers)

---

## 🚀 Getting Started

### 1. Backend Setup (FastAPI)
1. Navigate to the `backend` folder:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Create a `.env` file from the example:
   ```bash
   cp .env.example .env
   ```
3. Add your `GOOGLE_API_KEY` to the `.env` file.
4. Start the server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### 2. Frontend Setup (Next.js)
1. Navigate to the `frontend` folder:
   ```bash
   cd frontend
   npm install
   ```
2. Create a `.env.local` file:
   ```bash
   cp .env.local.example .env.local
   ```
3. (Optional) Set `NEXT_PUBLIC_API_BASE_URL` if your backend is not on `localhost:8000`.
4. Start the development server:
   ```bash
   npm run dev
   ```

---

## ☁️ Deployment (Google Cloud Run)

### Backend
Deploy the backend to get your API URL:
```bash
gcloud run deploy honeyai-backend \
  --source ./backend \
  --set-env-vars="ENABLE_GEMINI_LIVE=true,ALLOWED_ORIGINS=*" \
  --set-secrets="GOOGLE_API_KEY=YOUR_SECRET_NAME:latest"
```

### Frontend
1. Create a `.env.production` file in the `frontend` folder:
   ```text
   NEXT_PUBLIC_API_BASE_URL=https://your-backend-url.run.app
   ```
2. Deploy the frontend:
   ```bash
   gcloud run deploy honeyai-frontend --source ./frontend
   ```

---

## 📂 Project Structure

- `frontend/`: Next.js UI, real-time media processing, and task-tracking components.
- `backend/`: FastAPI server, Gemini Live adapter, DIY session agents, and memory engine.
- `brain/`: Artifacts, logs, and development documentation.

---

## 🛡️ Privacy & Security
- **No Persistence**: Raw camera and screen frames are processed in-memory and are not saved to disk.
- **Summarized Memory**: Long-term memory stores only high-level text summaries of interactions to preserve privacy.
