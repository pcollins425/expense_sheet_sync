# Expense sheet outbound sync (Docker)

Polls `finance.expense_sheet_out_queue` and writes rows to Google Sheets from `finance.vw_expense_supervisor_sheet`.

## Prerequisites

- SQL migrations applied on `dgs_application_db`:
  - `2026-06-16_finance_expense_supervisor_line.sql`
  - `2026-06-16_finance_expense_sheet_queues.sql`
  - `2026-06-16_finance_vw_expense_supervisor_sheet.sql`
- SQL grants for watcher login (`MSSQL_USER` in `secrets/.env`):
  - `sql/grant_expense_sheet_watcher.sql` (run on `dgs_application_db` with privileged login)
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
