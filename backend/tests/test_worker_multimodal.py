import base64
import json
from types import SimpleNamespace

import pytest


def _workspace(db, email: str):
    from app.models import User, Workspace

    user = User(email=email, password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name=email, owner_id=user.id)
    db.add(workspace)
    db.flush()
    return workspace


def _adapter(key, scorer):
    from app.evals.base import CallableAdapter

    return CallableAdapter(
        key=key,
        framework="test",
        display_name=key,
        description=key,
        requires=frozenset(),
        scorer=scorer,
        sample_kind="multimodal",
        resource_fn=lambda config: frozenset(),
    )


def _static_run(db, workspace, rows, object_store, *, metric_keys=("test.image",)):
    from app.models import Dataset, Run

    dataset = Dataset(
        workspace_id=workspace.id,
        name="Multimodal rows",
        format="json",
        row_count=len(rows),
        storage_path=f"datasets/{workspace.id}/multimodal.json",
        schema_map={
            "input": "input",
            "actual_output": "actual_output",
            "metadata": "metadata",
            "tags": "tags",
        },
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Multimodal static",
        mode="static",
        metric_config={"metrics": [{"key": key} for key in metric_keys]},
        judge_config={},
        definition_snapshot={
            "schema_map": dict(dataset.schema_map),
            "sample": {"kind": "multimodal"},
        },
    )
    db.add(run)
    db.commit()
    object_store[dataset.storage_path] = json.dumps(rows).encode()
    return run, dataset


def _asset(db, workspace, object_store, *, asset_id="asset-1", data=b"image"):
    from app.assets import asset_storage_path
    from app.models import EvaluationAsset

    path = asset_storage_path(workspace.id, asset_id)
    asset = EvaluationAsset(
        id=asset_id,
        workspace_id=workspace.id,
        mime_type="image/png",
        byte_size=len(data),
        source_url=None,
        storage_path=path,
    )
    db.add(asset)
    db.flush()
    object_store[path] = data
    return asset


