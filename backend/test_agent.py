import asyncio
from sqlmodel import Session
from app.database import engine
from app.models import User
from app.services.assistant.agent import run, ToolContext
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    with Session(engine) as session:
        user = session.query(User).first()
        ctx = ToolContext(session=session, user=user)
        ans = await run("how are you doing", ctx)
        print("Response 1:", ans.reply)
        
        ans2 = await run("show me the negative posts in gujarati from ahmedabad on reddit today", ctx)
        print("Response 2:", ans2.reply)

asyncio.run(main())
