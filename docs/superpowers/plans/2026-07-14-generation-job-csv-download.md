# Generation-Job CSV Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users download a completed generation job's records as CSV to edit answers offline, and remove the auto "Save as dataset" promotion so datasets are created only via manual upload.

**Architecture:** Add a read-only CSV export endpoint on the generation-jobs router; delete the dataset-promotion endpoint. In the frontend, the review step gains a Download CSV button (via the existing `download()` helper) and loses the save form; datasets are created only through the existing upload + column-mapper flow.

**Tech Stack:** FastAPI + SQLAlchemy (backend, pytest), Next.js + React + TypeScript (frontend, vitest + testing-library).

## Global Constraints

- CSV columns, exact order: `question`, `answer`, `contexts`.
- `contexts` (a `list[str]`) serialized in one CSV cell as `json.dumps(contexts, ensure_ascii=False)`. This round-trips: `app/tasks.py::_contexts()` already `json.loads`-es a string cell.
- Frontend auth is a Bearer token in a request header (localStorage). Bare anchors do NOT carry it — use `download(path, filename)` from `frontend/lib/api.ts`.
- DB columns `GenerationJob.dataset_id` / `dataset_created` stay (no migration); they become vestigial.
- **Commits require explicit user approval every time** (user preference). Prepare the commit and ask before running `git commit`.

---

## File Structure

- `backend/app/routers/generation.py` — add CSV endpoint, remove `save_dataset` + `SaveDatasetIn` + now-unused imports.
- `backend/tests/test_generation_api.py` — add CSV tests, remove/trim save-dataset tests.
- `frontend/components/GenerateWizard.tsx` — review step: swap save form for Download CSV; remove "saved" step + `dataset_created` label/gate.
- `frontend/tests/generate-wizard.test.tsx` — repoint save-based tests to Download; drop the "Dataset saved" test.
- `frontend/app/w/[workspace]/datasets/page.tsx` — add one hint line.

---

## Task 1: Backend — CSV download endpoint

**Files:**
- Modify: `backend/app/routers/generation.py`
- Test: `backend/tests/test_generation_api.py`

**Interfaces:**
- Consumes: existing `_get_job(job_id, workspace_id, db)`, `GenerationRecord` model, `Response` (fastapi), stdlib `csv`, `io`, `re`, `json`.
- Produces: `GET /api/workspaces/{workspace_id}/generation-jobs/{job_id}/records.csv` → `text/csv` attachment. Header row + one row per non-deleted record ordered by `record_index`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_generation_api.py`:

```python
def test_download_records_csv_matches_records(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    import csv as csvlib
    import io
    import json as jsonlib

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    records = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"]

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csvlib.DictReader(io.StringIO(response.text)))
    assert list(rows[0].keys()) == ["question", "answer", "contexts"]
    assert len(rows) == len(records)
    assert rows[0]["question"] == records[0]["question"]
    assert rows[0]["answer"] == records[0]["answer"]
    assert jsonlib.loads(rows[0]["contexts"]) == records[0]["contexts"]


def test_download_records_csv_excludes_deleted_and_escapes(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    import csv as csvlib
    import io
    import json as jsonlib

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    records = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"]

    client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{records[0]['id']}",
        json={"deleted": True},
        headers=auth_headers,
    )
    tricky = 'He said, "hi"\nnew line'
    client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{records[1]['id']}",
        json={"answer": tricky},
        headers=auth_headers,
    )

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    rows = list(csvlib.DictReader(io.StringIO(response.text)))
    assert len(rows) == len(records) - 1
    assert records[0]["question"] not in {row["question"] for row in rows}
    assert tricky in {row["answer"] for row in rows}