def test_static_worker_hydrates_asset_and_persists_safe_multimodal_details(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.evals.base import MetricScore
    from app.evals.samples import MultimodalSample
    from app.models import RunResult

    workspace = _workspace(db, "multimodal-asset@example.com")
    asset = _asset(db, workspace, object_store, data=b"stored-png")
    rows = [
        {
            "input": [
                {"type": "text", "text": "Describe the chart"},
                {"type": "image", "asset_id": asset.id},
            ],
            "actual_output": [
                {"type": "text", "text": "Revenue rises"},
                {"type": "image", "asset_id": asset.id},
            ],
            "metadata": {"dataset": "charts"},
            "tags": ["vision"],
        }
    ]
    run, _ = _static_run(db, workspace, rows, object_store)
    scored = []

    def scorer(sample, judge, config):
        assert isinstance(sample, MultimodalSample)
        assert sample.input[1].data_base64 == base64.b64encode(b"stored-png").decode()
        assert sample.actual_output[1].data_base64 == base64.b64encode(
            b"stored-png"
        ).decode()
        assert sample.input[1].mime_type == "image/png"
        scored.append(sample)
        return MetricScore("test.image", 0.9, "ok", True)

    monkeypatch.setattr(tasks, "METRICS", {"test.image": _adapter("test.image", scorer)})

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    details = result.details["sample"]
    encoded = json.dumps(details)
    assert len(scored) == 1
    assert result.input == "Describe the chart"
    assert result.actual == "Revenue rises"
    assert result.expected is None
    assert result.contexts is None
    assert set(details) == {
        "kind",
        "input",
        "actual_output",
        "metadata",
        "tags",
        "source",
        "normalizer_revision",
    }
    assert details["kind"] == "multimodal"
    assert details["metadata"] == {"dataset": "charts"}
    assert details["tags"] == ["vision"]
    assert details["source"]["row_index"] == 0
    assert details["normalizer_revision"] == "1"
    assert details["input"][1] == {
        "type": "image",
        "asset_id": asset.id,
        "mime_type": "image/png",
    }
    assert "data_base64" not in encoded
    assert "url" not in encoded


def test_remote_url_is_snapshotted_and_fetched_once_per_run(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.evals.base import MetricScore
    from app.models import EvaluationAsset, RunResult

    workspace = _workspace(db, "multimodal-url@example.com")
    remote_url = "https://images.example/chart.png"
    rows = [
        {
            "input": [{"type": "text", "text": f"Question {index}"}],
            "actual_output": [
                {"type": "text", "text": f"Answer {index}"},
                {"type": "image", "url": remote_url},
            ],
        }
        for index in range(2)
    ]
    run, _ = _static_run(db, workspace, rows, object_store)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b"remote-png", "image/png"

    monkeypatch.setattr(tasks, "fetch_remote_image", fetch, raising=False)

    def scorer(sample, judge, config):
        image = sample.actual_output[1]
        assert image.asset_id
        assert image.url is None
        assert image.data_base64 == base64.b64encode(b"remote-png").decode()
        return MetricScore("test.image", 1.0, "ok", True)

    monkeypatch.setattr(tasks, "METRICS", {"test.image": _adapter("test.image", scorer)})

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    snapshots = db.query(EvaluationAsset).filter_by(workspace_id=workspace.id).all()
    results = db.query(RunResult).filter_by(run_id=run.id).order_by(RunResult.row_index).all()
    assert fetched == [remote_url]
    assert len(snapshots) == 1
    assert snapshots[0].run_id == run.id
    assert snapshots[0].source_url == remote_url
    assert object_store[snapshots[0].storage_path] == b"remote-png"
    for result in results:
        image = result.details["sample"]["actual_output"][1]
        assert image == {
            "type": "image",
            "asset_id": snapshots[0].id,
            "mime_type": "image/png",
        }
        assert remote_url not in json.dumps(result.details)


def test_snapshot_recovery_reuses_committed_run_asset_without_remote_refetch(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.evals.samples import MultimodalSample
    from app.models import EvaluationAsset

    workspace = _workspace(db, "multimodal-snapshot-recovery@example.com")
    run, _ = _static_run(db, workspace, [], object_store)
    remote_url = "https://images.example/recover.png"
    fetches = []

    def fetch(url):
        fetches.append(url)
        return b"remote-png", "image/png"

    monkeypatch.setattr(tasks, "fetch_remote_image", fetch, raising=False)
    first = MultimodalSample(
        input=[{"type": "image", "url": remote_url}],
        actual_output=[{"type": "text", "text": "first attempt"}],
    )
    tasks._hydrate_image_blocks(db, workspace.id, run.id, first, {})

    # A fresh cache models worker recovery after snapshot commit but before result commit.
    recovered = MultimodalSample(
        input=[{"type": "image", "url": remote_url}],
        actual_output=[{"type": "text", "text": "recovered attempt"}],
    )
    tasks._hydrate_image_blocks(db, workspace.id, run.id, recovered, {})

    snapshots = db.query(EvaluationAsset).filter_by(run_id=run.id).all()
    assert fetches == [remote_url]
    assert len(snapshots) == 1
    assert first.input[0].asset_id == snapshots[0].id
    assert recovered.input[0].asset_id == snapshots[0].id


def test_missing_asset_fails_only_its_row(db, monkeypatch, object_store):
    from app import tasks
    from app.evals.base import MetricScore
    from app.models import Run, RunResult

    workspace = _workspace(db, "multimodal-missing@example.com")
    asset = _asset(db, workspace, object_store, data=b"valid")
    rows = [
        {
            "input": [{"type": "text", "text": "Bad row"}],
            "actual_output": [{"type": "image", "asset_id": "missing"}],
        },
        {
            "input": [{"type": "text", "text": "Good row"}],
            "actual_output": [{"type": "image", "asset_id": asset.id}],
        },
    ]
    run, _ = _static_run(db, workspace, rows, object_store)
    scored = []

    def scorer(sample, judge, config):
        scored.append(sample)
        return MetricScore("test.image", 1.0, "ok", True)

    monkeypatch.setattr(tasks, "METRICS", {"test.image": _adapter("test.image", scorer)})

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    results = db.query(RunResult).filter_by(run_id=run.id).order_by(RunResult.row_index).all()
    assert db.get(Run, run.id).status == "completed"
    assert results[0].error == "Image asset not found"
    assert results[1].error is None
    assert len(scored) == 1


def test_recovery_rebuilds_and_rehydrates_without_remote_refetch(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.evals.base import MetricScore
    from app.evals.samples import MultimodalSample
    from app.models import RunResult

    workspace = _workspace(db, "multimodal-recovery@example.com")
    asset = _asset(db, workspace, object_store, data=b"recovered")
    rows = [
        {
            "input": [{"type": "text", "text": "Question"}],
            "actual_output": [
                {"type": "text", "text": "Answer"},
                {"type": "image", "asset_id": asset.id},
            ],
        }
    ]
    run, _ = _static_run(
        db,
        workspace,
        rows,
        object_store,
        metric_keys=("test.done", "test.remaining"),
    )
    db.add(
        RunResult(
            workspace_id=workspace.id,
            run_id=run.id,
            row_index=0,
            input="Question",
            actual="Answer",
            scores={
                "test.done": {
                    "score": 1.0,
                    "reason": "done",
                    "passed": True,
                    "error": None,
                    "in_progress": False,
                }
            },
            details={
                "sample": {
                    "kind": "multimodal",
                    "input": [{"type": "text", "text": "Question"}],
                    "actual_output": [
                        {"type": "text", "text": "Answer"},
                        {
                            "type": "image",
                            "asset_id": asset.id,
                            "mime_type": "image/png",
                        },
                    ],
                    "metadata": {"recovered": True},
                    "tags": ["resume"],
                    "source": {"row_index": 0},
                    "normalizer_revision": "1",
                }
            },
        )
    )
    db.commit()
    calls = []

    def done(*args):
        raise AssertionError("completed metric repeated")

    def remaining(sample, judge, config):
        assert isinstance(sample, MultimodalSample)
        assert sample.actual_output[1].data_base64 == base64.b64encode(
            b"recovered"
        ).decode()
        assert sample.metadata == {"recovered": True}
        assert sample.tags == ["resume"]
        calls.append("remaining")
        return MetricScore("test.remaining", 0.8, "ok", True)

    monkeypatch.setattr(
        tasks,
        "fetch_remote_image",
        lambda url: (_ for _ in ()).throw(AssertionError("remote refetched")),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "METRICS",
        {
            "test.done": _adapter("test.done", done),
            "test.remaining": _adapter("test.remaining", remaining),
        },
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert calls == ["remaining"]
    assert result.scores["test.done"]["score"] == 1.0
    assert result.scores["test.remaining"]["score"] == 0.8


def test_recovery_hydration_failure_terminalizes_in_progress_metric(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.models import RunResult

    workspace = _workspace(db, "multimodal-recovery-failure@example.com")
    rows = [
        {
            "input": [{"type": "text", "text": "Question"}],
            "actual_output": [{"type": "image", "asset_id": "missing"}],
        }
    ]
    run, _ = _static_run(db, workspace, rows, object_store)
    db.add(
        RunResult(
            workspace_id=workspace.id,
            run_id=run.id,
            row_index=0,
            input="Question",
            actual="",
            scores={
                "test.image": {
                    "score": None,
                    "reason": None,
                    "passed": None,
                    "error": "Evaluation interrupted before its result was persisted",
                    "in_progress": True,
                }
            },
            details={
                "sample": {
                    "kind": "multimodal",
                    "input": [{"type": "text", "text": "Question"}],
                    "actual_output": [
                        {"type": "image", "asset_id": "missing"}
                    ],
                    "metadata": {},
                    "tags": [],
                    "source": {"row_index": 0},
                    "normalizer_revision": "1",
                }
            },
        )
    )
    db.commit()
    monkeypatch.setattr(
        tasks,
        "METRICS",
        {
            "test.image": _adapter(
                "test.image",
                lambda *args: (_ for _ in ()).throw(
                    AssertionError("scorer called after hydration failure")
                ),
            )
        },
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert result.error == "Image asset not found"
    assert result.scores["test.image"]["in_progress"] is False
    assert "interrupted" in result.scores["test.image"]["error"].lower()


def test_ingestion_multimodal_artifact_is_hydrated_and_scored(
    db, monkeypatch, object_store
):
    from app import tasks
    from app.evals.base import MetricScore
    from app.evals.samples import MultimodalSample
    from app.models import EvaluationArtifact, Run, RunResult

    workspace = _workspace(db, "multimodal-ingestion@example.com")
    asset = _asset(db, workspace, object_store, data=b"ingested")
    sample = {
        "kind": "multimodal",
        "input": [{"type": "text", "text": "Read image"}],
        "actual_output": [
            {"type": "text", "text": "Image read"},
            {"type": "image", "asset_id": asset.id},
        ],
        "metadata": {"mode": "ingestion"},
        "tags": ["api"],
    }
    artifact = EvaluationArtifact(
        workspace_id=workspace.id,
        sample_kind="multimodal",
        idempotency_key="multimodal-worker",
        request_hash="c" * 64,
        storage_path=f"evaluation-artifacts/{workspace.id}/multimodal.json",
    )
    db.add(artifact)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=None,
        artifact_id=artifact.id,
        name="Multimodal ingestion",
        mode="ingestion",
        metric_config={"metrics": [{"key": "test.image"}]},
        judge_config={},
        definition_snapshot={"sample": {"kind": "multimodal"}},
    )
    db.add(run)
    db.commit()
    object_store[artifact.storage_path] = json.dumps(sample).encode()
    scored = []

    def scorer(row, judge, config):
        assert isinstance(row, MultimodalSample)
        assert row.actual_output[1].data_base64 == base64.b64encode(
            b"ingested"
        ).decode()
        scored.append(row)
        return MetricScore("test.image", 1.0, "ok", True)

    monkeypatch.setattr(tasks, "METRICS", {"test.image": _adapter("test.image", scorer)})

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert len(scored) == 1
    assert result.input == "Read image"
    assert result.actual == "Image read"
    assert result.scores["test.image"]["score"] == 1.0


def test_snapshot_commit_failure_rolls_back_and_attempts_logged_storage_cleanup(
    monkeypatch, caplog
):
    from app import tasks
    from app.assets import asset_storage_path
    from app.evals.samples import MultimodalSample

    class FailingDB:
        rolled_back = False

        def query(self, *args):
            return self

        def filter_by(self, **kwargs):
            return self

        def first(self):
            return None

        def commit(self):
            raise RuntimeError("snapshot commit failed")

        def rollback(self):
            self.rolled_back = True

    db = FailingDB()
    sample = MultimodalSample(
        input=[{"type": "text", "text": "Question"}],
        actual_output=[
            {"type": "image", "url": "https://images.example/fail.png"}
        ],
    )
    deleted = []
    expected_path = asset_storage_path("workspace-1", "snapshot-1")

    monkeypatch.setattr(
        tasks,
        "fetch_remote_image",
        lambda url: (b"remote", "image/png"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "store_image_asset",
        lambda *args, **kwargs: SimpleNamespace(id="snapshot-1"),
        raising=False,
    )

    def cleanup(path):
        deleted.append(path)
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(tasks.storage, "delete_object", cleanup)

    with caplog.at_level("ERROR"), pytest.raises(
        RuntimeError, match="snapshot commit failed"
    ):
        tasks._hydrate_image_blocks(db, "workspace-1", "run-1", sample, {})

    assert db.rolled_back is True
    assert deleted == [expected_path]
    assert "Failed to clean up image snapshot" in caplog.text
