import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_workspace
from app.endpoints import EndpointConfig, call_endpoint
from app.evals.base import EvalRow
from app.models import Workspace

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/endpoint-test",
    tags=["endpoints"],
)


class EndpointTestIn(BaseModel):
    config: EndpointConfig
    input: str = Field(min_length=1)
    expected_output: str | None = None
    contexts: list[str] | None = None


@router.post("")
def test_endpoint(
    body: EndpointTestIn,
    _workspace: Workspace = Depends(get_workspace),
) -> dict:
    row = EvalRow(
        input=body.input,
        actual_output="",
        expected_output=body.expected_output,
        contexts=body.contexts,
    )
    try:
        # Single attempt: interactive test button; retrying a slow endpoint
        # would outlast the ALB idle timeout in front of the api.
        answer, payload, latency_ms = call_endpoint(
            body.config.model_dump(),
            row,
            encrypted_headers=False,
            retries=0,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "raw_response": payload,
        "extracted_answer": answer,
        "latency_ms": latency_ms,
    }
