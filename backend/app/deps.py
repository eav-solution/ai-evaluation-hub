from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Membership, User, Workspace
from app.security import decode_access_token


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = decode_access_token(authorization.removeprefix("Bearer "))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


def get_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Workspace:
    membership = (
        db.query(Membership)
        .filter_by(workspace_id=workspace_id, user_id=user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return db.get(Workspace, workspace_id)
