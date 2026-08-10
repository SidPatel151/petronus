"""
auth.py — JWT-based authentication with email/password + Google OAuth scaffold.

Google OAuth activates when GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET env vars are set.
Without them the /auth/google endpoint returns 501 so the frontend can show "Coming Soon".
"""
import os, uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from jose import JWTError, jwt
import bcrypt as _bcrypt_lib

from app.core.persistence import (
    create_user, get_user_by_email, get_user_by_id,
    update_user_google,
)

router = APIRouter()

# ── Crypto ─────────────────────────────────────────────────────────────────
_SECRET     = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
_ALGORITHM  = "HS256"
_TOKEN_DAYS = 30
_oauth2     = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

# ── Google OAuth config (optional) ─────────────────────────────────────────
_GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")
_GOOGLE_ENABLED       = bool(_GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET)


# ── Helpers ─────────────────────────────────────────────────────────────────
def _hash(pw: str) -> str:
    return _bcrypt_lib.hashpw(pw.encode(), _bcrypt_lib.gensalt()).decode()

def _verify(pw: str, hashed: str) -> bool:
    try:
        return _bcrypt_lib.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def _make_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(days=_TOKEN_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp}, _SECRET, algorithm=_ALGORITHM)

def _decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

async def get_current_user(token: str = Depends(_oauth2)):
    if not token:
        return None
    uid = _decode_token(token)
    if not uid:
        return None
    return get_user_by_id(uid)

async def require_user(token: str = Depends(_oauth2)):
    user = await get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ── Schemas ─────────────────────────────────────────────────────────────────
class RegisterBody(BaseModel):
    name: str
    email: str
    password: str

class LoginBody(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    avatar: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.post("/register")
async def register(body: RegisterBody):
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")
    uid = str(uuid.uuid4())
    create_user(uid, body.name, body.email, _hash(body.password))
    token = _make_token(uid)
    return {"token": token, "user": {"id": uid, "name": body.name, "email": body.email}}

@router.post("/login")
async def login(body: LoginBody):
    user = get_user_by_email(body.email)
    if not user or not _verify(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email or password")
    token = _make_token(user["id"])
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"], "avatar": user.get("avatar")}}

# OAuth2PasswordRequestForm compat endpoint (for OpenAPI /docs)
@router.post("/token")
async def token_compat(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_email(form.username)
    if not user or not _verify(form.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": _make_token(user["id"]), "token_type": "bearer"}

@router.get("/me")
async def me(user=Depends(require_user)):
    return {"id": user["id"], "name": user["name"], "email": user["email"], "avatar": user.get("avatar")}

# ── Google OAuth ──────────────────────────────────────────────────────────────
@router.get("/google")
async def google_start():
    if not _GOOGLE_ENABLED:
        raise HTTPException(501, "Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars")
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=_GOOGLE_CLIENT_ID,
        client_secret=_GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    redirect_uri = f"{_FRONTEND_URL}/api/auth/google/callback"
    # Build the redirect URL manually since we're in a plain router
    from urllib.parse import urlencode
    params = {
        "client_id": _GOOGLE_CLIENT_ID,
        "redirect_uri": f"{os.getenv('BACKEND_URL','http://localhost:8000')}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)

@router.get("/google/callback")
async def google_callback(code: str = "", error: str = ""):
    if not _GOOGLE_ENABLED:
        raise HTTPException(501, "Google OAuth not configured")
    if error:
        return RedirectResponse(f"{_FRONTEND_URL}/login?error=google_denied")
    try:
        import httpx
        # Exchange code for tokens
        token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": _GOOGLE_CLIENT_ID,
            "client_secret": _GOOGLE_CLIENT_SECRET,
            "redirect_uri": f"{os.getenv('BACKEND_URL','http://localhost:8000')}/api/auth/google/callback",
            "grant_type": "authorization_code",
        })
        token_data = token_resp.json()
        id_token = token_data.get("id_token", "")
        # Decode the id_token (no verify for speed — Google already verified the code exchange)
        import base64, json as _json
        payload_b64 = id_token.split(".")[1] + "=="
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        g_email  = payload.get("email", "")
        g_name   = payload.get("name", g_email.split("@")[0])
        g_avatar = payload.get("picture", "")
        g_sub    = payload.get("sub", "")

        user = get_user_by_email(g_email)
        if not user:
            uid = str(uuid.uuid4())
            create_user(uid, g_name, g_email, "", avatar=g_avatar)
            user = get_user_by_id(uid)
        elif g_avatar:
            update_user_google(user["id"], g_avatar)

        token = _make_token(user["id"])
        return RedirectResponse(f"{_FRONTEND_URL}/login?token={token}")
    except Exception as e:
        return RedirectResponse(f"{_FRONTEND_URL}/login?error=google_failed")
