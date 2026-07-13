from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.deps import get_db, get_workspace
from app.models import RunResult, RunSummary, Workspace
from app.reports import build_payload, render_csv, render_html
from app.routers.runs import _get_run

router = APIRouter(prefix="/api/workspaces/{workspace_id}/runs", tags=["exports"])


def _export_data(run_id: str, workspace_id: str, db: Session):
    run = _get_run(run_id, workspace_id, db)
    summaries = (
        db.query(RunSummary)
        .filter_by(run_id=run.id, workspace_id=workspace_id)
        .order_by(RunSummary.metric_key)
        .all()
    )
    results = (
        db.query(RunResult)
        .filter_by(run_id=run.id, workspace_id=workspace_id)
        .order_by(RunResult.row_index)
        .all()
    )
    return run, summaries, results


@router.get("/{run_id}/report.html")
def report_html(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    run, summaries, results = _export_data(run_id, ws.id, db)
    return HTMLResponse(
        render_html(run, summaries, results),
        headers={"Content-Disposition": f'attachment; filename="run-{run.id}.html"'},
    )


@router.get("/{run_id}/results.csv")
def results_csv(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    run, _summaries, results = _export_data(run_id, ws.id, db)
    return Response(
        render_csv(run, results),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="run-{run.id}.csv"'},
    )


@router.get("/{run_id}/results.json")
def results_json(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    run, summaries, results = _export_data(run_id, ws.id, db)
    return JSONResponse(
        build_payload(run, summaries, results),
        headers={"Content-Disposition": f'attachment; filename="run-{run.id}.json"'},
    )
