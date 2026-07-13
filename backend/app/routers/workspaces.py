from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, get_workspace
from app.models import Membership, User, Workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: str


class MemberIn(BaseModel):
    email: EmailStr
    role: Literal["owner", "member"]


class MemberOut(BaseModel):
    email: str
    role: str


@router.get("")
def list_workspaces(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[WorkspaceOut]:
    rows = (
        db.query(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .filter(Membership.user_id == user.id)
        .all()
    )
    return [WorkspaceOut(id=ws.id, name=ws.name, role=role) for ws, role in rows]


@router.post("", status_code=201)
def create_workspace(
    body: WorkspaceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    ws = Workspace(name=body.name, owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="owner"))
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role="owner")


@router.get("/{workspace_id}/members")
def list_members(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[MemberOut]:
    rows = (
        db.query(User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.workspace_id == ws.id)
        .all()
    )
    return [MemberOut(email=email, role=role) for email, role in rows]


@router.post("/{workspace_id}/members", status_code=201)
def add_member(
    body: MemberIn,
    ws: Workspace = Depends(get_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemberOut:
    caller = (
        db.query(Membership).filter_by(workspace_id=ws.id, user_id=user.id).one()
    )
    if caller.role != "owner":
        raise HTTPException(status_code=403, detail="Only owners can add members")
    target = db.query(User).filter_by(email=body.email).first()
    if target is None:
        raise HTTPException(status_code=404, detail="No user with that email")
    existing = (
        db.query(Membership)
        .filter_by(workspace_id=ws.id, user_id=target.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already a member")
    db.add(Membership(user_id=target.id, workspace_id=ws.id, role=body.role))
    db.commit()
    return MemberOut(email=target.email, role=body.role)
