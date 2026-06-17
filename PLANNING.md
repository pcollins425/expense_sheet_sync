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

## Inbound (planned)

Apps Script → `POST https://api.collinsmediallc.com/api/expense-sheet/inbound` → `finance.expense_sheet_in_queue` → inbound worker. No new Cloudflare tunnel if path lives under existing `/api/*` route.
