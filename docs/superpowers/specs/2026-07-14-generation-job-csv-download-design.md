# Design: Download generation-job records as CSV; remove auto "Save as dataset"

Date: 2026-07-14

## Problem

After a generation job produces question/answer records, there is no way to
pull that data out to add or correct answers before it becomes a dataset. The
current flow auto-promotes a job into a `Dataset` via a "Save as dataset"
button, which makes generation jobs and datasets look like the same thing and
forces an incomplete dataset (drafted answers, not reviewed golden answers)
into the evaluation pipeline.

## Goal

Decouple generation jobs from datasets into a one-way manual flow:

1. Generation job produces raw records (stays a job, never auto a dataset).
2. User downloads the job's records as a CSV.
3. User edits offline (fills / corrects answers) in Excel or similar.
4. User uploads the edited CSV manually through the existing Datasets upload,
   which already includes a column-mapping step.

## Non-goals

- No in-app dataset editing / re-upload-in-place. Dataset creation stays via the
  existing manual upload only.
- No new schema-mapping UI. The existing `ColumnMapper` in `DatasetUpload.tsx`
  already covers mapping after upload.
- No JSON/JSONL download option. CSV only (user works in Excel).

## Backend changes (`backend/app/routers/generation.py`)

### Add — CSV download endpoint

`GET /api/workspaces/{workspace_id}/generation-jobs/{job_id}/records.csv`

- Returns 409 if `job.status != "completed"`.
- Selects `GenerationRecord` rows for the job with `deleted=False`, ordered by
  `record_index`.
- CSV columns, in order: `question`, `answer`, `contexts`.
- `contexts` (a `list[str]`) is serialized into a single cell as a JSON array
  string via `json.dumps(contexts, ensure_ascii=False)`. This round-trips
  cleanly: on re-upload, `app.tasks._contexts()` already does `json.loads` on a
  string cell and falls back to a single-element list otherwise.
- Build CSV with the stdlib `csv` module (`csv.writer` over a `StringIO`) so
  commas/quotes/newlines in question/answer are correctly escaped. Emit a header
  row.
- Response: `media_type="text/csv"`, header
  `Content-Disposition: attachment; filename="<safe-name>.csv"` where
  `<safe-name>` is the job name reduced to a safe ASCII slug (fall back to
  `job-{id}` if empty). Non-ASCII / quote / control chars must not break the
  header.

### Remove — auto dataset promotion

- Delete the `POST /{job_id}/dataset` endpoint (`save_dataset`).
- Delete the `SaveDatasetIn` model.
- Leave `update_record` (`PATCH /{job_id}/records/{record_id}`) in place. Its
  guard `if job.status != "completed" or job.dataset_created` still holds:
  `dataset_created` is now always `False`, so records remain editable for any
  completed job. No logic change needed there.

### DB columns — leave in place

`GenerationJob.dataset_id` and `GenerationJob.dataset_created` become vestigial
(always `None` / `False`). Keep the columns to avoid a migration in this change.
`_job_out` may keep returning them. `datasets.py delete_dataset` still nulls
`GenerationJob.dataset_id` — harmless, leave it. Dropping these columns is a
possible follow-up, out of scope here.

## Frontend changes (`frontend/components/GenerateWizard.tsx`)

### Review step — keep, swap save for download

- Keep the review step: paginated record list, inline edit of
  question/answer/contexts, delete bad rows.
- Remove the "Save dataset" `<form>` (the name input + submit that POSTs to
  `.../dataset`), the `save` handler, and the `savedDataset` state / `onSaved`
  callback plumbing.
- Add a **Download CSV** button in the review step. Auth is a Bearer token in a
  header (localStorage), so a bare anchor will not carry it. Use the existing
  `download(path, filename)` helper in `frontend/lib/api.ts` (it fetches with the
  Bearer header and triggers a Blob download). Call it with
  `/api/workspaces/{workspaceId}/generation-jobs/{job.id}/records.csv` and a
  filename derived from the job name.

### Job list row — replace "Review & save"

- For a completed job: keep the button that opens the review step (rename its
  label from "Review & save" to "Review"), plus the existing Delete.
- Remove the `item.dataset_created` gate and the " · saved" status label; with
  promotion gone they are dead.

### Datasets page (`frontend/app/w/[workspace]/datasets/page.tsx`)

- Optional: add one hint line tying the flows together, e.g. "Generated records
  from a job? Download its CSV, add answers, then upload it here." No logic
  change.

## Data flow (end to end)

```
Generation job (completed)
  -> Review step: edit/delete records inline (optional)
  -> Download CSV  [question, answer, contexts(JSON string)]
  -> user edits answers offline in Excel
  -> Datasets page: Upload CSV
  -> ColumnMapper: map question->input, answer->expected_output,
                   contexts->contexts (PATCH schema-map)
  -> Dataset ready for eval runs
```

## Testing

Backend (pytest, `backend/tests`):
- `records.csv` on a completed job returns 200, `text/csv`, attachment header,
  a header row, and one row per non-deleted record in `record_index` order.
- Deleted records are excluded.
- `contexts` cell is valid JSON and re-parses to the original list; a question
  or answer containing a comma/quote/newline is correctly escaped and re-parses.
- 409 when the job is not completed.
- 404 for unknown job / wrong workspace.
- The removed `POST /{job_id}/dataset` route now returns 404/405 (and any
  existing test for it is deleted/updated).

Frontend (vitest, `frontend/tests`):
- Update/remove tests asserting the "Save dataset" form or `dataset_created`
  label.
- Assert the review step renders a Download CSV control pointing at the
  records.csv endpoint.

## Consequences / risks

- Users must now map schema columns manually after upload (previously
  auto-set). The existing `ColumnMapper` covers this; the mapping requires
  `input` at minimum before save (existing guard). Acceptable, and matches the
  intended manual flow.
- `dataset_id` / `dataset_created` linger as unused columns — noted as a
  follow-up cleanup, not blocking.
