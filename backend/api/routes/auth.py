from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from db.connection import get_session
from db.models import User

router = APIRouter()

class LoginRequest(BaseModel):
    username: str

class LoginResponse(BaseModel):
    user_id: str
    username: str

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Simple mock auth: Find user by username, or create if doesn't exist.
    """
    username_clean = body.username.strip().lower()
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
        
    async with get_session() as db:
        result = await db.execute(select(User).where(User.username == username_clean))
        user = result.scalar_one_or_none()
        
        if not user:
            # Auto-create for the prototype
            user = User(username=username_clean)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
        return LoginResponse(
            user_id=str(user.id),
            username=user.username
        )

from fastapi import Header
async def get_current_user_id(x_user_id: str = Header(..., description="The UUID of the authenticated user")) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing x-user-id header")
    return x_user_id

