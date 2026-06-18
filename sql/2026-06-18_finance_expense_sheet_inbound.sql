-- Sheet → SQL inbound: apply procs for expense_sheet_in_queue worker.
--
-- Apply:
--   python3 scripts/run_mssql_sql_file.py scripts/migrations/2026-06-18_finance_expense_sheet_inbound.sql

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER FUNCTION finance.fn_parse_expense_account_gl_code (@label nvarchar(255))
RETURNS varchar(16)
AS
BEGIN
    DECLARE @t nvarchar(255) = NULLIF(LTRIM(RTRIM(@label)), N'');
    IF @t IS NULL
        RETURN NULL;

    IF PATINDEX(N'[0-9][0-9][0-9][0-9]%', @t) = 1
        RETURN SUBSTRING(@t, 1, 4);

    IF CHARINDEX(N' -', @t + N' -') > 1
        RETURN NULLIF(
            LTRIM(RTRIM(LEFT(@t, CHARINDEX(N' -', @t + N' -') - 1))),
            N''
        );

    RETURN NULL;
END;
GO

CREATE OR ALTER PROCEDURE finance.usp_enqueue_expense_sheet_in
    @payload nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @hub_key nvarchar(25) = JSON_VALUE(@payload, N'$.hub_reference_key');
    DECLARE @source nvarchar(40) = COALESCE(JSON_VALUE(@payload, N'$.source'), N'root');

    IF @source = N'root'
    BEGIN
        IF @hub_key IS NULL OR @hub_key NOT LIKE N'ESL-%'
            THROW 51001, N'root inbound payload requires hub_reference_key ESL-*', 1;
    END
    ELSE IF @source = N'account_select'
    BEGIN
        SET @hub_key = COALESCE(
            @hub_key,
            N'GL-' + JSON_VALUE(@payload, N'$.gl_code')
        );
        IF @hub_key IS NULL OR JSON_VALUE(@payload, N'$.gl_code') IS NULL
            THROW 51002, N'account_select inbound payload requires gl_code', 1;
    END
    ELSE
        THROW 51003, N'Unknown inbound source', 1;

    DELETE q
    FROM finance.expense_sheet_in_queue q
    WHERE q.hub_reference_key = @hub_key
      AND q.status = N'pending';

    INSERT INTO finance.expense_sheet_in_queue (hub_reference_key, payload)
    VALUES (@hub_key, @payload);
END;
GO

CREATE OR ALTER PROCEDURE finance.usp_apply_expense_account_select_inbound
    @gl_code varchar(16),
    @display_name nvarchar(512)
AS
BEGIN
    SET NOCOUNT ON;

    IF @gl_code IS NULL OR LTRIM(RTRIM(@gl_code)) = N''
        THROW 51010, N'gl_code is required', 1;

    IF @display_name IS NULL OR LTRIM(RTRIM(@display_name)) = N''
        THROW 51011, N'display_name is required', 1;

    MERGE finance.expense_account_gl_display AS tgt
    USING (
        SELECT
            LTRIM(RTRIM(@gl_code)) AS gl_code,
            LTRIM(RTRIM(@display_name)) AS display_name
    ) AS src
    ON tgt.gl_code = src.gl_code
    WHEN MATCHED AND tgt.display_name <> src.display_name THEN
        UPDATE SET display_name = src.display_name
    WHEN NOT MATCHED THEN
        INSERT (gl_code, display_name) VALUES (src.gl_code, src.display_name);
END;
GO

