-- Helpers for reference-tab watcher → outbound sheet refresh.

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER PROCEDURE finance.usp_enqueue_expense_sheet_out_refresh
    @hub_reference_key nvarchar(25)
AS
BEGIN
    SET NOCOUNT ON;

    IF NULLIF(LTRIM(RTRIM(@hub_reference_key)), N'') IS NULL
        RETURN;

    DELETE q
    FROM finance.expense_sheet_out_queue q
    WHERE q.hub_reference_key = @hub_reference_key
      AND q.status = N'pending';

    INSERT INTO finance.expense_sheet_out_queue (hub_reference_key, payload)
    SELECT
        esl.reference_key,
        (
            SELECT
                CAST(1 AS int) AS schema_version,
                CAST(N'finance.expense_supervisor_line' AS nvarchar(50)) AS [source],
                CAST(N'expense_sheet_out_queue' AS nvarchar(40)) AS [queue],
                esl.reference_key AS hub_reference_key,
                CAST(N'update' AS nvarchar(10)) AS [op],
                esl.expense_id,
                esl.amex_id,
                esl.line_date,
                esl.card_member,
                esl.amount,
                esl.comments,
                esl.description,
                esl.tribe_id,
                esl.state_id,
                esl.casino_id,
                esl.expense_account,
                esl.receipt,
                esl.update_by,
                esl.update_date
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        )
    FROM finance.expense_supervisor_line esl
    WHERE esl.reference_key = @hub_reference_key;
END;
GO

CREATE OR ALTER PROCEDURE finance.usp_enqueue_expense_sheet_out_by_gl_code
    @gl_code varchar(16)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @code varchar(16) = NULLIF(LTRIM(RTRIM(@gl_code)), '');

    IF @code IS NULL
        RETURN;

    DELETE q
    FROM finance.expense_sheet_out_queue q
    INNER JOIN finance.expense_supervisor_line esl
        ON esl.reference_key = q.hub_reference_key
    WHERE q.status = N'pending'
      AND (
            esl.expense_account LIKE @code + N' %'
         OR esl.expense_account LIKE @code + N'-%'
         OR LEFT(LTRIM(RTRIM(esl.expense_account)), 4) = @code
      );

    INSERT INTO finance.expense_sheet_out_queue (hub_reference_key, payload)
    SELECT
        esl.reference_key,
        (
            SELECT
                CAST(1 AS int) AS schema_version,
                CAST(N'finance.expense_supervisor_line' AS nvarchar(50)) AS [source],
                CAST(N'expense_sheet_out_queue' AS nvarchar(40)) AS [queue],
                esl.reference_key AS hub_reference_key,
                CAST(N'update' AS nvarchar(10)) AS [op],
                esl.expense_id,
                esl.amex_id,
                esl.line_date,
                esl.card_member,
                esl.amount,
                esl.comments,
                esl.description,
                esl.tribe_id,
                esl.state_id,
                esl.casino_id,
                esl.expense_account,
                esl.receipt,
                esl.update_by,
                esl.update_date
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        )
    FROM finance.expense_supervisor_line esl
    WHERE esl.expense_account LIKE @code + N' %'
       OR esl.expense_account LIKE @code + N'-%'
       OR LEFT(LTRIM(RTRIM(esl.expense_account)), 4) = @code;
END;
GO

CREATE OR ALTER PROCEDURE finance.usp_enqueue_expense_sheet_out_by_fk
    @column nvarchar(20),
    @reference_key nvarchar(25)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @ref nvarchar(25) = NULLIF(LTRIM(RTRIM(@reference_key)), N'');

    IF @ref IS NULL
        RETURN;

    DELETE q
    FROM finance.expense_sheet_out_queue q
    INNER JOIN finance.expense_supervisor_line esl
        ON esl.reference_key = q.hub_reference_key
    WHERE q.status = N'pending'
      AND (
            (@column = N'state' AND esl.state_id = @ref)
         OR (@column = N'tribe' AND esl.tribe_id = @ref)
         OR (@column = N'casino' AND esl.casino_id = @ref)
      );

    INSERT INTO finance.expense_sheet_out_queue (hub_reference_key, payload)
    SELECT
        esl.reference_key,
        (
            SELECT
                CAST(1 AS int) AS schema_version,
                CAST(N'finance.expense_supervisor_line' AS nvarchar(50)) AS [source],
                CAST(N'expense_sheet_out_queue' AS nvarchar(40)) AS [queue],
                esl.reference_key AS hub_reference_key,
                CAST(N'update' AS nvarchar(10)) AS [op],
                esl.expense_id,
                esl.amex_id,
                esl.line_date,
                esl.card_member,
                esl.amount,
                esl.comments,
                esl.description,
                esl.tribe_id,
                esl.state_id,
                esl.casino_id,
                esl.expense_account,
                esl.receipt,
                esl.update_by,
                esl.update_date
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        )
    FROM finance.expense_supervisor_line esl
    WHERE (@column = N'state' AND esl.state_id = @ref)
       OR (@column = N'tribe' AND esl.tribe_id = @ref)
       OR (@column = N'casino' AND esl.casino_id = @ref);
END;
GO

PRINT N'finance.usp_enqueue_expense_sheet_out_* refresh helpers installed.';
GO
