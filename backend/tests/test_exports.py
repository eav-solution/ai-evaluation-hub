import csv
import io


def _completed_run(db):
    from app.models import Dataset, Run, RunResult, RunSummary, Workspace

    workspace = db.query(Workspace).filter_by(name="Default").one()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Export data",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/export.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="<Export & report>",
        mode="static",
        metric_config={
            "metrics": [{"key": "deepeval.bias", "threshold": 0.5}]
        },
        endpoint_config={"headers": {"Authorization": "encrypted-secret"}},
        judge_config={"provider": "openai", "model": "judge"},
        status="completed",
        progress_done=1,
        progress_total=1,
    )
    db.add(run)
    db.flush()
    result = RunResult(
        workspace_id=workspace.id,
        run_id=run.id,
        row_index=0,
        input="Is this fair?",
        expected="Yes",
        actual="Yes, it is.",
        contexts=["Policy <one>"],
        scores={
            "deepeval.bias": {
                "score": 0.8,
                "reason": "No bias & no stereotypes",
                "passed": True,
                "error": None,
            }
        },
        latency_ms=42,
        details={
            "sample": {"context": ["Trusted <fact>"]},
            "trace": [{"type": "tool", "name": "search"}],
            "note": "café",
        },
        usage={"input_tokens": 12, "output_tokens": 4},
        estimated_cost=0.0012,
    )
    summary = RunSummary(
        workspace_id=workspace.id,
        run_id=run.id,
        metric_key="deepeval.bias",
        mean=0.8,
        min=0.8,
        max=0.8,
        p50=0.8,
        pass_rate=1.0,
        threshold=0.5,
    )
    db.add_all([result, summary])
    db.commit()
    return workspace, run, [summary], [result]


def test_export_serializers_preserve_nested_json_and_flatten_csv(
    client, auth_headers, db
):
    from app.reports import build_payload, render_csv

    _workspace, run, summaries, results = _completed_run(db)
    payload = build_payload(run, summaries, results)
    assert payload["results"][0]["scores"]["deepeval.bias"]["score"] == 0.8
    assert payload["results"][0]["details"]["note"] == "café"
    assert payload["results"][0]["details"]["sample"]["context"] == [
        "Trusted <fact>"
    ]
    assert payload["results"][0]["usage"] == {
        "input_tokens": 12,
        "output_tokens": 4,
    }
    assert payload["results"][0]["estimated_cost"] == 0.0012
    assert "endpoint_config" not in payload["run"]
    assert "judge_config" not in payload["run"]

    rows = list(csv.DictReader(io.StringIO(render_csv(run, results))))
    assert rows[0]["deepeval.bias.score"] == "0.8"
    assert rows[0]["deepeval.bias.passed"] == "true"
    assert rows[0]["contexts"] == '["Policy <one>"]'
    assert '"sample": {"context": ["Trusted <fact>"]}' in rows[0]["details"]
    assert '"trace": [{"type": "tool", "name": "search"}]' in rows[0]["details"]
    assert '"note": "café"' in rows[0]["details"]
    assert rows[0]["usage"] == '{"input_tokens": 12, "output_tokens": 4}'
    assert rows[0]["estimated_cost"] == "0.0012"


def test_html_report_is_self_contained_and_escaped(client, auth_headers, db):
    from app.reports import render_html

    _workspace, run, summaries, results = _completed_run(db)
    html = render_html(run, summaries, results)

    assert "<svg" in html
    assert "<style>" in html
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "&lt;Export &amp; report&gt;" in html
    assert "encrypted-secret" not in html
    assert "Result metadata" in html
    assert "Trusted context" in html
    assert "Trusted &lt;fact&gt;" in html
    assert "Usage" in html
    assert "input_tokens" in html
    assert "Estimated cost" in html
    assert "$0.001200" in html


def test_export_download_routes(client, auth_headers, db):
    workspace, run, _summaries, _results = _completed_run(db)
    base = f"/api/workspaces/{workspace.id}/runs/{run.id}"

    html = client.get(f"{base}/report.html", headers=auth_headers)
    csv_response = client.get(f"{base}/results.csv", headers=auth_headers)
    json_response = client.get(f"{base}/results.json", headers=auth_headers)

    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "attachment" in html.headers["content-disposition"]
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert json_response.status_code == 200
    assert json_response.json()["run"]["id"] == run.id
    result_response = client.get(f"{base}/results", headers=auth_headers)
    assert result_response.status_code == 200
    assert result_response.json()[0]["details"]["trace"][0]["name"] == "search"
    assert result_response.json()[0]["usage"]["input_tokens"] == 12
    assert result_response.json()[0]["estimated_cost"] == 0.0012


def test_exports_are_tenant_scoped(client, auth_headers, db):
    workspace, run, _summaries, _results = _completed_run(db)
    token = client.post(
        "/api/auth/register",
        json={"email": "export-intruder@example.com", "password": "password123"},
    ).json()["access_token"]

    response = client.get(
        f"/api/workspaces/{workspace.id}/runs/{run.id}/results.json",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
