"""Enqueue ESL sheet refresh after SQL reference changes."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def enqueue_by_fk(engine: Engine, column: str, reference_key: str) -> int:
    with engine.begin() as conn:
        conn.execute(
            text(
                "EXEC finance.usp_enqueue_expense_sheet_out_by_fk "
                "@column = :col, @reference_key = :ref"
            ),
            {"col": column, "ref": reference_key},
        )
        n = conn.execute(
            text(
                """
                SELECT COUNT(*) AS n
                FROM finance.expense_sheet_out_queue
                WHERE status = N'pending'
                  AND hub_reference_key IN (
                    SELECT reference_key FROM finance.expense_supervisor_line esl
                    WHERE (:col = N'state' AND esl.state_id = :ref)
                       OR (:col = N'tribe' AND esl.tribe_id = :ref)
                       OR (:col = N'casino' AND esl.casino_id = :ref)
                  )
                """
            ),
            {"col": column, "ref": reference_key},
        ).scalar()
    return int(n or 0)


def enqueue_by_gl_code(engine: Engine, gl_code: str) -> int:
    with engine.begin() as conn:
        conn.execute(
            text("EXEC finance.usp_enqueue_expense_sheet_out_by_gl_code @gl_code = :code"),
            {"code": gl_code},
        )
        n = conn.execute(
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
        ).scalar()
    return int(n or 0)
