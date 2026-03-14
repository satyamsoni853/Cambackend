import asyncio
from database import init_db

async def test():
    try:
        await init_db()
        print("Tables created successfully!")
    except Exception as e:
        print(f"Error creating tables: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
