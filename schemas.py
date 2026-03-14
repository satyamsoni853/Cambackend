from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Auth ──────────────────────────────────────────────
class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── User ──────────────────────────────────────────────
class UserOut(BaseModel):
    id: str
    uid: str
    username: str
    email: str
    avatar_color: str | None = "#6c63ff"
    is_online: bool = False
    last_seen: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Friend Request ────────────────────────────────────
class FriendRequestOut(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    sender_username: str | None = None
    sender_uid: str | None = None
    receiver_username: str | None = None
    receiver_uid: str | None = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Message ───────────────────────────────────────────
class MessageOut(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    content: str | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_type: str | None = None
    reply_to_id: str | None = None
    reply_preview: str | None = None
    status: str = "sent"
    is_deleted: bool = False
    created_at: datetime

    class Config:
        from_attributes = True
