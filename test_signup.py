import asyncio
from database import engine, async_session, init_db
from models import User
from auth import hash_password
from sqlalchemy import select, text
import uuid
import traceback

async def test():
    log = []
    try:
        await init_db()
        log.append("Tables OK")
    except Exception as e:
        log.append(f"Init DB failed: {traceback.format_exc()}")

    async with async_session() as db:
        try:
            result = await db.execute(text("SELECT 1"))
            log.append(f"Simple query OK: {result.scalar()}")
        except Exception as e:
            log.append(f"Simple query FAILED: {traceback.format_exc()}")
            with open("debug_log.txt", "w") as f:
                f.write("\n".join(log))
            return

    async with async_session() as db:
        try:
            result = await db.execute(select(User).where(User.email == "test1@test.com"))
            existing = result.scalar_one_or_none()
            if existing:
                log.append(f"User exists: {existing.username} / {existing.uid}")
                with open("debug_log.txt", "w") as f:
                    f.write("\n".join(log))
                return
            log.append("No existing user")

            pw_hash = hash_password("test1234")
            log.append(f"Hash: {pw_hash[:30]}")

            user = User(
                id=str(uuid.uuid4()),
                username="TestUser1",
                email="test1@test.com",
                hashed_password=pw_hash,
            )
            db.add(user)
            log.append("Added to session")
            await db.commit()
            log.append("Committed")
            await db.refresh(user)
            log.append(f"Created: {user.username} UID: {user.uid}")
        except Exception as e:
            log.append(f"ERROR: {traceback.format_exc()}")

    with open("debug_log.txt", "w") as f:
        f.write("\n".join(log))

asyncio.run(test())
