# Phase 5 Multimodal and Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure image assets plus runnable offline and ingestion support for Image Coherence and Image Helpfulness, publish the remaining recommended presets, and verify the complete 25-card curated catalog.

**Architecture:** Store images as immutable workspace-scoped objects behind an `EvaluationAsset` row, never as base64 in the database. Remote HTTPS images are fetched with the same SSRF guards the endpoint caller uses and snapshotted before scoring. The worker hydrates every `ImageBlock` with bytes just before scoring; the DeepEval converter turns hydrated blocks into `MLLMImage` marker strings (DeepEval 4.1.0's multimodal contract), and the shared `ProviderLLM` judge learns to parse those markers back into provider vision messages. Reports render images through an authorized asset endpoint.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Alembic, Celery, httpx, boto3 object storage, DeepEval 4.1.0, Next.js 16, React 19, TypeScript, pytest, Vitest.

## Global Constraints

- Keep all 23 Phase 4 metric keys and add exactly two Phase 5 keys: `deepeval.image_coherence` and `deepeval.image_helpfulness`. Registry total: exactly 25.
- Both new adapters register category `general`, family `multimodal`, sample kind `multimodal`, resources `{"judge", "multimodal"}`.
- Only text and image content blocks are supported. PDF, video, and audio evaluation are excluded. Image generation/editing quality metrics are excluded.
- Image controls (spec-mandated): allow-listed MIME types `image/png`, `image/jpeg`, `image/webp`, `image/gif`; bounded size 5 MiB; fetch timeout and at most 3 redirects; DNS and resolved-address checks blocking loopback, link-local, private, and other non-public targets; workspace-scoped authorization; no local filesystem paths; object-storage `asset_id` references instead of relational-table base64.
- Remote images are fetched and snapshotted by the backend before scoring; raw payloads and image snapshots are immutable.
- Multimodal runs support static datasets and authenticated ingestion in this phase; endpoint mode returns `422` for multimodal selections (documented limitation, revisit after closeout).
- Add exactly three new presets — `conversational` (Conversation Completeness, Turn Relevancy, Role Adherence), `mcp` (MCP Task Completion, MCP Use), `multimodal` (Image Coherence, Image Helpfulness) — and change no existing preset.
- DeepEval multimodal contract (probed on 4.1.0): images travel as `[DEEPEVAL:IMAGE:<id>]` markers inside prompt/output strings backed by the module-level `_MLLM_IMAGE_REGISTRY`; the parser is `MLLMImage.parse_multimodal_string(s)` (there is **no** `LLMTestCase.parse_multimodal_string`); the judge model must implement `supports_multimodal() -> True`; both metrics raise unless **`actual_output` contains at least one image** (an image only in `input` is rejected upstream); `ImageCoherenceMetric`/`ImageHelpfulnessMetric` accept `model`, `threshold`, `async_mode`, `strict_mode`, `verbose_mode`, `max_context_size` — no `include_reason`.
- Every `MLLMImage` created for a score call auto-registers in the global registry and is never evicted by DeepEval; the scorer must release its registry entries in a `try/finally` or the worker leaks base64 across rows.
- The frontend authenticates with a Bearer token from localStorage, so a bare `<img src="/api/...">` receives `401`; report images must be fetched as authorized blobs and rendered through object URLs.
- One new Alembic revision `0004`; a single head must remain.
- Use no new dependency. Tests mock upstream scorers and provider clients; no live paid model calls and no live network fetches run in CI.
- Missing image blocks are a row incompatibility, never an automatic score of zero.
- Preserve atomic claim, resumable persisted progress, attempt-guarded terminal writes, cancellation, and no automatic retry of paid judge calls.
- Provider secrets and asset bytes never enter artifacts, definition snapshots, API responses (beyond the authorized asset endpoint), or exports.

---

### Task 1: Immutable image assets with SSRF-guarded fetching

**Files:**

- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0004_evaluation_assets.py`
- Create: `backend/app/assets.py`
- Create: `backend/app/routers/assets.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_models.py`
- Create: `backend/tests/test_assets.py`

**Interfaces:**

- Produces: `EvaluationAsset(id, workspace_id, mime_type, byte_size, source_url, storage_path, created_at)`.
- Produces: `assets.ALLOWED_IMAGE_MIME_TYPES`, `assets.MAX_IMAGE_BYTES`, `assets.asset_storage_path(workspace_id, asset_id) -> str`.
- Produces: `assets.fetch_remote_image(url: str) -> tuple[bytes, str]` (bytes, mime) with SSRF/size/redirect/timeout guards.
- Produces: `assets.store_image_asset(db, workspace_id, data: bytes, mime_type: str, source_url: str | None) -> EvaluationAsset`.
- Produces: `POST /api/workspaces/{workspace_id}/assets/images` (multipart upload → `201 {asset_id, mime_type, byte_size}`) and `GET /api/workspaces/{workspace_id}/assets/{asset_id}` (streams bytes with the stored MIME type).

- [ ] **Step 1: Write RED model and asset tests**

In `backend/tests/test_models.py`: an `EvaluationAsset` persists and is workspace-scoped; `storage_path` is unique.

In `backend/tests/test_assets.py`:

```python
def test_upload_rejects_disallowed_mime_and_oversize(client, workspace, auth_headers):
    url = f"/api/workspaces/{workspace.id}/assets/images"
    bad = client.post(url, files={"file": ("a.txt", b"hello", "text/plain")}, headers=auth_headers)
    assert bad.status_code == 422
    big = client.post(
        url,
        files={"file": ("a.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
        headers=auth_headers,
    )
    assert big.status_code == 413


def test_upload_and_serve_round_trip(client, workspace, auth_headers, monkeypatch):
    stored = {}
    monkeypatch.setattr(storage, "put_object", lambda key, data: stored.setdefault(key, data))
    monkeypatch.setattr(storage, "get_object", lambda key: stored[key])
    url = f"/api/workspaces/{workspace.id}/assets/images"
    created = client.post(url, files={"file": ("a.png", b"\x89PNG bytes", "image/png")}, headers=auth_headers)
    assert created.status_code == 201
    asset_id = created.json()["asset_id"]
    served = client.get(f"/api/workspaces/{workspace.id}/assets/{asset_id}", headers=auth_headers)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == b"\x89PNG bytes"


def test_serve_is_workspace_scoped(client, workspace, other_workspace, auth_headers, other_auth_headers, monkeypatch):
    stored = {}
    monkeypatch.setattr(storage, "put_object", lambda key, data: stored.setdefault(key, data))
    monkeypatch.setattr(storage, "get_object", lambda key: stored[key])
    created = client.post(
        f"/api/workspaces/{workspace.id}/assets/images",
        files={"file": ("a.png", b"\x89PNG bytes", "image/png")},
        headers=auth_headers,
    )
    asset_id = created.json()["asset_id"]
    foreign = client.get(
        f"/api/workspaces/{other_workspace.id}/assets/{asset_id}",
        headers=other_auth_headers,
    )
    assert foreign.status_code == 404


def test_upload_cleans_up_storage_when_commit_fails(client, workspace, auth_headers, monkeypatch):
    stored, deleted = {}, []
    monkeypatch.setattr(storage, "put_object", lambda key, data: stored.setdefault(key, data))
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(
        "app.routers.assets.Session.commit",
        lambda self: (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    response = client.post(
        f"/api/workspaces/{workspace.id}/assets/images",
        files={"file": ("a.png", b"\x89PNG bytes", "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 500
    assert deleted == list(stored)


class _FakeStreamResponse:
    def __init__(self, status_code=200, headers=None, chunks=(b"\x89PNG",), location=None):
        self.status_code = status_code
        self.headers = dict(headers or {"content-type": "image/png"})
        if location:
            self.headers["location"] = location
        self._chunks = chunks
        self.is_redirect = 300 <= status_code < 400

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def iter_bytes(self):
        yield from self._chunks


def _patch_stream(monkeypatch, responses):
    queue = list(responses)
    monkeypatch.setattr(
        "app.assets.httpx.Client.stream",
        lambda self, method, url: queue.pop(0),
    )


def test_fetch_remote_image_blocks_private_targets(monkeypatch):
    from app.assets import fetch_remote_image

    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="private or non-public"):
        fetch_remote_image("https://internal.example/img.png")


def test_fetch_remote_image_validates_every_redirect_hop(monkeypatch):
    from app.assets import fetch_remote_image

    checked = []
    monkeypatch.setattr(
        "app.assets._validated_https_target",
        lambda url: checked.append(url),
    )
    _patch_stream(monkeypatch, [
        _FakeStreamResponse(status_code=302, location="https://cdn.example/img.png"),
        _FakeStreamResponse(),
    ])
    data, mime = fetch_remote_image("https://origin.example/img.png")
    assert checked == [
        "https://origin.example/img.png",
        "https://cdn.example/img.png",
    ]
    assert mime == "image/png"


def test_fetch_remote_image_rejects_http_downgrade_redirect(monkeypatch):
    from app.assets import fetch_remote_image

    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    _patch_stream(monkeypatch, [
        _FakeStreamResponse(status_code=302, location="http://origin.example/img.png"),
    ])
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_remote_image("https://origin.example/img.png")


def test_fetch_remote_image_enforces_mime_size_and_redirect_limit(monkeypatch):
    from app.assets import MAX_IMAGE_BYTES, fetch_remote_image

    monkeypatch.setattr("app.assets._validated_https_target", lambda url: None)
    _patch_stream(monkeypatch, [_FakeStreamResponse(headers={"content-type": "text/html"})])
    with pytest.raises(ValueError, match="not an allowed image type"):
        fetch_remote_image("https://origin.example/img.png")

    _patch_stream(monkeypatch, [
        _FakeStreamResponse(chunks=(b"x" * (MAX_IMAGE_BYTES // 2 + 1),) * 2),
    ])
    with pytest.raises(ValueError, match="5 MiB limit"):
        fetch_remote_image("https://origin.example/img.png")

    _patch_stream(monkeypatch, [
        _FakeStreamResponse(status_code=302, location="https://origin.example/next")
    ] * 4)
    with pytest.raises(ValueError, match="redirect limit"):
        fetch_remote_image("https://origin.example/img.png")
```

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_models.py tests/test_assets.py`

Expected: missing model, module, and routes.

- [ ] **Step 3: Add the model and migration**

In `backend/app/models.py` after `EvaluationArtifact`:

```python
class EvaluationAsset(Base):
    __tablename__ = "evaluation_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1024), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

`backend/alembic/versions/0004_evaluation_assets.py` (`revision "0004"`, `down_revision "0003"`) creates the table with the same columns, the unique `storage_path` constraint, and the workspace index; downgrade drops the table.

- [ ] **Step 4: Implement guarded fetching and storage**

`backend/app/assets.py`:

```python
import uuid

import httpx

from app import storage
from app.endpoints import validate_url, _validate_destination
from app.models import EvaluationAsset

ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 3


def asset_storage_path(workspace_id: str, asset_id: str) -> str:
    return f"image-assets/{workspace_id}/{asset_id}"


def _normalized_mime(content_type: str | None) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"'{mime or 'unknown'}' is not an allowed image type")
    return mime


def _validated_https_target(url: str):
    """Validate scheme, credentials, and resolved addresses BEFORE any request."""
    parsed = validate_url(url)
    if parsed.scheme != "https":
        raise ValueError("Remote images must use HTTPS")
    _validate_destination(parsed)
    return parsed


def fetch_remote_image(url: str) -> tuple[bytes, str]:
    # Follow redirects manually: httpx's follow_redirects=True would fetch
    # every intermediate hop before we could validate it, and would also
    # accept an HTTPS -> HTTP downgrade. Each hop is validated first.
    current = url
    try:
        with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                _validated_https_target(current)
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Remote image redirect has no location")
                        current = str(httpx.URL(current).join(location))
                        continue
                    response.raise_for_status()
                    mime = _normalized_mime(response.headers.get("content-type"))
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            raise ValueError("Remote image exceeds the 5 MiB limit")
                    if not data:
                        raise ValueError("Remote image is empty")
                    return bytes(data), mime
            raise ValueError("Remote image exceeded the redirect limit")
    except httpx.HTTPError as exc:
        raise ValueError(f"Remote image fetch failed: {exc}") from exc


def store_image_asset(
    db,
    workspace_id: str,
    data: bytes,
    mime_type: str,
    source_url: str | None = None,
) -> EvaluationAsset:
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"'{mime_type}' is not an allowed image type")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 5 MiB limit")
    asset = EvaluationAsset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        mime_type=mime_type,
        byte_size=len(data),
        source_url=source_url,
        storage_path="",
    )
    asset.storage_path = asset_storage_path(workspace_id, asset.id)
    storage.put_object(asset.storage_path, data)
    db.add(asset)
    return asset
```

Note: `_validate_destination` and `validate_url` are the existing SSRF guards in `backend/app/endpoints.py` — reuse, do not duplicate. Re-validating `response.url` closes the redirect-to-private-host hole; `max_redirects=3` bounds the chain.

- [ ] **Step 5: Implement the router**

`backend/app/routers/assets.py`:

```python
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app import storage
from app.assets import ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_BYTES, store_image_asset
from app.deps import get_db, get_workspace
from app.models import EvaluationAsset, Workspace

router = APIRouter(prefix="/api/workspaces/{workspace_id}/assets", tags=["assets"])


@router.post("/images", status_code=201)
def upload_image(
    file: Annotated[UploadFile, File()],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    if (file.content_type or "").lower() not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported image type")
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 5 MiB limit")
    if not data:
        raise HTTPException(status_code=422, detail="Image file is empty")
    asset = store_image_asset(db, ws.id, data, file.content_type.lower())
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete_object(asset.storage_path)
        except Exception:
            logger.exception("Failed to clean up asset upload %s", asset.storage_path)
        raise
    return {
        "asset_id": asset.id,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
    }


@router.get("/{asset_id}")
def serve_image(
    asset_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    asset = (
        db.query(EvaluationAsset)
        .filter_by(id=asset_id, workspace_id=ws.id)
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return Response(content=storage.get_object(asset.storage_path), media_type=asset.mime_type)
```

Register in `backend/app/main.py`: `app.include_router(assets.router)`.

- [ ] **Step 6: Run GREEN, verify migration, and commit**

```bash
cd backend
.venv/bin/pytest -q -p no:deepeval tests/test_models.py tests/test_assets.py
.venv/bin/alembic heads
```

Expected: tests pass; exactly one `0004` head.

```bash
git add backend/app/models.py backend/alembic/versions/0004_evaluation_assets.py backend/app/assets.py backend/app/routers/assets.py backend/app/main.py backend/app/config.py backend/tests/test_models.py backend/tests/test_assets.py
git commit -m "feat(assets): add guarded image assets"
```

---

### Task 2: Normalize multimodal samples

**Files:**

- Modify: `backend/app/evals/samples.py`
- Modify: `backend/app/evals/normalizers.py`
- Modify: `backend/tests/test_samples.py`
- Modify: `backend/tests/test_agent_normalizers.py`

**Interfaces:**

- Produces: `ImageBlock(asset_id | url, mime_type, data_base64 excluded-from-dump)` with an exactly-one-source validator.
- Produces: `normalize_sample("multimodal", source, schema_map, ...) -> MultimodalSample` (plain strings coerce to one `TextBlock`).
- Produces: `multimodal_input_preview(sample) -> str` and `multimodal_actual_preview(sample) -> str` (concatenated text blocks, `""` when none).

- [ ] **Step 1: Write RED sample tests**

In `backend/tests/test_samples.py`:

```python
def test_image_block_requires_exactly_one_source():
    ImageBlock.model_validate({"type": "image", "asset_id": "a1"})
    ImageBlock.model_validate({"type": "image", "url": "https://example.com/x.png"})
    with pytest.raises(ValidationError):
        ImageBlock.model_validate({"type": "image"})
    with pytest.raises(ValidationError):
        ImageBlock.model_validate({"type": "image", "asset_id": "a1", "url": "https://x/y.png"})


def test_image_block_dump_excludes_hydrated_bytes():
    block = ImageBlock(asset_id="a1", data_base64="aGVsbG8=", mime_type="image/png")
    dumped = block.model_dump(mode="json")
    assert "data_base64" not in dumped
    assert dumped["asset_id"] == "a1"


def test_multimodal_previews_concatenate_text_blocks():
    sample = MultimodalSample.model_validate({
        "kind": "multimodal",
        "input": [{"type": "text", "text": "Describe the chart"}],
        "actual_output": [
            {"type": "text", "text": "The chart shows"},
            {"type": "image", "asset_id": "a1"},
            {"type": "text", "text": "rising revenue."},
        ],
    })
    assert multimodal_input_preview(sample) == "Describe the chart"
    assert multimodal_actual_preview(sample) == "The chart shows rising revenue."
```

- [ ] **Step 2: Write RED normalizer tests**

In `backend/tests/test_agent_normalizers.py`:

```python
def test_normalize_multimodal_from_csv_json_and_plain_text():
    sample = normalize_sample(
        "multimodal",
        {
            "q": "Describe the chart",
            "a": '[{"type":"text","text":"It rises"},{"type":"image","asset_id":"a1"}]',
        },
        {"input": "q", "actual_output": "a"},
    )
    assert sample.kind == "multimodal"
    assert sample.input[0].text == "Describe the chart"
    assert sample.actual_output[1].asset_id == "a1"


def test_normalize_multimodal_requires_both_fields_and_names_bad_json():
    with pytest.raises(ValueError, match="Mapped input value is missing"):
        normalize_sample("multimodal", {"a": "x"}, {"actual_output": "a"})
    with pytest.raises(ValueError, match="Invalid actual_output in column 'a'"):
        normalize_sample(
            "multimodal", {"q": "t", "a": "[not json"}, {"input": "q", "actual_output": "a"}
        )
```

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_samples.py tests/test_agent_normalizers.py`

- [ ] **Step 4: Evolve `ImageBlock` and add previews**

In `backend/app/evals/samples.py`, replace `ImageBlock` and add previews after `MultimodalSample`:

```python
class ImageBlock(StrictModel):
    type: Literal["image"] = "image"
    asset_id: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    mime_type: str | None = None
    data_base64: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.asset_id) == bool(self.url):
            raise ValueError("Image blocks need exactly one of asset_id or url")
        return self


def multimodal_input_preview(sample: "MultimodalSample") -> str:
    return " ".join(
        block.text for block in sample.input if block.type == "text"
    ).strip()


def multimodal_actual_preview(sample: "MultimodalSample") -> str:
    return " ".join(
        block.text for block in sample.actual_output if block.type == "text"
    ).strip()
```

(`model_validator` is already imported for `AgentTraceSample`; add it to the import list if not.) `MultimodalSample` itself is unchanged: `input`/`actual_output` are `list[ContentBlock]` with `min_length=1`.

- [ ] **Step 5: Add the multimodal normalizer branch**

In `backend/app/evals/normalizers.py`, after the shared `input`/`actual_output` presence checks (multimodal needs both, so it stays **below** them, unlike conversation):

```python
def _content_blocks(value: Any, field: str, column: str) -> Any:
    decoded = _structured_value(value, field, column)
    if isinstance(decoded, str):
        return [{"type": "text", "text": decoded}]
    return decoded
```

and inside `normalize_sample`:

```python
    if sample_kind == "multimodal":
        return MultimodalSample(
            input=_content_blocks(
                input_value, "input", schema_map.get("input", "input")
            ),
            actual_output=_content_blocks(
                actual_output, "actual_output", schema_map.get("actual_output", "actual_output")
            ),
            metadata={} if metadata is _MISSING or metadata is None else metadata,
            tags=[] if tags is _MISSING or tags is None else tags,
            source=_sample_source(source_ref),
        )
```

where `metadata`/`tags` are read with `_mapped_value` exactly as the agent branch does. Note `_content_blocks` must not `str(...)`-coerce its input first — move the shared `str(input_value)` coercion into the single-turn/agent branches so multimodal receives the raw value.

- [ ] **Step 6: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_samples.py tests/test_agent_normalizers.py`

```bash
git add backend/app/evals/samples.py backend/app/evals/normalizers.py backend/tests/test_samples.py backend/tests/test_agent_normalizers.py
git commit -m "feat(evals): normalize multimodal samples"
```

---

### Task 3: Teach the provider judge to see images

**Files:**

- Modify: `backend/app/evals/judges.py`
- Modify: `backend/tests/test_openai_compatible.py`
- Create: `backend/tests/test_multimodal_judge.py`

**Interfaces:**

- Produces: `ProviderLLM.supports_multimodal() -> True`.
- Produces: marker-aware message construction — a prompt containing `[DEEPEVAL:IMAGE:<id>]` becomes OpenAI `image_url` parts / Anthropic `image` blocks using the registered `MLLMImage`'s `dataBase64` + `mimeType`.
- Consumes: DeepEval's `MLLMImage.parse_multimodal_string` (pinned 4.1.0; the Task 4 upstream contract test locks it).

- [ ] **Step 1: Write RED judge tests**

`backend/tests/test_multimodal_judge.py` (mock the OpenAI/Anthropic clients the way `test_openai_compatible.py` does — capture the `messages` argument):

```python
def _marker_prompt():
    from deepeval.test_case import MLLMImage

    image = MLLMImage(dataBase64="aGVsbG8=", mimeType="image/png")
    return f"Rate this. {image}", image


class _FakeMessage:
    content = '{"score": 1, "reasoning": "ok"}'


class _FakeChoice:
    message = _FakeMessage()
    finish_reason = "stop"


class _FakeCompletion:
    choices = [_FakeChoice()]
    usage = None


def _openai_judge(monkeypatch, captured):
    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeCompletion()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("app.evals.judges._client", lambda judge: FakeClient())
    return JudgeConfig(provider="openai_compatible", model="local-vlm", api_key="k", base_url="https://gw.test")


def test_openai_judge_builds_image_url_parts(monkeypatch):
    prompt, image = _marker_prompt()
    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured)
    deepeval_llm(judge).generate(prompt)
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Rate this. "}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="


def test_anthropic_judge_builds_image_blocks(monkeypatch):
    prompt, image = _marker_prompt()
    captured: dict = {}

    class FakeBlock:
        text = '{"score": 1, "reasoning": "ok"}'

    class FakeResponse:
        content = [FakeBlock()]
        stop_reason = "end_turn"
        usage = None

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr("app.evals.judges._client", lambda judge: FakeClient())
    judge = JudgeConfig(provider="anthropic", model="claude-3-opus-20240229", api_key="k")
    deepeval_llm(judge).generate(prompt)
    content = captured["messages"][0]["content"]
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="},
    }


def test_plain_prompt_stays_string(monkeypatch):
    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured)
    deepeval_llm(judge).generate("plain text prompt")
    assert captured["messages"][0]["content"] == "plain text prompt"


def test_unhydrated_image_marker_raises(monkeypatch):
    from deepeval.test_case import MLLMImage

    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured)
    image = MLLMImage(url="https://example.com/x.png")  # no dataBase64
    with pytest.raises(ValueError, match="hydrated"):
        deepeval_llm(judge).generate(f"Rate this. {image}")


def test_provider_llm_reports_multimodal_support(monkeypatch):
    judge = _openai_judge(monkeypatch, {})
    assert deepeval_llm(judge).supports_multimodal() is True
```

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_multimodal_judge.py tests/test_openai_compatible.py`

- [ ] **Step 3: Implement marker-aware content building**

In `backend/app/evals/judges.py`, add a shared helper above `deepeval_llm`:

```python
def _split_marker_prompt(prompt: str):
    """Return None for plain prompts, else the parsed [str | MLLMImage] segments."""
    from deepeval.test_case import MLLMImage

    if "[DEEPEVAL:" not in prompt:
        return None
    # Probed on DeepEval 4.1.0: the parser lives on MLLMImage, and there is
    # no LLMTestCase.parse_multimodal_string. The Task 4 contract test pins this.
    segments = MLLMImage.parse_multimodal_string(prompt)
    if all(isinstance(segment, str) for segment in segments):
        return None
    return segments


def _openai_content(segments) -> list[dict]:
    parts = []
    for segment in segments:
        if isinstance(segment, str):
            if segment:
                parts.append({"type": "text", "text": segment})
            continue
        if not segment.dataBase64 or not segment.mimeType:
            raise ValueError("Image was not hydrated before the judge call")
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{segment.mimeType};base64,{segment.dataBase64}"
                },
            }
        )
    return parts


def _anthropic_content(segments) -> list[dict]:
    parts = []
    for segment in segments:
        if isinstance(segment, str):
            if segment:
                parts.append({"type": "text", "text": segment})
            continue
        if not segment.dataBase64 or not segment.mimeType:
            raise ValueError("Image was not hydrated before the judge call")
        parts.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": segment.mimeType,
                    "data": segment.dataBase64,
                },
            }
        )
    return parts
```


Inside `ProviderLLM`:

- add

```python
        def supports_multimodal(self):
            return True
```

- in each `generate` path (OpenAI structured, OpenAI plain, OpenAI-compatible JSON, Anthropic), compute `segments = _split_marker_prompt(prompt)` and, when segments exist, replace the message content: `{"role": "user", "content": _openai_content(segments)}` for OpenAI-family paths and `{"role": "user", "content": _anthropic_content(segments)}` for the Anthropic path. Plain prompts keep today's string content byte-for-byte.

`DeterministicLLM` is untouched — deterministic metrics never see images.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_multimodal_judge.py tests/test_openai_compatible.py`

```bash
git add backend/app/evals/judges.py backend/tests/test_multimodal_judge.py backend/tests/test_openai_compatible.py
git commit -m "feat(judges): render image markers for vision judges"
```

---

### Task 4: Register the two image adapters and remaining presets

**Files:**

- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/deepeval.py`
- Modify: `backend/app/evals/registry.py`
- Modify: `backend/app/evals/metric_info.py`
- Modify: `backend/app/evals/presets.py`
- Modify: `backend/tests/test_metric_contract.py`
- Modify: `backend/tests/test_metric_adapters.py`
- Modify: `backend/tests/test_metric_upstream_contract.py`
- Modify: `backend/tests/test_metrics.py`

**Interfaces:**

- Consumes: `ImageBlock.data_base64`/`mime_type` hydrated by Task 6's worker, `multimodal_input_preview`/`multimodal_actual_preview` from Task 2.
- Produces: `ImageMetricConfig(threshold, strict_mode, max_context_size)`.
- Produces: `score_metric` handling `MultimodalSample` via marker strings; registry with exactly 25 keys; presets `conversational`, `mcp`, `multimodal`.

- [ ] **Step 1: Write RED contract tests**

In `backend/tests/test_metric_contract.py`:

```python
PHASE_5_KEYS = PHASE_4_KEYS | {"deepeval.image_coherence", "deepeval.image_helpfulness"}


def test_multimodal_adapter_metadata():
    for key in ("deepeval.image_coherence", "deepeval.image_helpfulness"):
        adapter = METRICS[key]
        assert adapter.category == "general"
        assert adapter.family == "multimodal"
        assert adapter.sample_kind == "multimodal"
        assert adapter.resources({}) == frozenset({"judge", "multimodal"})
        assert adapter.requirements({}) == frozenset({"input", "actual_output"})
        assert adapter.info["score_direction"] == "higher_is_better"
```

In `backend/tests/test_metrics.py` (presets):

```python
def test_phase_5_presets_cover_remaining_categories():
    ids = {preset["id"] for preset in PRESETS.values()}
    assert {"conversational", "mcp", "multimodal"} <= ids
    assert PRESETS["multimodal"]["metric_keys"] == [
        "deepeval.image_coherence",
        "deepeval.image_helpfulness",
    ]
    assert PRESETS["conversational"]["metric_keys"] == [
        "deepeval.conversation_completeness",
        "deepeval.turn_relevancy",
        "deepeval.role_adherence",
    ]
    assert PRESETS["mcp"]["metric_keys"] == [
        "deepeval.mcp_task_completion",
        "deepeval.mcp_use",
    ]
```

- [ ] **Step 2: Write RED adapter conversion tests**

In `backend/tests/test_metric_adapters.py` (mock constructor like the other DeepEval tests; capture init kwargs and the measured test case):

```python
def _multimodal_sample():
    return MultimodalSample.model_validate({
        "kind": "multimodal",
        "input": [{"type": "text", "text": "Describe the chart"}],
        "actual_output": [
            {"type": "text", "text": "Revenue"},
            {"type": "image", "asset_id": "a1"},
        ],
    })


def _hydrated(sample):
    for block in sample.actual_output + sample.input:
        if block.type == "image":
            block.data_base64 = "aGVsbG8="
            block.mime_type = "image/png"
    return sample


def _capture_image_metric(monkeypatch, captured):
    class FakeMetric:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs
            self.reason = "ok"

        def measure(self, test_case, **kwargs):
            captured["measure_args"] = (test_case,)
            return 0.9

        def is_successful(self):
            return True

    import deepeval.metrics

    monkeypatch.setattr(deepeval.metrics, "ImageCoherenceMetric", FakeMetric)
    monkeypatch.setattr(deepeval.metrics, "ImageHelpfulnessMetric", FakeMetric)


def test_image_metric_receives_marker_test_case(monkeypatch):
    captured: dict = {}
    _capture_image_metric(monkeypatch, captured)
    score_metric("image_coherence", _hydrated(_multimodal_sample()), judge, {"max_context_size": 500})
    test_case = captured["measure_args"][0]
    assert test_case.multimodal is True
    assert "[DEEPEVAL:IMAGE:" in test_case.actual_output
    assert captured["init_kwargs"]["max_context_size"] == 500
    assert "include_reason" not in captured["init_kwargs"]


def test_image_metric_without_actual_output_image_fails_row():
    # Upstream (probed on 4.1.0) rejects test cases whose actual_output has no
    # image — an image only in the input is not enough.
    input_only_image = MultimodalSample.model_validate({
        "kind": "multimodal",
        "input": [
            {"type": "text", "text": "Describe"},
            {"type": "image", "asset_id": "a1"},
        ],
        "actual_output": [{"type": "text", "text": "a plain text answer"}],
    })
    for block in input_only_image.input:
        if block.type == "image":
            block.data_base64 = "aGVsbG8="
            block.mime_type = "image/png"
    with pytest.raises(ValueError, match="image block in actual_output"):
        score_metric("image_coherence", input_only_image, judge, {})


def test_image_metric_with_unhydrated_block_fails_row():
    with pytest.raises(ValueError, match="hydrated"):
        score_metric("image_helpfulness", _multimodal_sample(), judge, {})


def test_image_metrics_require_judge():
    with pytest.raises(ValueError, match="requires a judge"):
        score_metric("image_coherence", _hydrated(_multimodal_sample()), None, {})


def test_score_metric_releases_marker_registry_entries(monkeypatch):
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    captured: dict = {}
    _capture_image_metric(monkeypatch, captured)
    before = len(_MLLM_IMAGE_REGISTRY)
    score_metric("image_coherence", _hydrated(_multimodal_sample()), judge, {})
    assert len(_MLLM_IMAGE_REGISTRY) == before


def test_score_metric_releases_registry_even_when_measure_raises(monkeypatch):
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    class ExplodingMetric:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case, **kwargs):
            raise RuntimeError("judge failed")

    import deepeval.metrics

    monkeypatch.setattr(deepeval.metrics, "ImageCoherenceMetric", ExplodingMetric)
    before = len(_MLLM_IMAGE_REGISTRY)
    with pytest.raises(RuntimeError):
        score_metric("image_coherence", _hydrated(_multimodal_sample()), judge, {})
    assert len(_MLLM_IMAGE_REGISTRY) == before
```

- [ ] **Step 3: Extend the upstream contract lock**

In `backend/tests/test_metric_upstream_contract.py`:

```python
def test_deepeval_multimodal_contract_is_available():
    import inspect

    from deepeval.metrics import ImageCoherenceMetric, ImageHelpfulnessMetric
    from deepeval.test_case import LLMTestCase, MLLMImage
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    for metric_class in (ImageCoherenceMetric, ImageHelpfulnessMetric):
        params = inspect.signature(metric_class.__init__).parameters
        assert "max_context_size" in params
        assert "include_reason" not in params
    image = MLLMImage(dataBase64="aGVsbG8=", mimeType="image/png")
    try:
        assert str(image).startswith("[DEEPEVAL:IMAGE:")
        assert _MLLM_IMAGE_REGISTRY[image._id] is image
        case = LLMTestCase(input="i", actual_output=f"look {image}")
        assert case.multimodal is True
        segments = MLLMImage.parse_multimodal_string(f"before {image} after")
        assert [type(segment).__name__ for segment in segments] == [
            "str",
            "MLLMImage",
            "str",
        ]
        assert segments[1] is image
    finally:
        _MLLM_IMAGE_REGISTRY.pop(image._id, None)
```

- [ ] **Step 4: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_metric_contract.py tests/test_metric_adapters.py tests/test_metric_upstream_contract.py tests/test_metrics.py`

- [ ] **Step 5: Implement config, converter, registry, presets, info**

`backend/app/evals/base.py`:

```python
class ImageMetricConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    strict_mode: bool = False
    max_context_size: int | None = Field(
        default=None,
        ge=50,
        le=10_000,
        description="Characters of surrounding text shown to the judge per image.",
    )
```

`backend/app/evals/deepeval.py`:

```python
_IMAGE_METRICS = {"image_coherence", "image_helpfulness"}


def _marker_text(blocks, created_ids: list[str]) -> str:
    from deepeval.test_case import MLLMImage

    parts = []
    for block in blocks:
        if block.type == "text":
            parts.append(block.text)
            continue
        if not block.data_base64 or not block.mime_type:
            raise ValueError("Image block was not hydrated before scoring")
        image = MLLMImage(dataBase64=block.data_base64, mimeType=block.mime_type)
        created_ids.append(image._id)
        parts.append(str(image))
    return " ".join(parts)


def _multimodal_test_case(sample: MultimodalSample) -> tuple[Any, list[str]]:
    from deepeval.test_case import LLMTestCase

    if not any(block.type == "image" for block in sample.actual_output):
        # Upstream requires at least one image in actual_output (probed 4.1.0).
        raise ValueError(
            "Multimodal sample needs at least one image block in actual_output"
        )
    created_ids: list[str] = []
    try:
        test_case = LLMTestCase(
            input=_marker_text(sample.input, created_ids),
            actual_output=_marker_text(sample.actual_output, created_ids),
            metadata=sample.metadata,
            tags=sample.tags,
        )
    except Exception:
        _release_marker_images(created_ids)
        raise
    return test_case, created_ids


def _release_marker_images(image_ids: list[str]) -> None:
    # DeepEval's module-level registry holds strong references forever;
    # without this the worker accumulates every scored image's base64.
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    for image_id in image_ids:
        _MLLM_IMAGE_REGISTRY.pop(image_id, None)
```

`score_metric` wraps multimodal scoring in `try/finally`:

```python
def score_metric(name, row, judge, config=None):
    metric = _make_metric(name, judge, config)
    created_image_ids: list[str] = []
    if isinstance(row, MultimodalSample):
        test_case, created_image_ids = _multimodal_test_case(row)
    else:
        test_case = _test_case(row, name)
    try:
        value = float(
            metric.measure(
                test_case,
                _show_indicator=False,
                _log_metric_to_confident=False,
            )
        )
        usage, estimated_cost = usage_snapshot(getattr(metric, "model", None))
        return MetricScore(
            metric=f"deepeval.{name}",
            score=value,
            reason=getattr(metric, "reason", None),
            passed=bool(metric.is_successful()) if hasattr(metric, "is_successful") else None,
            usage=usage,
            estimated_cost=estimated_cost,
        )
    finally:
        _release_marker_images(created_image_ids)
```

(keeping the existing non-multimodal behavior byte-for-byte — the refactor only threads `created_image_ids` and the `finally`). The `MultimodalSample` branch is removed from `_test_case` since `score_metric` now dispatches it explicitly.

`_make_metric` gains (imports added to the existing block; note **no** `include_reason`):

```python
        "image_coherence": lambda: ImageCoherenceMetric(
            max_context_size=options.get("max_context_size"),
            threshold=options.get("threshold", 0.5),
            strict_mode=options.get("strict_mode", False),
            model=judge_model,
            async_mode=False,
        ),
        "image_helpfulness": lambda: ImageHelpfulnessMetric(
            max_context_size=options.get("max_context_size"),
            threshold=options.get("threshold", 0.5),
            strict_mode=options.get("strict_mode", False),
            model=judge_model,
            async_mode=False,
        ),
```

`backend/app/evals/registry.py` — two entries:

```python
        _adapter(
            "deepeval.image_coherence",
            "Image Coherence",
            "Whether each image fits the surrounding response text.",
            "general",
            "multimodal",
            {"input", "actual_output"},
            {"judge", "multimodal"},
            config_model=ImageMetricConfig,
            sample_kind="multimodal",
        ),
        _adapter(
            "deepeval.image_helpfulness",
            "Image Helpfulness",
            "Whether images help answer the user's request.",
            "general",
            "multimodal",
            {"input", "actual_output"},
            {"judge", "multimodal"},
            config_model=ImageMetricConfig,
            sample_kind="multimodal",
        ),
```

`backend/app/evals/presets.py` — three additions (category/mode hints: `conversational`→`general`/`static`, `mcp`→`agentic`/`static`, `multimodal`→`general`/`static`), metric keys exactly as the Step 1 test asserts. `backend/app/evals/metric_info.py` — two complete entries, both `higher_is_better`, required data "input and actual output content blocks with at least one image".

- [ ] **Step 6: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_metric_contract.py tests/test_metric_adapters.py tests/test_metric_upstream_contract.py tests/test_metrics.py`

```bash
git add backend/app/evals backend/tests/test_metric_contract.py backend/tests/test_metric_adapters.py backend/tests/test_metric_upstream_contract.py backend/tests/test_metrics.py
git commit -m "feat(metrics): add image metrics and remaining presets"
```

---

### Task 5: Gate multimodal runs and accept multimodal ingestion

**Files:**

- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/routers/ingestions.py`
- Modify: `backend/tests/test_runs.py`
- Modify: `backend/tests/test_ingestions.py`

**Interfaces:**

- Produces: `POST /api/workspaces/{workspace_id}/ingestions/multimodal` (reusing `_ingest_sample` with `sample_kind="multimodal"`).
- Produces: endpoint-mode `422` for multimodal selections: `"Multimodal runs support static datasets and ingestion"`.

- [ ] **Step 1: Write RED run tests**

In `backend/tests/test_runs.py`:

- static run with `deepeval.image_coherence` on a dataset mapping `input` + `actual_output` and a judge returns `201`;
- the same selection with `mode="endpoint"` and a valid `endpoint_config` returns `422` `"Multimodal runs support static datasets and ingestion"`;
- `judge: null` with an image metric returns `422` (judge required);
- mixing `deepeval.image_coherence` with `deepeval.answer_relevancy` returns `422` (different sample kinds).

- [ ] **Step 2: Write RED ingestion tests**

In `backend/tests/test_ingestions.py`, mirror the conversation cases for `/ingestions/multimodal`:

```python
def _multimodal_body(judge_id):
    return {
        "name": "Chart answer eval",
        "sample": {
            "kind": "multimodal",
            "input": [{"type": "text", "text": "Describe the chart"}],
            "actual_output": [
                {"type": "text", "text": "Revenue rises"},
                {"type": "image", "asset_id": "a1"},
            ],
        },
        "metrics": [{"key": "deepeval.image_coherence"}],
        "judge": {"connection_id": judge_id, "model": "gpt-4.1-mini"},
    }
```

first `202` / replay `200` / changed `409`; invalid sample (`input: []`) `422` with pointer `["body", "sample", "input"]`; selecting `deepeval.turn_relevancy` returns `422` "Multimodal ingestion only accepts multimodal metrics"; artifact `sample_kind == "multimodal"`; oversize body `413`.

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_runs.py tests/test_ingestions.py`

- [ ] **Step 4: Implement the gates**

In `backend/app/routers/runs.py` `create_run`, right after `_validate_metric_selection` returns:

```python
    if sample_kind == "multimodal" and body.mode == "endpoint":
        raise HTTPException(
            status_code=422,
            detail="Multimodal runs support static datasets and ingestion",
        )
```

(The existing `sample_requirements` map already demands `input` + `actual_output` for multimodal; the `sample_kind != "conversation"` input/actual checks also apply to multimodal static runs, which is correct.)

In `backend/app/routers/ingestions.py`:

```python
_KIND_LABELS = {
    "agent_trace": "Agent trace",
    "conversation": "Conversation",
    "multimodal": "Multimodal",
}
_LIMITED_SUFFIXES = (
    "/ingestions/agent-traces",
    "/ingestions/conversations",
    "/ingestions/multimodal",
)


def _multimodal_or_422(raw: dict[str, Any]) -> MultimodalSample:
    return _validated_sample_or_422(raw, MultimodalSample)


@router.post("/multimodal", status_code=202)
def ingest_multimodal(
    body: IngestionIn,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return _ingest_sample(
        body=body,
        response=response,
        idempotency_key=idempotency_key,
        ws=ws,
        db=db,
        sample_kind="multimodal",
        validate_sample=_multimodal_or_422,
    )
```

widening `_ingest_sample`'s `sample_kind` literal to `Literal["agent_trace", "conversation", "multimodal"]` and importing `MultimodalSample`.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_runs.py tests/test_ingestions.py`

```bash
git add backend/app/routers/runs.py backend/app/routers/ingestions.py backend/tests/test_runs.py backend/tests/test_ingestions.py
git commit -m "feat(runs): gate and ingest multimodal samples"
```

---

### Task 6: Hydrate and score multimodal samples in the worker

**Files:**

- Modify: `backend/app/tasks.py`
- Create: `backend/tests/test_worker_multimodal.py`

**Interfaces:**

- Consumes: `assets.fetch_remote_image`, `assets.store_image_asset`, `asset_storage_path` from Task 1; `ImageBlock.data_base64` from Task 2.
- Produces: `_hydrate_image_blocks(db, workspace_id, sample, url_cache) -> None` — resolves `url` blocks into snapshot assets, loads bytes for every block, mutates blocks in place.
- Produces: `_sample_details`/`_write_result_sample`/`_stored_sample` multimodal branches persisting blocks with `asset_id` + `mime_type` only (never bytes, never raw remote URLs after snapshotting).

- [ ] **Step 1: Write RED worker tests**

`backend/tests/test_worker_multimodal.py` (fixtures mirror `test_worker_conversation.py`; storage and `score_metric` mocked):

- a static JSON dataset row with text + `asset_id` image reaches the scorer as `MultimodalSample` whose image blocks are hydrated (`data_base64` set from mocked storage, `mime_type` from the asset row);
- a row with a remote `url` image: `fetch_remote_image` is called once, a new `EvaluationAsset` row exists with `source_url` set, and the persisted `details.sample.actual_output` block now carries the snapshot `asset_id` and **no** `url`;
- the same URL appearing twice in one run fetches remotely once (in-run cache);
- a row whose asset id does not exist fails only that row with `"Image asset not found"`;
- `RunResult.input`/`actual` equal the text previews; `details.sample` stores `kind="multimodal"`, block lists, `metadata`, `tags`, `source`, `normalizer_revision`, and **no** `data_base64` anywhere;
- recovery via `_stored_sample(result, "multimodal")` rebuilds the sample and re-hydration fills bytes again without re-fetching remote URLs (blocks already reference asset ids);
- an ingestion-mode multimodal run loads the artifact JSON and scores it.

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_worker_multimodal.py`

- [ ] **Step 3: Implement hydration**

In `backend/app/tasks.py`:

```python
import base64

from app.assets import fetch_remote_image, store_image_asset
from app.models import EvaluationAsset


def _hydrate_image_blocks(
    db,
    workspace_id: str,
    sample,
    url_cache: dict[str, str],
) -> None:
    if not isinstance(sample, MultimodalSample):
        return
    for block in [*sample.input, *sample.actual_output]:
        if block.type != "image":
            continue
        if block.url and not block.asset_id:
            cached = url_cache.get(block.url)
            if cached is None:
                data, mime = fetch_remote_image(block.url)
                asset = store_image_asset(
                    db, workspace_id, data, mime, source_url=block.url
                )
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    try:
                        storage.delete_object(asset.storage_path)
                    except Exception:
                        logger.exception(
                            "Failed to clean up image snapshot %s",
                            asset.storage_path,
                        )
                    raise
                cached = asset.id
                url_cache[block.url] = cached
            block.asset_id = cached
            block.url = None
        asset_row = (
            db.query(EvaluationAsset)
            .filter_by(id=block.asset_id, workspace_id=workspace_id)
            .first()
        )
        if asset_row is None:
            raise ValueError("Image asset not found")
        block.data_base64 = base64.b64encode(
            storage.get_object(asset_row.storage_path)
        ).decode()
        block.mime_type = asset_row.mime_type
```

Mutating `block.url`/`block.asset_id` requires relaxing the exactly-one validator on assignment — `StrictModel` does not enable `validate_assignment`, so plain attribute writes are safe; add that as a comment only if the codebase convention demands one (it does not).

Call it in `evaluate_run` for the static/ingestion branch right after `normalize_sample(...)` succeeds and before the `RunResult` is created, and in `_stored_sample`-recovery scoring right after the stored sample is rebuilt:

```python
                            _hydrate_image_blocks(
                                db, run.workspace_id, row, url_cache
                            )
```

with `url_cache: dict[str, str] = {}` initialized once per `evaluate_run` invocation. Hydration failures raise inside the existing per-row `try`, so they fail only that row.

- [ ] **Step 4: Persist multimodal details**

`_sample_details` gains:

```python
    if isinstance(sample, MultimodalSample):
        return {
            "sample": {
                "kind": "multimodal",
                "input": [block.model_dump(mode="json") for block in sample.input],
                "actual_output": [
                    block.model_dump(mode="json") for block in sample.actual_output
                ],
                "metadata": sample.metadata,
                "tags": sample.tags,
                "source": (
                    sample.source.model_dump(mode="json") if sample.source else None
                ),
                "normalizer_revision": sample.normalizer_revision,
            }
        }
```

(`model_dump` excludes `data_base64` by field config — Task 2.) `_write_result_sample` gains:

```python
    if isinstance(sample, MultimodalSample):
        result.input = multimodal_input_preview(sample)
        result.actual = multimodal_actual_preview(sample)
        result.expected = None
        result.contexts = None
        result.details = _sample_details(sample)
        return
```

`_stored_sample` gains:

```python
    if sample_kind == "multimodal":
        return MultimodalSample.model_validate(
            {
                "kind": "multimodal",
                "input": sample.get("input"),
                "actual_output": sample.get("actual_output"),
                "metadata": sample.get("metadata", {}),
                "tags": sample.get("tags", []),
                "source": sample.get("source"),
                "normalizer_revision": sample.get("normalizer_revision", "1"),
            }
        )
```

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_worker_multimodal.py tests/test_worker.py tests/test_worker_conversation.py tests/test_worker_agentic.py tests/test_ingestions.py`

```bash
git add backend/app/tasks.py backend/tests/test_worker_multimodal.py
git commit -m "feat(worker): hydrate and score multimodal samples"
```

---

### Task 7: Multimodal UI, reports, and image rendering

**Files:**

- Modify: `frontend/lib/dataset-capabilities.ts`
- Modify: `frontend/components/RunWizard.tsx`
- Modify: `frontend/components/RunReport.tsx`
- Modify: `backend/app/reports.py`
- Modify: `backend/app/templates/report.html`
- Modify: `frontend/tests/datasets-page.test.tsx`
- Modify: `frontend/tests/run-wizard.test.tsx`
- Modify: `frontend/tests/run-report.test.tsx`
- Modify: `backend/tests/test_exports.py`

**Interfaces:**

- Produces: multimodal metrics counted/selectable when `input` + `actual_output` are mapped; endpoint mode hides/disables multimodal selections mirroring the backend `422`.
- Produces: `frontend/components/AuthImage.tsx` — fetches the asset with the Bearer token, renders an object URL, and revokes it on unmount (a bare `<img src>` would get `401`).
- Produces: run-report drill-down rendering content blocks — text inline, images through `AuthImage`; HTML export lists block structure (asset ids, no image bytes).
- Produces: a vision-capability confirmation checkbox for `openai_compatible` judges when the selected resources include `multimodal`, reset whenever the connection **or the model** changes.

- [ ] **Step 1: Write RED frontend tests**

In `frontend/tests/run-wizard.test.tsx`:

- with a dataset mapping `input`+`actual_output`, the `Multimodal` family under General shows both cards enabled in static mode;
- switching to endpoint mode disables them with the reason `Static datasets or ingestion only`;
- selecting `deepeval.image_coherence` with an `openai_compatible` connection renders a checkbox `This model accepts images` and launch stays disabled until it is checked (native `openai`/`anthropic` connections show no checkbox);
- the multimodal preset selects exactly the two image keys.

In `frontend/tests/run-report.test.tsx`: a result with `details.sample.kind === "multimodal"` renders an `Input blocks`/`Output blocks` section where text blocks appear as text and image blocks render through `AuthImage`; mock `global.fetch` to return a blob and assert the fetch call carries an `Authorization` header and the rendered `<img>` uses the object URL (mock `URL.createObjectURL` to return `"blob:mock"`), and that `URL.revokeObjectURL` fires on unmount.

In `frontend/tests/datasets-page.test.tsx`: `compatibleMetricCount` counts multimodal metrics for a dataset mapping `input`+`actual_output`.

In `backend/tests/test_exports.py`: HTML export of a multimodal result lists the block structure (asset id text present, no `<img`, no base64).

- [ ] **Step 2: Run RED**

Run:

```bash
cd frontend && npm test -- --run tests/run-wizard.test.tsx tests/run-report.test.tsx tests/datasets-page.test.tsx
cd ../backend && .venv/bin/pytest -q -p no:deepeval tests/test_exports.py
```

- [ ] **Step 3: Implement UI and report changes**

`frontend/lib/dataset-capabilities.ts` — count multimodal kinds:

```typescript
      (metric.sample_kind === "single_turn" ||
        (metric.sample_kind === "agent_trace" && fields.has("agent_trace")) ||
        (metric.sample_kind === "conversation" && fields.has("turns")) ||
        (metric.sample_kind === "multimodal" &&
          fields.has("input") &&
          fields.has("actual_output"))) &&
```

`frontend/components/RunWizard.tsx`:

- disable multimodal cards in endpoint mode: alongside `sampleKindConflict`, compute `const endpointIncompatible = mode === "endpoint" && metric.sample_kind === "multimodal";` and disable with reason `Static datasets or ingestion only`;
- vision confirmation: when `selectedResources.has("multimodal") && isCustom`, render

```tsx
<label className="config-checkbox">
  <input
    type="checkbox"
    checked={visionConfirmed}
    onChange={(event) => setVisionConfirmed(event.target.checked)}
  />
  This model accepts images
</label>
```

and add `(selectedResources.has("multimodal") && isCustom && !visionConfirmed)` to the launch-disable expression, with:

```tsx
const [visionConfirmed, setVisionConfirmed] = useState(false);
useEffect(() => {
  setVisionConfirmed(false);
}, [connectionId, model]);
```

(reset on **model** change too — a vision confirmation for one model must not carry over to another model on the same connection).

Create `frontend/components/AuthImage.tsx`:

```tsx
"use client";

import {useEffect, useState} from "react";

import {getToken} from "@/lib/api";

export function AuthImage({path, alt}: {path: string; alt: string}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    fetch(path, {headers: {Authorization: `Bearer ${getToken() ?? ""}`}})
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        revoked = URL.createObjectURL(blob);
        setObjectUrl(revoked);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);

  if (failed) return <span className="muted">Image unavailable</span>;
  if (!objectUrl) return <span className="muted">Loading image…</span>;
  return <img src={objectUrl} alt={alt} style={{maxWidth: "100%"}} />;
}
```

`backend/app/reports.py` `_result_detail_view` — multimodal branch parallel to conversation: typed fields `{"kind", "input", "actual_output", "normalizer_revision"}`, returning `"input_blocks": sample.get("input")`, `"output_blocks": sample.get("actual_output")` (plus `None` keys on the other branches). `backend/app/templates/report.html` renders block lists as `<pre>{{ detail.input_blocks|tojson(indent=2) }}</pre>` sections labeled `Input blocks`/`Output blocks` — no image embedding in the self-contained export.

`frontend/components/RunReport.tsx` `resultDetailView` — same branch; render text blocks as `<p>` and image blocks as `<AuthImage path={`/api/workspaces/${workspaceId}/assets/${block.asset_id}`} alt="result image" />` inside the metadata drill-down (never a bare `<img src>` — the asset endpoint needs the Bearer header).

Add `Create: frontend/components/AuthImage.tsx` and `Create: frontend/tests/auth-image.test.tsx` to this task's file list; the AuthImage test asserts the Authorization header, the object-URL render, the unmount revoke, and the `Image unavailable` fallback on a non-OK response.

- [ ] **Step 4: Run GREEN, build, and commit**

```bash
cd frontend
npm test -- --run tests/run-wizard.test.tsx tests/run-report.test.tsx tests/datasets-page.test.tsx
npm run build
cd ../backend && .venv/bin/pytest -q -p no:deepeval tests/test_exports.py
```

```bash
git add frontend/lib/dataset-capabilities.ts frontend/components/RunWizard.tsx frontend/components/RunReport.tsx backend/app/reports.py backend/app/templates/report.html frontend/tests/datasets-page.test.tsx frontend/tests/run-wizard.test.tsx frontend/tests/run-report.test.tsx backend/tests/test_exports.py
git commit -m "feat(ui): expose multimodal metrics and image reports"
```

---

### Task 8: Full catalog closeout verification

**Files:**

- Verify: all Phase 5 files
- Modify only if verification proves a mismatch: `docs/superpowers/specs/2026-07-14-curated-ragas-deepeval-metric-support-design.md`

- [ ] **Step 1: Run complete backend verification**

```bash
ruff check backend/app backend/tests backend/alembic/versions
cd backend
.venv/bin/pytest -q -p no:deepeval tests
.venv/bin/alembic heads
```

Expected: Ruff clean, all tests pass, exactly one `0004` head.

- [ ] **Step 2: Run complete frontend verification**

```bash
cd frontend
npm test -- --run
npx tsc --noEmit
npm run build
```

Expected: all Vitest tests, TypeScript validation, and the production build pass.

- [ ] **Step 3: Verify the complete curated catalog**

Confirm:

- exactly 25 registry keys — 8 RAG, 12 General (7 text/safety + 3 conversational + 2 multimodal), 5 Agentic (2 trace + 1 tools + 2 MCP) — matching the spec's adapter tables key for key;
- six presets exist (`rag_live`, `rag_offline_references`, `agentic`, `conversational`, `mcp`, `multimodal`) and none selects duplicate framework implementations of one concept;
- every card's validation, execution, persistence, report, and export paths are runnable for its supported sources (static/endpoint/ingestion per kind; multimodal endpoint exclusion is explicit);
- image bytes appear only in object storage and judge calls — never in the database, artifacts, snapshots, API JSON, or exports;
- remote-image fetching enforces HTTPS, MIME allowlist, 5 MiB cap, timeout, ≤3 redirects, and public-address-only resolution, including the post-redirect target;
- deterministic adapters still resolve no provider; multimodal adapters require judge + multimodal resources;
- all Phase 2–4 tests remain green and historical rows render unchanged;
- no provider or endpoint secret appears anywhere in stored or exported data.

- [ ] **Step 4: Close out**

```bash
git diff --check main...HEAD
git status --short
```

Expected: no whitespace errors and a clean branch. The curated catalog may now be advertised as complete (spec: "The feature is complete only when all 25 cards have an end-to-end passing path").
