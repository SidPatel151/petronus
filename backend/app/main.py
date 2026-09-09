import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import projects, site, generate, exports, chat, auth, blueprint
from app.core.persistence import init_db

app = FastAPI(
    title="Petronus API",
    description="Automated preliminary BIM generation for California residential buildings",
    version="0.1.0",
)

@app.on_event("startup")
def on_startup():
    init_db()

_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002")
# Handle both JSON array format (["url"]) and comma-separated format
_cors_raw = _cors_raw.strip().strip("[]").replace('"', '').replace("'", "")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(site.router, prefix="/api/site", tags=["site"])
app.include_router(generate.router, prefix="/api/generate", tags=["generate"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(blueprint.router, prefix="/api/blueprint", tags=["blueprint"])

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
