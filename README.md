# Expense sheet outbound sync (Docker)

Polls `finance.expense_sheet_out_queue` and writes rows to Google Sheets from `finance.vw_expense_supervisor_sheet`.

## Server deploy (canonical)

**The slot server pulls only one repo:** [pcollins425/expense_sheet_sync](https://github.com/pcollins425/expense_sheet_sync) (clone path e.g. `E:\expense_sheet_sync`).

| Repo | Role |
|---|---|
| **`cursor-assistant`** | Develop here (`deploy/expense_sheet_sync/`, root `expense_sheet_*_watcher/`, SQL migrations, Apps Script source). |
| **`expense_sheet_sync`** | **Deploy artifact** — must be pushed before you `git pull` on the server. |

After any change under `deploy/expense_sheet_sync/` (or watchers copied into it):

```bash
# From cursor-assistant (WSL)
bash scripts/push_expense_sheet_sync_deploy.sh "Short commit message"
```

Then on the slot server:

```bash
cd expense_sheet_sync
git pull
docker compose build --no-cache
docker compose up -d
```

Do **not** mix `git pull` on `cursor-assistant` + `cd deploy/expense_sheet_sync` for production tests unless that clone is what the server actually runs. One pull location only.

## Prerequisites

- SQL migrations applied on `dgs_application_db`:
  - `2026-06-16_finance_expense_supervisor_line.sql`
  - `2026-06-16_finance_expense_sheet_queues.sql`
  - `2026-06-16_finance_vw_expense_supervisor_sheet.sql`
  - `2026-06-16_finance_expense_sheet_ref_enqueue.sql`
  - `2026-06-18_finance_expense_sheet_inbound.sql`
  - `2026-06-19_finance_expense_sheet_inbound_materialize_expense.sql`
  - `2026-06-20_finance_override_receipt_sheet_two_way.sql`
- SQL grants for watcher login (`MSSQL_USER` in `secrets/.env`):
  - `sql/grant_expense_sheet_watcher.sql`
  - `sql/grant_expense_sheet_ref_watcher.sql`
  - `sql/grant_expense_sheet_in_watcher.sql`
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

Compose runs four services:

| Service | Role |
|---|---|
| `expense-sheet-out-watcher` | SQL queue → `root` tab (ESL lines) |
| `expense-sheet-ref-watcher` | SQL reference tables → validation tabs + `findReplace` on renames |
| `expense-sheet-in-watcher` | Sheet webhook → `expense_sheet_in_queue` → ESL / roots + GL catalog |
| `expense-sheet-alert-watcher` | Reclaim stale `processing`; Resend **event** on dead + **daily** digest |

## Alerts (Resend)

Silent dead/stuck queues are a drift risk. Alerts use **Resend** (`RESEND_API_KEY` in `secrets/.env`).

| Mode | When |
|---|---|
| **Event** | In/out watcher marks a queue row **dead** (after max attempts) → immediate email |
| **Daily** | Alert watcher once per Chicago day at `EXPENSE_SHEET_ALERT_DAILY_HOUR` (default 8) → counts + dead samples |

Also reclaims `processing` older than `EXPENSE_SHEET_STALE_PROCESSING_MINUTES` (default 30) back to `pending`.

```bash
# Force today's digest (idempotent per day via Resend key)
docker compose run --rm expense-sheet-alert-watcher python -u run.py --daily-now
```

Default to: `paulc@dynamicgamingsolutions.com` (`EXPENSE_SHEET_ALERT_TO`).

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

`reference_key` | `Date` | `Card Member` | `Amount` | `Comments` | `Description` | `Tribe/Dynamic location` | `State` | `Casino/Dynamic location` | `Expense Account` | `Receipt` | `Override Receipt`

Column **L** (`Override Receipt`) is a checkbox synced with `finance.expenses.override_receipt` (two-way via Apps Script inbound + outbound watcher).

Column **A** (`reference_key` = `ESL-…`) is the sync anchor for upsert/delete.

## Queue behavior

- `op: insert` / `update` → re-read DB view, upsert sheet row
- `op: delete` → clear sheet row (recycle / hard delete)

Failed rows retry until `EXPENSE_SHEET_MAX_ATTEMPTS`, then `status = dead`.

## Reference-tab watcher (SQL → Sheet)

Polls SQL (`clients.states`, `clients.tribes`, `clients.casinos`) every `EXPENSE_SHEET_REF_POLL_SECONDS` (default 30).

| SQL change | Action |
|---|---|
| New / updated validation row | Rewrite tab (batched `batchUpdate`) |
| Renamed display label | `findReplace` on `root` column G (tribe), H (state abbrev), or I (casino) — whole cell, one column |
| `account_select` | **Not synced** — supervisor-owned on sheet |

**No ESL queue fan-out** on reference changes.

```bash
docker compose run --rm expense-sheet-ref-watcher python -u run.py --bootstrap
```

Snapshots persist in Docker volume `expense-sheet-ref-state`.

Google Sheets allows **60 read and 60 write requests/minute/user** (same OAuth user for both watchers).

- **Ref watcher:** batched tab writes + batched `findReplace` on renames; 429 retry (`EXPENSE_SHEET_REF_RETRY_SECONDS`, default 15).
- **Outbound watcher:** one column-A read per queue drain, batched row writes, pause between batches (`EXPENSE_SHEET_BATCH_PAUSE_SECONDS`, default 1).

## Inbound (Sheet → SQL)

`expense-sheet-in-watcher` runs the queue worker and an HTTP webhook on port **9020** (configurable).

| Tab | SQL |
|---|---|
| `root` | ESL → `finance.expenses` / `finance.amex_landing` |
| `account_select` | `finance.expense_account_gl_display` |

Set in `secrets/.env`:

```env
EXPENSE_SHEET_INBOUND_SECRET=your-long-random-secret
```

Proxy `POST /api/expense-sheet/inbound` to `http://127.0.0.1:9020/api/expense-sheet/inbound` on the slot server (existing Cloudflare `/api/*` route), or point Apps Script at the Docker port directly during testing.

**Apps Script** (bound project `expense_sheet_tools`):

```bash
python3 scripts/push_expense_sheet_apps_script.py
```

In the spreadsheet: **Expense sync → Install inbound triggers** (once). Set script properties:

- `EXPENSE_SHEET_INBOUND_URL` — webhook URL
- `EXPENSE_SHEET_INBOUND_SECRET` — same value as `secrets/.env`

**Editable `root` columns:** Date, Amount, Comments, Description, State, Tribe, Casino, Expense Account. Card Member and Receipt are read-only. Casino edit updates tribe/state on the sheet (Apps Script) and in SQL (derived from casino FK). State/tribe-only edits clear casino when it no longer matches.
