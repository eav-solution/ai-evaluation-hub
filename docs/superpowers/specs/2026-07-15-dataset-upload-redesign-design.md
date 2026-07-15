# Dataset Upload Redesign — Design

**Date:** 2026-07-15
**Status:** Approved pending user review
**Scope:** The upload zone in `frontend/components/DatasetUpload.tsx` plus its CSS. `ColumnMapper` internals, the dataset list section, and the backend stay unchanged.

## Problem

The current upload form has six defects:

1. The "Drop in a dataset" area is decoration only — no `onDragOver`/`onDrop` handlers exist. Dropping a file makes the browser navigate to the raw file.
2. The file input is visually hidden and nothing echoes the chosen file, so after "Choose file" the user gets zero feedback.
3. The dataset name must be typed by hand even though the filename is a fine default.
4. Only one file can be uploaded at a time; there is no way to ingest a folder tree such as `sample_datasets/`.
5. No client-side validation: a wrong extension or an over-limit file is discovered only after a wasted POST (server enforces 5,000 rows in `backend/app/datasets.py`).
6. After upload, `ColumnMapper` abruptly replaces the whole panel with no step indication, and every column must be mapped by hand even when column names already match schema fields exactly.

## Goals

- Real drag-and-drop for files **and folders** (recursive scan).
- A folder picker button in addition to the file picker.
- Staged review before upload: per-file row with record count and an editable, prefilled dataset name.
- Batch upload with per-file progress and per-file errors.
- Auto-map columns whose names match schema field keys after each upload.
- Client-side rejection of unsupported extensions and over-limit files before any POST.

## Non-goals

- Redesigning the dataset list, tabs, or empty state.
- Changing `ColumnMapper` internals (it is reused as-is).
- Backend changes. Every file is still one `POST /api/workspaces/{id}/datasets`; auto-mapping uses the existing `PATCH .../schema-map`.

## Design

### States

`idle → staged (file list) → uploading → results`, with `×`/reset paths back to `idle`.

### 1. Intake

Three ways to add files, all funneling into one staged list:

- **Click / keyboard** on the dropzone opens the hidden file input (`multiple`, `accept=".csv,.json,.jsonl"`). The dropzone gets `role="button"`, `tabIndex=0`, Enter/Space activation, and an `aria-label`.
- **"Choose folder" button** backed by a second hidden input with `webkitdirectory`.
- **Drag-and-drop** of any mix of files and folders. `onDrop` walks `DataTransferItem.webkitGetAsEntry()` recursively. `onDragOver` prevents default and sets a `dragover` highlight class; window-level `dragover`/`drop` listeners prevent the browser from navigating when a drop misses the zone.

Filtering: keep only `.csv`, `.json`, `.jsonl` (case-insensitive). Everything else (including dotfiles like `.DS_Store`) is skipped silently; if any were skipped, show one line: "Skipped N unsupported files". Adding files appends to the existing staged list; a duplicate of an already-staged file (same name + size) is ignored.

### 2. Staged list

Each row: file-type icon · filename · record count · dataset name input · remove (×) button.

- **Dataset name** is prefilled with the filename minus its extension, editable per row. User edits are never overwritten.
- **Record count** is computed client-side right after staging by reading the file text:
  - CSV: data rows excluding the header, counted with a quote-aware scanner so multi-line cells are not miscounted.
  - JSON: array length (a non-array top level counts as invalid → error badge).
  - JSONL: non-empty lines.
  While counting, the row shows a subtle "counting…" placeholder.
- **Over-limit files** (> 5,000 records) get an error badge ("exceeds 5,000 rows") and are excluded from the batch. Unreadable/unparseable files get an error badge likewise.
- Upload button label shows the actionable count, e.g. "Upload 12 files"; disabled when there are no uploadable rows or when any uploadable row has an empty name (error-badged rows don't count).

### 3. Upload (sequential batch)

- POST one file at a time, in list order, with progress "n/N" and `aria-busy` on the zone.
- A failed POST marks that row with the server error and continues with the next file.
- `onComplete(dataset)` fires after each successful upload so the page list refreshes incrementally.

### 4. Auto-map + results

After each successful POST, compute a mapping from the dataset's `preview` columns:

- A column whose name exactly matches a schema field key maps 1:1. Keys: `input`, `actual_output`, `expected_output`, `retrieval_contexts`, `context`, `agent_trace`, `tools_called`, `expected_tools`, `turns`, `chatbot_role`, `conversation_context`, `mcp_metadata`, `mcp_events`.
- A column named `contexts` (legacy alias) maps to `retrieval_contexts`.
- If the mapping is non-empty, `PATCH .../schema-map` immediately.

The results panel then shows one row per file: ✓/✗ · dataset name · "N columns mapped" · a **"needs mapping"** badge when neither `input` nor `turns` got mapped · a **Map** button that opens `ColumnMapper` inline (expanded under the row) for that dataset. Saving the mapper PATCHes, collapses the row, and clears the badge. A "Done" button resets the panel to `idle`.

With this, `sample_datasets/` (columns named to match schema fields; `case`/`note` intentionally unmapped) uploads and maps end-to-end with zero manual mapping.

### Code structure

- New pure-function module `frontend/lib/dataset-staging.ts`: `isSupportedFile`, `stripExtension`, `detectFormat`, `countRecords(text, format)`, `collectFilesFromDataTransfer(items)`, `autoMapColumns(columns)`. Keeps `DatasetUpload.tsx` lean and the logic unit-testable without DOM.
- `DatasetUpload.tsx`: replaces the single-file form with the staged-list flow; keeps its public props (`workspaceId`, `onComplete`) so `datasets/page.tsx` is untouched.
- `globals.css`: `.upload-drop.dragover`, staged/result row styles, `.upload-zone` grid reduced to two columns; the separate "Choose file" pill button is removed (the dropzone is the picker), "Choose folder" becomes a secondary button.

### Error handling

| Case | Behavior |
|---|---|
| Unsupported extension | Skipped at intake, counted in "Skipped N unsupported files" |
| > 5,000 records / unparseable | Error badge on row, excluded from batch |
| Server rejects a file | Error message on that row, batch continues |
| Folder with zero supported files | Notice: "No CSV/JSON/JSONL files found" |
| Empty dataset name | Upload button disabled |

### Testing

Unit (vitest, no DOM) on `dataset-staging.ts`:
- `countRecords`: CSV with quoted multi-line cells; JSONL blank lines; JSON non-array → invalid.
- `autoMapColumns`: exact matches, `contexts` alias, unknown columns (`case`, `note`) ignored.
- `isSupportedFile`: case-insensitive extensions, dotfiles rejected.

Component (vitest + RTL, `datasets-page.test.tsx` / new `dataset-upload.test.tsx`):
- Staging a file prefils the name and shows the record count.
- Removing a staged file returns to idle.
- An over-limit file shows the badge and is excluded from the upload count.
- Batch with one failing file: error on that row, remaining files still POSTed.
- Auto-map PATCH payload matches expected mapping; "needs mapping" badge appears when neither `input` nor `turns` mapped; Map button reveals `ColumnMapper`.
