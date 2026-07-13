from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Membership, User, Workspace
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    id: str
    email: str


@router.post("/auth/register", status_code=201)
def register(body: Credentials, db: Session = Depends(get_db)) -> TokenOut:
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    ws = Workspace(name="Default", owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="owner"))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter_by(email=body.email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(id=user.id, email=user.email)
