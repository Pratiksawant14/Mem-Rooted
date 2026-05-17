import httpx
import asyncio

async def main():
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "http://127.0.0.1:8000/api/chat/message",
                json={"message": "hello", "session_id": "00000000-0000-0000-0000-000000000000"},
                timeout=10.0
            )
            print(resp.status_code)
            print(resp.text)
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
