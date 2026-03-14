import os
import uuid
import random
from datetime import datetime, timezone
from typing import Dict, List
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect,
    status, Query, UploadFile, File,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, update

from database import get_db, init_db
from models import User, FriendRequest, FriendRequestStatus, Message, MessageStatus
from schemas import (
    SignupRequest, LoginRequest, TokenResponse, UserOut,
    FriendRequestOut, MessageOut,
)
from auth import hash_password, verify_password, create_access_token, get_current_user
from jose import JWTError, jwt
from auth import SECRET_KEY, ALGORITHM

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

AVATAR_COLORS = [
    "#6c63ff", "#a855f7", "#ec4899", "#f43f5e",
    "#f97316", "#eab308", "#22c55e", "#14b8a6",
    "#06b6d4", "#3b82f6",
]


# ── WebSocket connection manager ──────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[user_id] = websocket

    def disconnect(self, user_id: str, ws: WebSocket):
        if self.active.get(user_id) == ws:
            self.active.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return user_id in self.active

    async def send_personal(self, user_id: str, data: dict):
        ws = self.active.get(user_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                if self.active.get(user_id) == ws:
                    self.active.pop(user_id, None)

    async def broadcast_to_friends(self, user_id: str, data: dict, db: AsyncSession):
        """Send data to all friends of user_id who are online."""
        result = await db.execute(
            select(FriendRequest).where(
                or_(
                    FriendRequest.sender_id == user_id,
                    FriendRequest.receiver_id == user_id,
                ),
                FriendRequest.status == FriendRequestStatus.ACCEPTED,
            )
        )
        for fr in result.scalars().all():
            fid = fr.receiver_id if fr.sender_id == user_id else fr.sender_id
            await self.send_personal(fid, data)


manager = ConnectionManager()


# ── Lifespan ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ══════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════

@app.post("/api/auth/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        avatar_color=random.choice(AVATAR_COLORS),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@app.get("/api/auth/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ══════════════════════════════════════════════════════
#  USER SEARCH
# ══════════════════════════════════════════════════════

@app.get("/api/users/search", response_model=UserOut | None)
async def search_user(
    uid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.uid == uid.strip().upper()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ══════════════════════════════════════════════════════
#  FRIEND REQUESTS
# ══════════════════════════════════════════════════════

@app.post("/api/friends/request", response_model=FriendRequestOut)
async def send_friend_request(
    receiver_uid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.uid == receiver_uid.strip().upper()))
    receiver = result.scalar_one_or_none()
    if not receiver:
        raise HTTPException(status_code=404, detail="User not found")
    if receiver.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself")

    result = await db.execute(
        select(FriendRequest).where(
            or_(
                and_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == receiver.id),
                and_(FriendRequest.sender_id == receiver.id, FriendRequest.receiver_id == current_user.id),
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.status == FriendRequestStatus.ACCEPTED:
            raise HTTPException(status_code=400, detail="Already friends")
        if existing.status == FriendRequestStatus.PENDING:
            raise HTTPException(status_code=400, detail="Request already pending")
        existing.status = FriendRequestStatus.PENDING
        existing.sender_id = current_user.id
        existing.receiver_id = receiver.id
        await db.commit()
        await db.refresh(existing)
        fr = existing
    else:
        fr = FriendRequest(
            id=str(uuid.uuid4()),
            sender_id=current_user.id,
            receiver_id=receiver.id,
        )
        db.add(fr)
        await db.commit()
        await db.refresh(fr)

    await manager.send_personal(receiver.id, {
        "type": "friend_request",
        "from_username": current_user.username,
        "from_uid": current_user.uid,
        "request_id": fr.id,
    })

    return FriendRequestOut(
        id=fr.id, sender_id=fr.sender_id, receiver_id=fr.receiver_id,
        sender_username=current_user.username, sender_uid=current_user.uid,
        receiver_username=receiver.username, receiver_uid=receiver.uid,
        status=fr.status.value, created_at=fr.created_at,
    )


@app.get("/api/friends/requests", response_model=List[FriendRequestOut])
async def get_friend_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(FriendRequest).where(
            FriendRequest.receiver_id == current_user.id,
            FriendRequest.status == FriendRequestStatus.PENDING,
        )
    )
    out = []
    for r in result.scalars().all():
        sr = await db.execute(select(User).where(User.id == r.sender_id))
        sender = sr.scalar_one_or_none()
        out.append(FriendRequestOut(
            id=r.id, sender_id=r.sender_id, receiver_id=r.receiver_id,
            sender_username=sender.username if sender else "Unknown",
            sender_uid=sender.uid if sender else "",
            status=r.status.value, created_at=r.created_at,
        ))
    return out


@app.post("/api/friends/accept/{request_id}")
async def accept_friend_request(
    request_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(FriendRequest).where(FriendRequest.id == request_id))
    fr = result.scalar_one_or_none()
    if not fr or fr.receiver_id != current_user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    if fr.status != FriendRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request already handled")

    fr.status = FriendRequestStatus.ACCEPTED
    await db.commit()

    await manager.send_personal(fr.sender_id, {
        "type": "request_accepted",
        "by_username": current_user.username,
        "by_uid": current_user.uid,
        "by_id": current_user.id,
    })
    return {"message": "Friend request accepted"}


@app.post("/api/friends/decline/{request_id}")
async def decline_friend_request(
    request_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(FriendRequest).where(FriendRequest.id == request_id))
    fr = result.scalar_one_or_none()
    if not fr or fr.receiver_id != current_user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    fr.status = FriendRequestStatus.DECLINED
    await db.commit()
    return {"message": "Friend request declined"}


@app.get("/api/friends", response_model=List[UserOut])
async def get_friends(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(FriendRequest).where(
            or_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == current_user.id),
            FriendRequest.status == FriendRequestStatus.ACCEPTED,
        )
    )
    friends = []
    for fr in result.scalars().all():
        fid = fr.receiver_id if fr.sender_id == current_user.id else fr.sender_id
        ur = await db.execute(select(User).where(User.id == fid))
        friend = ur.scalar_one_or_none()
        if friend:
            # Update online status from manager
            friend.is_online = manager.is_online(friend.id)
            friends.append(friend)
    return friends


# ══════════════════════════════════════════════════════
#  MESSAGES (history)
# ══════════════════════════════════════════════════════

@app.get("/api/messages/{friend_id}", response_model=List[MessageOut])
async def get_messages(
    friend_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Message)
        .where(
            or_(
                and_(Message.sender_id == current_user.id, Message.receiver_id == friend_id),
                and_(Message.sender_id == friend_id, Message.receiver_id == current_user.id),
            )
        )
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    out = []
    for m in messages:
        reply_preview = None
        if m.reply_to_id:
            rr = await db.execute(select(Message).where(Message.id == m.reply_to_id))
            replied = rr.scalar_one_or_none()
            if replied:
                reply_preview = (replied.content or "[file]")[:80]
        out.append(MessageOut(
            id=m.id, sender_id=m.sender_id, receiver_id=m.receiver_id,
            content=m.content, file_url=m.file_url, file_name=m.file_name,
            file_type=m.file_type, reply_to_id=m.reply_to_id,
            reply_preview=reply_preview,
            status=m.status.value if m.status else "sent",
            is_deleted=m.is_deleted, created_at=m.created_at,
        ))

    # Mark unread messages as read
    await db.execute(
        update(Message)
        .where(
            Message.sender_id == friend_id,
            Message.receiver_id == current_user.id,
            Message.status != MessageStatus.READ,
        )
        .values(status=MessageStatus.READ)
    )
    await db.commit()

    # Notify the friend that messages were read
    await manager.send_personal(friend_id, {
        "type": "messages_read",
        "by": current_user.id,
    })

    return out


# ══════════════════════════════════════════════════════
#  FILE UPLOAD
# ══════════════════════════════════════════════════════

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "file")[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, unique_name)

    contents = await file.read()
    with open(path, "wb") as f:
        f.write(contents)

    content_type = file.content_type or ""
    if content_type.startswith("image"):
        file_type = "image"
    elif content_type.startswith("video"):
        file_type = "video"
    else:
        file_type = "document"

    return {
        "file_url": f"http://localhost:8000/uploads/{unique_name}",
        "file_name": file.filename,
        "file_type": file_type,
    }


# ══════════════════════════════════════════════════════
#  WEBSOCKET  /ws?token=...
# ══════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    await websocket.accept()

    # Authenticate
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001)
            return
    except JWTError:
        await websocket.close(code=4001)
        return

    async for db in get_db():
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001)
            return

        # Set user online
        user.is_online = True
        await db.commit()

        # Just store the active socket
        manager.active[user_id] = websocket

        # Broadcast online status
        await manager.broadcast_to_friends(user_id, {
            "type": "presence",
            "user_id": user_id,
            "is_online": True,
        }, db)

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "message")

                # ── Chat message ──
                if msg_type == "message":
                    receiver_id = data.get("to")
                    content = data.get("content", "").strip()
                    file_url = data.get("file_url")
                    file_name = data.get("file_name")
                    file_type = data.get("file_type")
                    reply_to_id = data.get("reply_to_id")

                    if not receiver_id or (not content and not file_url):
                        continue

                    msg = Message(
                        id=str(uuid.uuid4()),
                        sender_id=user_id,
                        receiver_id=receiver_id,
                        content=content if content else None,
                        file_url=file_url,
                        file_name=file_name,
                        file_type=file_type,
                        reply_to_id=reply_to_id,
                        status=MessageStatus.DELIVERED if manager.is_online(receiver_id) else MessageStatus.SENT,
                    )
                    db.add(msg)
                    await db.commit()
                    await db.refresh(msg)

                    reply_preview = None
                    if reply_to_id:
                        rr = await db.execute(select(Message).where(Message.id == reply_to_id))
                        replied = rr.scalar_one_or_none()
                        if replied:
                            reply_preview = (replied.content or "[file]")[:80]

                    payload = {
                        "type": "message",
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "receiver_id": msg.receiver_id,
                        "content": msg.content,
                        "file_url": msg.file_url,
                        "file_name": msg.file_name,
                        "file_type": msg.file_type,
                        "reply_to_id": msg.reply_to_id,
                        "reply_preview": reply_preview,
                        "status": msg.status.value,
                        "is_deleted": False,
                        "created_at": msg.created_at.isoformat(),
                    }
                    await manager.send_personal(receiver_id, payload)
                    await manager.send_personal(user_id, payload)

                # ── Typing indicator ──
                elif msg_type == "typing":
                    receiver_id = data.get("to")
                    if receiver_id:
                        await manager.send_personal(receiver_id, {
                            "type": "typing",
                            "user_id": user_id,
                            "is_typing": data.get("is_typing", True),
                        })

                # ── Mark messages as read ──
                elif msg_type == "read":
                    sender_id = data.get("from")
                    if sender_id:
                        await db.execute(
                            update(Message)
                            .where(
                                Message.sender_id == sender_id,
                                Message.receiver_id == user_id,
                                Message.status != MessageStatus.READ,
                            )
                            .values(status=MessageStatus.READ)
                        )
                        await db.commit()
                        await manager.send_personal(sender_id, {
                            "type": "messages_read",
                            "by": user_id,
                        })

                # ── Delete message ──
                elif msg_type == "delete":
                    message_id = data.get("message_id")
                    if message_id:
                        mr = await db.execute(select(Message).where(Message.id == message_id))
                        m = mr.scalar_one_or_none()
                        if m and m.sender_id == user_id:
                            m.is_deleted = True
                            m.content = None
                            m.file_url = None
                            await db.commit()
                            other_id = m.receiver_id
                            del_payload = {"type": "message_deleted", "message_id": message_id}
                            await manager.send_personal(other_id, del_payload)
                            await manager.send_personal(user_id, del_payload)

                # ── WebRTC signaling (video call) ──
                elif msg_type in ("call_offer", "call_answer", "ice_candidate", "call_end", "call_reject"):
                    target_id = data.get("to")
                    if target_id:
                        await manager.send_personal(target_id, {
                            **data,
                            "from": user_id,
                        })

        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"WebSocket Exception: {e}")
        finally:
            manager.disconnect(user_id, websocket)
            # Only broadcast offline if they really disconnected
            if user_id not in manager.active:
                user.is_online = False
                user.last_seen = datetime.now(timezone.utc)
                await db.commit()
                await manager.broadcast_to_friends(user_id, {
                    "type": "presence",
                    "user_id": user_id,
                    "is_online": False,
                }, db)
