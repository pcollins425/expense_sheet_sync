# Expense sheet sync — planning notes

**Status:** Implemented in repo (2026-06-17). Safe to redeploy after `git pull` + rebuild.

## Architecture

| Data | Source | Sheet update |
|---|---|---|
| States, Tribes, Casinos | SQL → validation tabs | Ref watcher |
| Renamed label on those | SQL diff | `findReplace` on root col G/H/I (whole cell) |
| New GL | Supervisor on sheet | Not ref watcher |
| Expense rows | SQL queue | Outbound watcher only |

**Removed:** ESL queue fan-out on reference change (was 2k+ API calls).

## Deploy

```bash
cd expense_sheet_sync
git pull
docker compose build --no-cache
docker compose up -d

# First time or reset snapshots:
docker compose run --rm expense-sheet-ref-watcher python -u run.py --bootstrap
# root already has rows; optional:
docker compose run --rm expense-sheet-out-watcher python -u run.py --bootstrap
```

Ensure `secrets/.env` has updated `GMAIL_*` with Apps Script scopes if using sheet tools from host.

## Inbound (implemented 2026-06-18)

Apps Script `onInboundEdit` → `POST /api/expense-sheet/inbound` (or Docker `:9020`) → `finance.expense_sheet_in_queue` → `expense-sheet-in-watcher`.

| Tab | SQL target |
|---|---|
| `root` | ESL → `finance.expenses` / `finance.amex_landing` |
| `account_select` | `finance.expense_account_gl_display` |

**Editable on `root`:** Date, Amount, Comments, Description, State, Tribe, Casino, Expense Account (not Card Member / Receipt).

**Casino edit:** SQL derives tribe + state from casino; Apps Script cascades G/H on sheet. State/tribe-only edit clears casino when invalid (Option A).

```bash
python3 scripts/run_mssql_sql_file.py scripts/migrations/2026-06-18_finance_expense_sheet_inbound.sql
python3 scripts/run_mssql_sql_file.py scripts/sql/grant_expense_sheet_in_watcher.sql
python3 scripts/push_expense_sheet_apps_script.py
```

Set `EXPENSE_SHEET_INBOUND_SECRET` in `secrets/.env` and Apps Script project properties (`EXPENSE_SHEET_INBOUND_URL`, `EXPENSE_SHEET_INBOUND_SECRET`). Run **Expense sync → Install inbound triggers** once on the sheet.

**Public URL (preferred):** dedicated hostname `expense-inbound.collinsmediallc.com` → `:9020` (not path routing on `api`). See `agents/knowledge/finance_expense_supervisor_line.md` § Cloudflare.
