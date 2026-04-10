import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import projects, site, generate, exports, chat

app = FastAPI(
    title="Petronus API",
    description="Automated BIM generation for California multi-family residential",
    version="0.1.0"
)

_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(site.router, prefix="/api/site", tags=["site"])
app.include_router(generate.router, prefix="/api/generate", tags=["generate"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
