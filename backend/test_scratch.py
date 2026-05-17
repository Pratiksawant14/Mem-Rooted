import asyncio
from db.connection import get_session
from core.extraction import extract_memories
from db.connection import init_db

async def main():
    print("Testing extraction...")
    await init_db()
    
    try:
        res = await extract_memories("hello")
        print("Extraction success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
