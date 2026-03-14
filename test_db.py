import asyncio
import asyncpg
import ssl

async def test():
    try:
        ssl_ctx = ssl.create_default_context()
        conn = await asyncpg.connect(
            user="neondb_owner",
            password="npg_GQY6B0PWEiDz",
            host="ep-floral-frog-ans6vdag-pooler.c-6.us-east-1.aws.neon.tech",
            database="neondb",
            ssl=ssl_ctx,
        )
        result = await conn.fetchval("SELECT 1")
        print(f"DB connection OK: {result}")
        await conn.close()
    except Exception as e:
        print(f"DB connection FAILED: {e}")

asyncio.run(test())