def test_download_records_csv_requires_completed(
    client, auth_headers, db, object_store, fake_generator, workspace_with_key
):
    from app.models import GenerationJob

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    row = db.get(GenerationJob, job["id"])
    row.status = "pending"
    db.commit()

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_download_records_csv_missing_job_returns_404(
    client, auth_headers, workspace_with_key
):
    response = client.get(
        f"/api/workspaces/{workspace_with_key}/generation-jobs/not-a-job/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_generation_api.py -k download_records_csv -v`
Expected: FAIL — 404/405 (route not defined yet).

- [ ] **Step 3: Add imports**

In `backend/app/routers/generation.py`, extend the fastapi import and add stdlib imports at the top:

```python
import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
```

(`json` and `uuid` are already imported — do not duplicate. Add `csv`, `io`, `re`, and `Response`.)

- [ ] **Step 4: Add the endpoint**

Add near the other `/records` routes in `backend/app/routers/generation.py`:

```python
def _safe_filename(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return slug or "generation-job"


@router.get("/{job_id}/records.csv")
def download_records_csv(
    job_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    job = _get_job(job_id, ws.id, db)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Generation job is not completed")
    records = (
        db.query(GenerationRecord)
        .filter_by(job_id=job.id, workspace_id=ws.id, deleted=False)
        .order_by(GenerationRecord.record_index)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["question", "answer", "contexts"])
    for record in records:
        writer.writerow(
            [
                record.question,
                record.answer,
                json.dumps(record.contexts, ensure_ascii=False),
            ]
        )
    filename = _safe_filename(job.name)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_generation_api.py -k download_records_csv -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit (ask user first)**

Ask the user to approve, then:

```bash
git add backend/app/routers/generation.py backend/tests/test_generation_api.py
git commit -m "feat: add CSV download for generation-job records"
```

---

## Task 2: Backend — remove auto "Save as dataset"

**Files:**
- Modify: `backend/app/routers/generation.py`
- Test: `backend/tests/test_generation_api.py`

**Interfaces:**
- Removes route `POST /{job_id}/dataset` and model `SaveDatasetIn`.
- No new interface. `update_record` guard `job.status != "completed" or job.dataset_created` is unchanged (`dataset_created` is always `False` now, so completed jobs stay editable).

- [ ] **Step 1: Delete the endpoint and model**

In `backend/app/routers/generation.py`:
- Delete the entire `save_dataset` function (the `@router.post("/{job_id}/dataset", ...)` handler).
- Delete the `SaveDatasetIn` class.
- Remove now-unused imports: `uuid`, `storage` (`from app import storage`), and `Dataset` from the `app.models` import list. Keep `json` (used by the CSV endpoint from Task 1). Keep `GenerationRecord`, `GenerationJob`, `Document`, `OutboxEvent`, `ProviderConnection`, `Workspace`.

- [ ] **Step 2: Remove/trim the save-dataset tests**

In `backend/tests/test_generation_api.py`:
- Delete these tests entirely: `test_save_dataset_materializes_jsonl`, `test_save_dataset_serializes_concurrent_requests`, `test_patch_record_waits_for_concurrent_save`.
- In `test_patch_record_requires_completed_unsaved_job`: keep everything up to and including the `running.status_code == 409` assertion; delete the remainder of the function from the line `saved_job.status = "completed"` through the final `after_save` assertion (the save + edit-after-save block). The test now ends after the running-status assertion.
- Leave `_job_with_drafts`, `test_delete_finished_job_removes_drafts_and_preserves_dataset`, and `test_delete_active_job_requires_cancel_first` unchanged — they set `dataset_created`/`dataset_id` via the ORM and still pass because the columns remain.

- [ ] **Step 3: Run the full generation API suite**

Run: `cd backend && python -m pytest tests/test_generation_api.py -v`
Expected: PASS — no remaining reference to `/dataset`; no import errors.

- [ ] **Step 4: Run the full backend suite to catch fallout**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit (ask user first)**

Ask the user to approve, then:

```bash
git add backend/app/routers/generation.py backend/tests/test_generation_api.py
git commit -m "feat: remove auto save-as-dataset from generation jobs"
```

---

## Task 3: Frontend — Download CSV in review step

**Files:**
- Modify: `frontend/components/GenerateWizard.tsx`
- Test: `frontend/tests/generate-wizard.test.tsx`

**Interfaces:**
- Consumes: `download(path, filename)` from `@/lib/api`; the new `records.csv` endpoint from Task 1.
- `ReviewTable` no longer takes an `onSaved` prop. The wizard drops the `"saved"` step and `savedDataset` state.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/generate-wizard.test.tsx` inside `describe("GenerateWizard", ...)`. It mocks the blob download plumbing and asserts the CSV endpoint is fetched:

```typescript
it("downloads records as CSV from the review step", async () => {
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:mock");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});

  let csvRequested = false;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = typeof input === "string" ? input : input.toString();
    if (path.endsWith("/generation-jobs")) {
      return jsonResponse([completedJob]);
    }
    if (path.includes("/records.csv")) {
      csvRequested = true;
      return Promise.resolve(
        new Response("question,answer,contexts\n", {
          status: 200,
          headers: { "content-type": "text/csv" },
        }),
      );
    }
    if (path.includes("/records")) {
      return jsonResponse(recordPage);
    }
    return jsonResponse([]);
  });

  render(<GenerateWizard workspaceId="ws-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Review" }));
  fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));

  await waitFor(() => expect(csvRequested).toBe(true));
  expect(clickSpy).toHaveBeenCalled();
  createObjectURL.mockRestore();
});
```

(Reuse the existing `completedJob`, `recordPage`, `jsonResponse`, `render`, `screen`, `fireEvent`, `waitFor` helpers already imported in the file. If `completedJob`/`recordPage` are defined locally in other tests, hoist a shared fixture or inline the minimal objects — mirror the shapes used in the existing `"Review"` tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/generate-wizard.test.tsx -t "downloads records as CSV"`
Expected: FAIL — no "Download CSV" button.

- [ ] **Step 3: Import the download helper**

At the top of `frontend/components/GenerateWizard.tsx`, add `download` to the api import, e.g.:

```typescript
import { api, download } from "@/lib/api";
```

(Match the existing import style/path for `api` in the file.)

- [ ] **Step 4: Replace the save form with a Download panel**

In `ReviewTable` (`frontend/components/GenerateWizard.tsx`), replace the `<form className="panel" aria-label="Save dataset" ...>...</form>` block with:

```tsx
      <section className="panel" aria-label="Download records">
        <h2>Download records</h2>
        <p className="muted">
          Download as CSV, fill in or correct answers offline, then upload it on the Datasets page.
        </p>
        {error && <p className="notice error">{error}</p>}
        <div className="list-row">
          <button
            className="primary"
            disabled={busy || pendingCount > 0 || hasEditFailure}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const edits = await Promise.all([...pendingEdits.current]);
                if (failedEdits.current.size || edits.some((ok) => !ok)) return;
                await download(
                  `/api/workspaces/${workspaceId}/generation-jobs/${job.id}/records.csv`,
                  `${job.name}.csv`,
                );
              } catch (reason) {
                setError(reason instanceof Error ? reason.message : "Could not download records");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Preparing…" : "Download CSV"}
          </button>
          <a className="ghost" href={`/w/${workspaceId}/datasets`}>Go to datasets</a>
        </div>
      </section>
```

Then remove the now-dead members of `ReviewTable`: the `save` function, the `datasetName` state, the `saving` ref, and the `onSaved` prop (both from the destructured params and the `ReviewTable` type). Keep `pendingEdits`, `failedEdits`, `pendingCount`, `hasEditFailure`, `busy`, `error`, and the edit/patch machinery.

- [ ] **Step 5: Drop the "saved" step and dataset_created UI**

In the `GenerateWizard` component body:
- Change the review-step render to not pass `onSaved`:

```tsx
  if (step === "review" && job) {
    return <ReviewTable workspaceId={workspaceId} job={job} />;
  }
```

- Delete the entire `if (step === "saved" && savedDataset) { ... }` block.
- Delete the `savedDataset` state declaration and remove `"saved"` from the `step` state's union type if it is typed explicitly.
- In the generation-jobs list row, change the `<small>` to drop the saved label:

```tsx
                  <small>
                    {item.status} · {item.generated_count}/{item.requested_count} records
                  </small>
```

- Change the completed-job Review button condition from `item.status === "completed" && !item.dataset_created` to just `item.status === "completed"`.
- Add a direct **Download CSV** button on completed job rows (next to Review), so history is downloadable without opening the review step. Place it inside the same `item.status === "completed"` block:

```tsx
                {item.status === "completed" && (
                  <>
                    <button className="ghost" disabled={busy} onClick={() => { setJob(item); setStep("review"); }}>
                      Review
                    </button>
                    <button
                      className="ghost"
                      disabled={busy}
                      onClick={() => download(
                        `/api/workspaces/${workspaceId}/generation-jobs/${item.id}/records.csv`,
                        `${item.name}.csv`,
                      )}
                    >
                      Download CSV
                    </button>
                  </>
                )}
```

(Replace the old single-button `item.status === "completed" && !item.dataset_created` block with this. The Delete block below it is unchanged.)

- [ ] **Step 5b: Test the history-row download**

Add to `frontend/tests/generate-wizard.test.tsx`:

```typescript
it("downloads a completed job's CSV directly from history", async () => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});

  let csvRequested = false;
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = typeof input === "string" ? input : input.toString();
    if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
    if (path.includes("/records.csv")) {
      csvRequested = true;
      return Promise.resolve(
        new Response("question,answer,contexts\n", {
          status: 200,
          headers: { "content-type": "text/csv" },
        }),
      );
    }
    return jsonResponse([]);
  });

  render(<GenerateWizard workspaceId="ws-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));

  await waitFor(() => expect(csvRequested).toBe(true));
  expect(clickSpy).toHaveBeenCalled();
});
```

(If two "Download CSV" buttons could match — the review one is only rendered after clicking Review — this history-list test never opens review, so the only "Download CSV" present is the row button. Reuse the shared `completedJob`/`jsonResponse` helpers.)

- [ ] **Step 6: Update the existing save-based tests**

In `frontend/tests/generate-wizard.test.tsx`:
- Delete the test `"locks review mutations once dataset saving begins"` (it asserts the removed "Dataset saved" heading and POST `/dataset` flow).
- In `"waits for an in-flight edit before saving"` and `"keeps a failed edit blocking save after another edit succeeds"`: replace the `fireEvent.submit(screen.getByRole("form", { name: "Save dataset" }))` / POST `/dataset` interactions with clicking the `"Download CSV"` button, and add the `URL.createObjectURL` / `HTMLAnchorElement.prototype.click` / `/records.csv` fetch stubs shown in Step 1. Any `if (path.endsWith("/dataset") ...)` fetch branch becomes an `if (path.includes("/records.csv") ...)` branch returning the CSV Response.
- In `"serializes same-field edits in server order"`, `"queues a server-value revert behind an in-flight edit"`, and `"clears text and context failures when reverted to server values"`: replace every `screen.getByRole("button", { name: "Save as dataset" })` with `screen.getByRole("button", { name: "Download CSV" })`. These assert enabled/disabled state as a proxy for edit-chain completion; the Download button carries the same `disabled={busy || pendingCount > 0 || hasEditFailure}` guard, so the assertions hold with the new name.

- [ ] **Step 7: Run the frontend suite**

Run: `cd frontend && npx vitest run tests/generate-wizard.test.tsx`
Expected: PASS.

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (confirms `savedDataset`, `onSaved`, `datasetName`, `saving`, and the `"saved"` step were fully removed).

- [ ] **Step 9: Commit (ask user first)**

Ask the user to approve, then:

```bash
git add frontend/components/GenerateWizard.tsx frontend/tests/generate-wizard.test.tsx
git commit -m "feat: download generation records as CSV, drop save-as-dataset UI"
```

---

## Task 4: Frontend — Datasets page hint

**Files:**
- Modify: `frontend/app/w/[workspace]/datasets/page.tsx`

**Interfaces:** none. Copy-only change.

- [ ] **Step 1: Add the hint line**

In `frontend/app/w/[workspace]/datasets/page.tsx`, update the header sub-paragraph under `<h1>Datasets</h1>` to tie the flows together:

```tsx
<p className="muted">Upload examples once, then reuse them across evaluation runs. Generated records from a job? Download its CSV, add answers, then upload it here.</p>
```

- [ ] **Step 2: Verify it renders**

Run: `cd frontend && npx vitest run` (full suite) OR visually confirm via the app.
Expected: PASS / hint visible.

- [ ] **Step 3: Commit (ask user first)**

Ask the user to approve, then:

```bash
git add frontend/app/w/[workspace]/datasets/page.tsx
git commit -m "docs: hint linking generation download to dataset upload"
```

---

## Self-Review Notes

- **Spec coverage:** CSV endpoint (Task 1) ✓; contexts JSON round-trip (Task 1 Step 4 + test) ✓; remove save endpoint/model (Task 2) ✓; keep record edit (Task 2, guard untouched) ✓; keep DB columns (Task 2 Step 1, imports note) ✓; review step kept + Download button (Task 3) ✓; row label/gate cleanup (Task 3 Step 5) ✓; datasets hint (Task 4) ✓; manual schema mapping already exists (no task needed — `ColumnMapper` covers it).
- **Type consistency:** `download(path, filename)` signature matches `frontend/lib/api.ts`. `_safe_filename`, `download_records_csv`, and the CSV column order match across endpoint and tests.
- **Vestigial columns** `dataset_id`/`dataset_created` are intentionally retained; dropping them is a possible follow-up, not in this plan.
