# 🎙️ Live AI Meeting Summarizer

A real-time meeting summarizer that captures audio via WebRTC, transcribes it locally using Whisper, and generates on‑demand summaries using Ollama (or optionally Gemini). Perfect for capturing decisions and action items from live conversations.

![Screenshot](https://via.placeholder.com/800x400?text=Live+Meeting+Summarizer+UI) *(replace with actual screenshot later)*

---

## 🚀 Features

- **Live audio capture** – uses WebRTC (`getUserMedia`) directly in the browser.
- **Real‑time transcription** – local Whisper model converts speech to text.
- **On‑demand summarization** – choose 3, 5, or 10 minutes of the conversation and get a concise summary.
- **Firebase Authentication** – secure email/password login.
- **Firestore storage** – transcripts and summaries are persisted.
- **WebSocket streaming** – low‑latency audio transmission.
- **Self‑hosted AI** – Ollama runs locally, keeping data private and free.

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js, React, WebRTC, TailwindCSS |
| Backend | FastAPI, WebSockets, Python |
| Transcription | OpenAI Whisper (local) |
| Summarization | Ollama (LLaMA 3.2) – or Gemini API (optional) |
| Database & Auth | Firebase Firestore + Authentication |
| Communication | WebSocket (audio chunks) + REST (summaries) |

---

## 📋 Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.10+
- **Ollama** installed and running (or a Gemini API key)
- **Firebase** project with Authentication (Email/Password) and Firestore enabled
- **Whisper** – will be downloaded automatically by the backend on first use.

---

## 🛠️ Installation & Setup

### 1️⃣ Clone the repository

```bash
git clone https://github.com/suraj662/live-summarizer.git
cd live-summarizer


Backend setup
cd backend
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt


Create a .env file (copy from .env.example) and fill in:
# Server
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:3000

# Audio
AUDIO_SAMPLE_RATE=16000
AUDIO_BUFFER_SECONDS=2

# Firebase Admin
FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json
# or set GOOGLE_APPLICATION_CREDENTIALS to the same path

# Whisper
WHISPER_MODEL=base   # tiny, base, small, medium, large
WHISPER_DEVICE=cpu

# Ollama (local)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
OLLAMA_REQUEST_TIMEOUT_SECONDS=120


Place your Firebase service account JSON (serviceAccountKey.json) in the backend/ folder (do not commit it – it's in .gitignore).

Start Ollama
In a separate terminal:
ollama serve
# (pull the model if not already done)
ollama pull llama3.2


Frontend setup
cd ../frontend
npm install


Create a .env.local file:
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_API_URL=http://localhost:8000


Get these values from your Firebase project's Web app configuration.

Run the application

Backend (from backend/):
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Frontend (from frontend/):
npm run dev



Open http://localhost:3000 in your browser.

🧪 Usage
Sign up or log in with email/password.

Click “Start Meeting” – allow microphone access.

Speak naturally.

After some speech, choose a duration (3, 5, or 10 minutes) and click “Get Summary”.

The summary will appear with key points and action items.

📡 API Endpoints (Backend)
Endpoint	Method	Description
/health	GET	Health check
/api/summarize	POST	Request a summary (requires meeting_id, duration, optional from_time)
/ws/{meeting_id}	WebSocket	Audio streaming endpoint (requires user_id query param)
/users/me/preferences	GET	Get user preferences
/meetings/{id}/transcripts	GET	Fetch transcripts for a time range (debugging)
🐳 Deployment (Optional)
Frontend: Deploy to Vercel, Netlify, or Firebase Hosting.

Backend: Containerize with Docker and deploy to Google Cloud Run, AWS ECS, or Render.

Ollama: Run on a GPU‑equipped server or use a cloud API (like Gemini) to avoid local compute.

For a quick demo, you can also use ngrok to expose your local backend publicly.

🤝 Contributing
Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.