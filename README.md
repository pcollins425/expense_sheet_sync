# Expense sheet outbound sync (Docker)

Polls `finance.expense_sheet_out_queue` and writes rows to Google Sheets from `finance.vw_expense_supervisor_sheet`.

## Prerequisites

- SQL migrations applied on `dgs_application_db`:
  - `2026-06-16_finance_expense_supervisor_line.sql`
  - `2026-06-16_finance_expense_sheet_queues.sql`
  - `2026-06-16_finance_vw_expense_supervisor_sheet.sql`
  - `2026-06-16_finance_expense_sheet_ref_enqueue.sql`
- SQL grants for watcher login (`MSSQL_USER` in `secrets/.env`):
  - `sql/grant_expense_sheet_watcher.sql`
  - `sql/grant_expense_sheet_ref_watcher.sql`
- ESL backfill complete (`scripts/backfill_expense_supervisor_line.py --apply`)
- Google OAuth refresh token with **Spreadsheets** scope (master credentials `GMAIL_*`)
- Service account or user must have **edit** access to the target spreadsheet

## Default sheet

| Setting | Default |
|---|---|
| `EXPENSE_SHEET_ID` | `1cfdOzzAtiQYVLSaFtiZLYLKcqyD07ANkIsgEV5lGqXM` ([quickbooks_export](https://docs.google.com/spreadsheets/d/1cfdOzzAtiQYVLSaFtiZLYLKcqyD07ANkIsgEV5lGqXM)) |
| `EXPENSE_SHEET_TAB` | `root` (gid=0) |

## Setup

```bash
cp secrets/.env.example secrets/.env   # create manually on Windows if needed
# Edit secrets/.env — MSSQL_* + GMAIL_* + EXPENSE_SHEET_*

docker compose up -d --build
```

Compose runs two services:

| Service | Role |
|---|---|
| `expense-sheet-out-watcher` | SQL queue → `root` tab (ESL lines) |
| `expense-sheet-ref-watcher` | SQL reference tables → validation tabs + enqueue `root` refresh |

First start of the ref watcher seeds SQL snapshots (no sheet writes). Bootstrap all reference tabs from SQL:

```bash
docker compose run --rm expense-sheet-ref-watcher python -u run.py --bootstrap
```

## Bootstrap (first full push)

```bash
docker compose run --rm expense-sheet-out-watcher python -u run.py --bootstrap
```

Then start the watcher (or rely on queue for incremental updates).

## Local dev (WSL)

```bash
pip install -r expense_sheet_out_watcher/requirements.txt
export MASTER_CREDENTIALS_ENV=/mnt/e/master_credentials/.env
cd expense_sheet_out_watcher
python -u run.py --once
```

## Column layout (row 1)

`reference_key` | `Date` | `Card Member` | `Amount` | `Comments` | `Description` | `Tribe/Dynamic location` | `State` | `Casino/Dynamic location` | `Expense Account` | `Receipt`

Column **A** (`reference_key` = `ESL-…`) is the sync anchor for upsert/delete.

## Queue behavior

- `op: insert` / `update` → re-read DB view, upsert sheet row
- `op: delete` → clear sheet row (recycle / hard delete)

Failed rows retry until `EXPENSE_SHEET_MAX_ATTEMPTS`, then `status = dead`.

## Reference-tab watcher (SQL → Sheet)

Polls SQL every `EXPENSE_SHEET_REF_POLL_SECONDS` (default 30). When reference data changes, rewrites the sheet tab and enqueues ESL rows on `root` for the outbound watcher.

| SQL source | Sheet tab |
|---|---|
| `clients.states` | `States` |
| `clients.tribes` | `Tribes` |
| `clients.casinos` | `Casinos` |
| `finance.expense_account_gl_display` | `account_select` |

Snapshots persist in Docker volume `expense-sheet-ref-state`.

Google Sheets allows **60 write requests/minute/user**. The ref watcher batches tab updates into **one** `batchUpdate` per poll. On HTTP 429 it backs off and retries (`EXPENSE_SHEET_REF_RETRY_SECONDS`, default 15). Run **`--bootstrap` once** after deploy so the first poll cycle does not rewrite every tab.
