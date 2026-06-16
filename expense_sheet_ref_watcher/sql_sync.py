"""Apply reference-tab diffs to SQL + fan-out sheet refresh."""
from __future__ import annotations

from sqlalchemy import text

from sheets_io import parse_gl_account_label, sheet_label, update_account_select_row


def sync_account_select_change(
    engine, service, gl_code: str, display_name: str, full_label: str
) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                MERGE finance.expense_account_gl_display AS tgt
                USING (SELECT :code AS gl_code, :name AS display_name) AS src
                ON tgt.gl_code = src.gl_code
                WHEN MATCHED AND tgt.display_name <> src.display_name THEN
                    UPDATE SET display_name = src.display_name
                WHEN NOT MATCHED THEN
                    INSERT (gl_code, display_name) VALUES (src.gl_code, src.display_name);
                """
            ),
            {"code": gl_code, "name": display_name},
        )
        conn.execute(
            text("EXEC finance.usp_enqueue_expense_sheet_out_by_gl_code @gl_code = :code"),
            {"code": gl_code},
        )
        r = conn.execute(
            text(
                """
                SELECT COUNT(*) AS n
                FROM finance.expense_sheet_out_queue
                WHERE status = N'pending'
                  AND hub_reference_key IN (
                    SELECT reference_key FROM finance.expense_supervisor_line esl
                    WHERE esl.expense_account LIKE :pfx
                       OR LEFT(LTRIM(RTRIM(esl.expense_account)), 4) = :code
                  )
                """
            ),
            {"pfx": f"{gl_code}%", "code": gl_code},
        )
        n = int(r.scalar() or 0)

    return n


def sync_root_expense_change(
    engine, service, esl_key: str, full_label: str
) -> bool:
    parsed = parse_gl_account_label(full_label)
    if parsed is None:
        return False
    gl_code, display_name = parsed
    canonical = sheet_label(gl_code, display_name)

    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT expense_id
                FROM finance.expense_supervisor_line
                WHERE reference_key = :k
                """
            ),
            {"k": esl_key},
        ).mappings().first()
        if not row or not row["expense_id"]:
            return False

        conn.execute(
            text(
                """
                MERGE finance.expense_account_gl_display AS tgt
                USING (SELECT :code AS gl_code, :name AS display_name) AS src
                ON tgt.gl_code = src.gl_code
                WHEN MATCHED AND tgt.display_name <> src.display_name THEN
                    UPDATE SET display_name = src.display_name
                WHEN NOT MATCHED THEN
                    INSERT (gl_code, display_name) VALUES (src.gl_code, src.display_name);
                """
            ),
            {"code": gl_code, "name": display_name},
        )
        conn.execute(
            text(
                """
                UPDATE finance.expenses
                SET
                    expense_account = :acct,
                    update_by = N'sheet_ref_watcher',
                    update_date = SYSUTCDATETIME()
                WHERE reference_key = :exp
                """
            ),
            {"acct": canonical, "exp": row["expense_id"]},
        )

    update_account_select_row(service, gl_code, canonical)
    return True


def sync_state_change(engine, ref_key: str, abbr: str, name: str) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE clients.states
                SET
                    state_abbreviation = NULLIF(:abbr, N''),
                    state = NULLIF(:name, N''),
                    update_date = SYSUTCDATETIME(),
                    update_by = N'sheet_ref_watcher'
                WHERE reference_key = :ref
                """
            ),
            {"ref": ref_key, "abbr": abbr, "name": name},
        )
        conn.execute(
            text(
                "EXEC finance.usp_enqueue_expense_sheet_out_by_fk "
                "@column = N'state', @reference_key = :ref"
            ),
            {"ref": ref_key},
        )
        r = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM finance.expense_sheet_out_queue
                WHERE status = N'pending'
                  AND hub_reference_key IN (
                    SELECT reference_key FROM finance.expense_supervisor_line
                    WHERE state_id = :ref
                  )
                """
            ),
            {"ref": ref_key},
        )
        return int(r.scalar() or 0)


def sync_tribe_change(
    engine, ref_key: str, tribe_name: str, tribe_short: str, state_id: str
) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE clients.tribes
                SET
                    tribe_name = NULLIF(:name, N''),
                    tribe_short = NULLIF(:short, N''),
                    state_id = NULLIF(:state_id, N''),
                    update_date = SYSUTCDATETIME(),
                    update_by = N'sheet_ref_watcher'
                WHERE reference_key = :ref
                """
            ),
            {
                "ref": ref_key,
                "name": tribe_name,
                "short": tribe_short,
                "state_id": state_id,
            },
        )
        conn.execute(
            text(
                "EXEC finance.usp_enqueue_expense_sheet_out_by_fk "
                "@column = N'tribe', @reference_key = :ref"
            ),
            {"ref": ref_key},
        )
        r = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM finance.expense_sheet_out_queue
                WHERE status = N'pending'
                  AND hub_reference_key IN (
                    SELECT reference_key FROM finance.expense_supervisor_line
                    WHERE tribe_id = :ref
                  )
                """
            ),
            {"ref": ref_key},
        )
        return int(r.scalar() or 0)


def sync_casino_change(
    engine,
    ref_key: str,
    casino_name: str,
    casino_short: str,
    tribe_id: str,
    state_id: str,
) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE clients.casinos
                SET
                    casino_name = NULLIF(:name, N''),
                    casino_short = NULLIF(:short, N''),
                    tribe_id = NULLIF(:tribe_id, N''),
                    state_id = NULLIF(:state_id, N''),
                    update_date = SYSUTCDATETIME(),
                    update_by = N'sheet_ref_watcher'
                WHERE reference_key = :ref
                """
            ),
            {
                "ref": ref_key,
                "name": casino_name,
                "short": casino_short,
                "tribe_id": tribe_id,
                "state_id": state_id,
            },
        )
        conn.execute(
            text(
                "EXEC finance.usp_enqueue_expense_sheet_out_by_fk "
                "@column = N'casino', @reference_key = :ref"
            ),
            {"ref": ref_key},
        )
        r = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM finance.expense_sheet_out_queue
                WHERE status = N'pending'
                  AND hub_reference_key IN (
                    SELECT reference_key FROM finance.expense_supervisor_line
                    WHERE casino_id = :ref
                  )
                """
            ),
            {"ref": ref_key},
        )
        return int(r.scalar() or 0)
