import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

from openai import AsyncOpenAI

async def main():
    client = AsyncOpenAI(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.getenv("OPENAI_API_KEY", "")
    )
    model = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    print("Using base_url:", client.base_url)
    print("Using key:", client.api_key)
    print("Using model:", model)

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=50,
            temperature=0.7
        )
        print("Success:", resp.choices[0].message.content)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
