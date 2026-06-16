# Expense sheet sync — planning notes (2026-06-16 EOD)

**Status:** Planning only. Containers not turned back on yet.

## Agreed architecture direction

### Source of truth by data type

| Data | Source of truth | Sheet role |
|---|---|---|
| States, Tribes, Casinos | SQL (`clients.*`) | Validation tabs only |
| New GL accounts | **Supervisor on sheet** (`account_select`) | Personal control — not auto-inserted from SQL |
| Renamed GL | Supervisor edits sheet | Mass update on `root` |
| Expense rows | SQL (AppSheet → ESL) | `root` display; row-by-row outbound queue |

**Do not touch:** AppSheet tabs `expense_accounts`, `roles_groups` (ACL).

### Reference tab changes (SQL → sheet)

Ref watcher keeps **States / Tribes / Casinos** validation tabs in sync from SQL.

- **New reference row:** insert on validation tab only. Nothing on `root` until picked on an expense.
- **Renamed label:** one scoped **Sheets API `findReplace`** on the matching `root` column (`matchEntireCell: true`, single column). Payload = old text + new text. No ESL queue fan-out.

Columns on `root` (display):

- G — Tribe/Dynamic location  
- H — State  
- I — Casino/Dynamic location  
- J — Expense Account  

### Outbound watcher scope

- New/changed/deleted **expense lines** only (`finance.expense_sheet_out_queue` → `root` upsert).
- **Remove** ref-watcher fan-out (`usp_enqueue_expense_sheet_out_by_fk`, `by_gl_code`) when implementing above.

### GL accounts

Supervisor **personally adds** new GL rows on `account_select`. Inbound path (sheet → `finance.expense_account_gl_display`) is future work.

Ref watcher should **not** push new GL rows from SQL. Renames on sheet → find/replace on `root` column J.

### Apps Script

Optional, not required for ref renames if Docker calls native `findReplace` after updating validation tabs.

Apps Script still useful later for:

- Supervisor **onEdit** on `root` → validate → POST to DGS API (inbound)
- Manual menu: “Refresh root from references”

**No beforeEdit trigger** in Apps Script. External API writes do not fire `onEdit`. Web App POST is an option if sheet-side logic is preferred over Docker `findReplace`.

### Rate limits (implemented)

- Ref watcher: batched `batchUpdate`, 429 retry (`7b9bcb9`)
- Outbound watcher: one column-A read per queue drain, batched writes, 429 retry (`af74f50`)

### Session cleanup (2026-06-16)

Cleared `finance.expense_sheet_out_queue`: 2,282 rows (2,239 pending + 43 processing). Queue empty. ESL rows in SQL unchanged (4,399). Sheet may be stale until bootstrap when containers restart.

## Next implementation steps

1. Remove fan-out from `expense_sheet_ref_watcher/poll.py`
2. Add `findReplace` step after ref tab write (old/new label from snapshot diff)
3. Stop ref watcher syncing `account_select` from SQL (or make opt-in off)
4. Bootstrap outbound `root` once after deploy
5. Inbound: supervisor GL add + root edit write-back (separate phase)
