import os
import json
import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from .engine.yt_ingest import fetch_youtube_transcript, list_ingested_knowledge
from .engine.video_pipeline import create_video_script

app = FastAPI(title="ARES Creator Studio Sidecar", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "ares-creator",
        "version": "1.0.0",
        "capabilities": ["vtuber_overlay", "youtube_learning", "video_pipeline"]
    }

class YouTubeLearnRequest(BaseModel):
    url: str

@app.post("/api/yt/learn")
def learn_youtube_video(req: YouTubeLearnRequest):
    return fetch_youtube_transcript(req.url)

@app.get("/api/yt/knowledge")
def get_knowledge_library():
    return {"library": list_ingested_knowledge()}

class VideoScriptRequest(BaseModel):
    topic: str
    duration_secs: Optional[int] = 60

@app.post("/api/video/script")
def generate_video_script(req: VideoScriptRequest):
    return create_video_script(req.topic, req.duration_secs)

@app.get("/overlay/avatar", response_class=HTMLResponse)
def get_obs_transparent_overlay():
    """Returns a transparent OBS Browser Source viewport for the VTuber avatar."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>ARES VTuber OBS Overlay</title>
      <style>
        body { margin: 0; background: transparent; overflow: hidden; }
        #avatarContainer { width: 100vw; height: 100vh; display: flex; justify-content: center; align-items: flex-end; }
        .avatar-placeholder { color: #00ffcc; font-family: monospace; font-size: 20px; padding: 20px; text-shadow: 0 0 10px #00ffcc; }
      </style>
    </head>
    <body>
      <div id="avatarContainer">
        <div class="avatar-placeholder">[ARES LIVE AVATAR VIEWPORT • TRANSPARENT OBS READY]</div>
      </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.getenv("CREATOR_PORT", 3849))
    uvicorn.run(app, host="127.0.0.1", port=port)