CREATE OR ALTER PROCEDURE finance.usp_apply_expense_sheet_inbound
    @payload nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @hub_key nvarchar(25) = JSON_VALUE(@payload, N'$.hub_reference_key'),
        @line_date date,
        @amount decimal(18, 2),
        @comments nvarchar(255),
        @description nvarchar(255),
        @state_label nvarchar(100),
        @tribe_label nvarchar(255),
        @casino_label nvarchar(255),
        @expense_account_label nvarchar(255),
        @state_id nvarchar(25),
        @tribe_id nvarchar(25),
        @casino_id nvarchar(25),
        @final_state_id nvarchar(25),
        @final_tribe_id nvarchar(25),
        @final_casino_id nvarchar(25),
        @resolved_casino_id nvarchar(25),
        @resolved_tribe_id nvarchar(25),
        @resolved_state_id nvarchar(25),
        @gl_code varchar(16),
        @expense_account nvarchar(255),
        @expense_id nvarchar(25),
        @amex_id nvarchar(25),
        @current_state_id nvarchar(25),
        @current_tribe_id nvarchar(25),
        @current_casino_id nvarchar(25),
        @casino_in_payload bit = 0,
        @err nvarchar(4000);

    IF @hub_key IS NULL OR @hub_key NOT LIKE N'ESL-%'
        THROW 51020, N'hub_reference_key ESL-* is required', 1;

    SELECT
        @expense_id = esl.expense_id,
        @amex_id = esl.amex_id,
        @current_state_id = esl.state_id,
        @current_tribe_id = esl.tribe_id,
        @current_casino_id = esl.casino_id
    FROM finance.expense_supervisor_line esl
    WHERE esl.reference_key = @hub_key;

    IF @@ROWCOUNT = 0
        THROW 51021, N'ESL row not found', 1;

    SET @line_date = TRY_CONVERT(date, JSON_VALUE(@payload, N'$.fields.date'));
    SET @amount = TRY_CONVERT(decimal(18, 2), JSON_VALUE(@payload, N'$.fields.amount'));
    SET @comments = NULLIF(LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.comments'))), N'');
    SET @description = NULLIF(LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.description'))), N'');
    SET @state_label = NULLIF(LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.state'))), N'');
    SET @tribe_label = NULLIF(LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.tribe'))), N'');
    SET @casino_label = NULLIF(LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.casino'))), N'');
    SET @expense_account_label = NULLIF(
        LTRIM(RTRIM(JSON_VALUE(@payload, N'$.fields.expense_account'))),
        N''
    );

    IF JSON_VALUE(@payload, N'$.fields.casino') IS NOT NULL
        SET @casino_in_payload = 1;

    IF @state_label IS NOT NULL
    BEGIN
        SELECT TOP (1) @state_id = s.reference_key
        FROM clients.states s
        WHERE s.state_abbreviation = @state_label
           OR s.state = @state_label
        ORDER BY CASE WHEN s.state_abbreviation = @state_label THEN 0 ELSE 1 END;

        IF @state_id IS NULL
        BEGIN
            SET @err = N'Unknown state label: ' + @state_label;
            THROW 51022, @err, 1;
        END
    END

    IF @tribe_label IS NOT NULL
    BEGIN
        SELECT TOP (1) @tribe_id = t.reference_key
        FROM clients.tribes t
        WHERE t.tribe_name = @tribe_label
           OR t.tribe_short = @tribe_label
        ORDER BY CASE WHEN t.tribe_name = @tribe_label THEN 0 ELSE 1 END;

        IF @tribe_id IS NULL
        BEGIN
            SET @err = N'Unknown tribe label: ' + @tribe_label;
            THROW 51023, @err, 1;
        END
    END

    IF @casino_label IS NOT NULL
    BEGIN
        SELECT TOP (1)
            @resolved_casino_id = c.reference_key,
            @resolved_tribe_id = c.tribe_id,
            @resolved_state_id = c.state_id
        FROM clients.casinos c
        WHERE c.casino_name = @casino_label
           OR c.casino_short = @casino_label
        ORDER BY CASE WHEN c.casino_name = @casino_label THEN 0 ELSE 1 END;

        IF @resolved_casino_id IS NULL
        BEGIN
            SET @err = N'Unknown casino label: ' + @casino_label;
            THROW 51024, @err, 1;
        END

        SET @casino_id = @resolved_casino_id;
        SET @tribe_id = @resolved_tribe_id;
        SET @state_id = @resolved_state_id;
    END
    ELSE IF @casino_in_payload = 1
    BEGIN
        SET @casino_id = NULL;
    END

    SET @final_state_id = COALESCE(@state_id, @current_state_id);
    SET @final_tribe_id = COALESCE(@tribe_id, @current_tribe_id);

    IF @casino_in_payload = 1
        SET @final_casino_id = @casino_id;
    ELSE
        SET @final_casino_id = @current_casino_id;

    IF @final_casino_id IS NOT NULL
       AND (
            (@final_tribe_id IS NOT NULL AND EXISTS (
                SELECT 1
                FROM clients.casinos c
                WHERE c.reference_key = @final_casino_id
                  AND c.tribe_id <> @final_tribe_id
            ))
            OR (@final_state_id IS NOT NULL AND EXISTS (
                SELECT 1
                FROM clients.casinos c
                WHERE c.reference_key = @final_casino_id
                  AND c.state_id <> @final_state_id
            ))
       )
    BEGIN
        SET @final_casino_id = NULL;
    END

    IF @expense_account_label IS NOT NULL
    BEGIN
        SET @gl_code = finance.fn_parse_expense_account_gl_code(@expense_account_label);
        IF @gl_code IS NULL
            THROW 51025, N'Could not parse gl_code from expense account label', 1;

        IF NOT EXISTS (
            SELECT 1
            FROM finance.expense_account_gl_display ead
            WHERE ead.gl_code = @gl_code
        )
        BEGIN
            SET @err = N'Unknown GL code: ' + @gl_code;
            THROW 51026, @err, 1;
        END

        SELECT @expense_account = finance.fn_expense_account_sheet_label(
            ead.gl_code,
            ead.display_name
        )
        FROM finance.expense_account_gl_display ead
        WHERE ead.gl_code = @gl_code;
    END

    EXEC sp_set_session_context N'SyncFromSheet', 1;
    EXEC sp_set_session_context N'SyncFromExpenseHub', 1;

    UPDATE esl
    SET
        line_date = COALESCE(@line_date, esl.line_date),
        amount = COALESCE(@amount, esl.amount),
        comments = COALESCE(@comments, esl.comments),
        description = COALESCE(@description, esl.description),
        state_id = @final_state_id,
        tribe_id = @final_tribe_id,
        casino_id = @final_casino_id,
        expense_account = COALESCE(@expense_account, esl.expense_account),
        update_date = SYSUTCDATETIME(),
        update_by = COALESCE(JSON_VALUE(@payload, N'$.update_by'), N'expense_sheet_inbound'),
        change_log = N'Synced from sheet on ' + CONVERT(nvarchar(30), SYSUTCDATETIME(), 120)
    FROM finance.expense_supervisor_line esl
    WHERE esl.reference_key = @hub_key;

    IF @expense_id IS NOT NULL
    BEGIN
        UPDATE ex
        SET
            date = COALESCE(@line_date, ex.date),
            amount = COALESCE(@amount, ex.amount),
            comments = COALESCE(@comments, ex.comments),
            description = COALESCE(@description, ex.description),
            state_id = @final_state_id,
            tribe_id = @final_tribe_id,
            casino_id = @final_casino_id,
            expense_account = COALESCE(@expense_account, ex.expense_account),
            update_date = SYSUTCDATETIME(),
            update_by = COALESCE(JSON_VALUE(@payload, N'$.update_by'), N'expense_sheet_inbound')
        FROM finance.expenses ex
        WHERE ex.reference_key = @expense_id;
    END
    ELSE IF @amex_id IS NOT NULL
    BEGIN
        UPDATE al
        SET
            date = COALESCE(@line_date, al.date),
            amount = COALESCE(@amount, al.amount),
            description = COALESCE(@description, al.description),
            update_date = SYSUTCDATETIME(),
            update_by = COALESCE(JSON_VALUE(@payload, N'$.update_by'), N'expense_sheet_inbound')
        FROM finance.amex_landing al
        WHERE al.reference_key = @amex_id;
    END

    EXEC sp_set_session_context N'SyncFromSheet', NULL;
    EXEC sp_set_session_context N'SyncFromExpenseHub', NULL;
END;
GO

PRINT N'finance expense sheet inbound apply objects installed.';
GO
