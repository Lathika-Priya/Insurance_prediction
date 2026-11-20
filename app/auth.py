"""Local accounts and revocable, server-side sessions for the FastAPI app."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
COOKIE_NAME = "carewise_session"
SESSION_SECONDS = 12 * 60 * 60
REMEMBER_SECONDS = 7 * 24 * 60 * 60
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@contextmanager
def database():
    path = Path(os.environ.get("AUTH_DB_PATH", str(ROOT / "data" / "auth.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS latest_assessments (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                result_json TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS auth_attempts (
                bucket TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "role" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt.hex()}${key.hex()}"


# Keep password verification work similar for unknown and existing accounts.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterInput(LoginInput):
    name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Enter a name with at least 2 characters.")
        return value


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin != str(request.base_url).rstrip("/")
    ):
        raise HTTPException(403, "This request must come from this website.")


def limit_auth_attempts(request: Request):
    """Persistent per-client limit, shared by login and registration."""
    same_origin(request)
    address = request.client.host if request.client else "local"
    bucket = hashlib.sha256(address.encode()).hexdigest()
    now = int(time.time())
    with database() as db:
        db.execute("DELETE FROM auth_attempts WHERE expires_at <= ?", (now,))
        db.execute(
            """INSERT INTO auth_attempts VALUES (?, 1, ?)
               ON CONFLICT(bucket) DO UPDATE SET attempts = attempts + 1""",
            (bucket, now + 300),
        )
        row = db.execute("SELECT attempts, expires_at FROM auth_attempts WHERE bucket = ?", (bucket,)).fetchone()
    if row["attempts"] > 30:
        raise HTTPException(429, "Too many sign-in attempts. Please try again in a few minutes.",
                            headers={"Retry-After": str(max(1, row["expires_at"] - now))})


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_session(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 128:
        return None
    with database() as db:
        row = db.execute(
            """SELECT users.id, users.name, users.email, users.role, sessions.csrf_token
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (token_hash(token), int(time.time())),
        ).fetchone()
    return dict(row) if row else None


def require_user(request: Request):
    session = current_session(request)
    if not session:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    return session


def require_csrf(request: Request, session=Depends(require_user)):
    same_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied, session["csrf_token"]):
        raise HTTPException(403, "Please refresh this page and try again.")
    return session


def public_session(session):
    return {
        "user": {**{key: session[key] for key in ("id", "name", "email")}, "role": session.get("role", "user")},
        "csrf_token": session["csrf_token"],
    }


def create_session(request, response, user, remember):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    lifetime = REMEMBER_SECONDS if remember else SESSION_SECONDS
    now = int(time.time())
    with database() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        old_token = request.cookies.get(COOKIE_NAME)
        if old_token:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old_token),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (token_hash(token), user["id"], csrf, now + lifetime))
    response.set_cookie(
        COOKIE_NAME, token, max_age=lifetime if remember else None,
        httponly=True, secure=os.environ.get("COOKIE_SECURE", "0") == "1",
        samesite="lax", path="/",
    )
    return public_session({**dict(user), "csrf_token": csrf})


@router.post("/register", status_code=201, dependencies=[Depends(limit_auth_attempts)])
def register(payload: RegisterInput, request: Request, response: Response):
    password_hash = hash_password(payload.password)
    try:
        with database() as db:
            cursor = db.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (payload.name, payload.email, password_hash, int(time.time())),
            )
            user = {"id": cursor.lastrowid, "name": payload.name, "email": payload.email}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Please sign in.")
    return create_session(request, response, user, payload.remember_me)


@router.post("/admin-login", dependencies=[Depends(limit_auth_attempts)])
@router.post("/login", dependencies=[Depends(limit_auth_attempts)])
def login(payload: LoginInput, request: Request, response: Response):
    with database() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (payload.email,)).fetchone()
    valid = verify_password(payload.password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
    if not user or not valid or (request.url.path.endswith("/admin-login") and user["role"] != "admin"):
        raise HTTPException(401, "Email or password is incorrect.")
    return create_session(request, response, user, payload.remember_me)


@router.get("/me")
def me(session=Depends(require_user)):
    return public_session(session)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session=Depends(require_csrf)):
    with database() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(request.cookies[COOKIE_NAME]),))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax",
                           secure=os.environ.get("COOKIE_SECURE", "0") == "1")
