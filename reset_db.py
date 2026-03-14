import asyncio
from database import engine, Base

async def reset():
    async with engine.begin() as conn:
        from models import User, FriendRequest, Message
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        print("All tables dropped and recreated!")

asyncio.run(reset())
