from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import projects, site, generate, exports, chat
from app.core.config import settings

app = FastAPI(
    title="Petronus API",
    description="Automated BIM generation for California multi-family residential",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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
