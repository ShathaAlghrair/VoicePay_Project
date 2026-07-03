from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
import sys

# Relative imports from the new structure
from app.core.pipeline import VoicePayPipeline
from app.db.database import SessionLocal
from app.db.models import PersonAccount
from app.api.voice import router as voice_router
from app.api.management import router as management_router
from deepgram import DeepgramClient

DEEPGRAM_API_KEY = "79993c1ce891ea233887e95690d551bb5334fe7f"

app = FastAPI(title="VoicePay API")

# Add CORS support (Important for Flutter apps)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Pipeline and STT Model ONCE and share it
pipeline_instance = VoicePayPipeline()
app.state.pipeline = pipeline_instance

print("Initializing Deepgram client...")
stt_client = DeepgramClient(api_key=DEEPGRAM_API_KEY)
app.state.stt_client = stt_client
print("Deepgram client initialized!")

# Include Routers (Make sure routers can access app.state)
app.include_router(voice_router, prefix="/api/v1")
app.include_router(management_router, prefix="/api/v1")

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def root():
    return {"status": "VoicePay API is running", "message": "Backend is ready for Flutter integration."}

if __name__ == "__main__":
    import uvicorn
    # To run this, you should be in the directory containing the 'app' folder
    # and run: python -m app.api.main
    uvicorn.run(app, host="0.0.0.0", port=5000)
