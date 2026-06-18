-- Amex-only ESL rows: create finance.expenses (EXP-) once required allocation
-- fields are present on ESL. Partial sheet edits accumulate on ESL only.
--
-- Apply:
--   python3 scripts/run_mssql_sql_file.py scripts/migrations/2026-06-19_finance_expense_sheet_inbound_materialize_expense.sql

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER PROCEDURE finance.usp_try_materialize_expense_from_esl_amex
    @hub_key nvarchar(25),
    @update_by varchar(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @expense_id nvarchar(25),
        @amex_id nvarchar(25),
        @line_date date,
        @amount decimal(18, 2),
        @comments nvarchar(255),
        @description nvarchar(255),
        @state_id nvarchar(25),
        @tribe_id nvarchar(25),
        @casino_id nvarchar(25),
        @expense_account nvarchar(255),
        @employee_id nvarchar(50),
        @card_member nvarchar(75),
        @err nvarchar(4000);

    IF @hub_key IS NULL OR @hub_key NOT LIKE N'ESL-%'
        RETURN;

    SELECT
        @expense_id = esl.expense_id,
        @amex_id = esl.amex_id,
        @line_date = esl.line_date,
        @amount = esl.amount,
        @comments = esl.comments,
        @description = esl.description,
        @state_id = esl.state_id,
        @tribe_id = esl.tribe_id,
        @casino_id = esl.casino_id,
        @expense_account = esl.expense_account
    FROM finance.expense_supervisor_line esl
    WHERE esl.reference_key = @hub_key;

    IF @@ROWCOUNT = 0 OR @expense_id IS NOT NULL OR @amex_id IS NULL
        RETURN;

    -- Partial allocation: keep accumulating on ESL until all required expense fields exist.
    IF @state_id IS NULL
        OR @tribe_id IS NULL
        OR @casino_id IS NULL
        OR @line_date IS NULL
        OR @amount IS NULL
        RETURN;

    IF EXISTS (
        SELECT 1
        FROM finance.expenses ex
        WHERE ex.amex_id = @amex_id
           OR ex.reference_key = (
               SELECT al.expense_id
               FROM finance.amex_landing al
               WHERE al.reference_key = @amex_id
           )
    )
        RETURN;

    SELECT
        @card_member = al.card_member,
        @employee_id = (
            SELECT TOP (1) ca.employee_id
            FROM finance.card_accounts ca
            WHERE ca.name_on_card = al.card_member
              AND ca.active = 1
            ORDER BY ca.employee_id
        )
    FROM finance.amex_landing al
    WHERE al.reference_key = @amex_id;

    IF @employee_id IS NULL
    BEGIN
        SET @err = N'Cannot create expense for ' + @hub_key
            + N': no active card_accounts row for card member '
            + COALESCE(@card_member, N'(unknown)');
        THROW 51030, @err, 1;
    END

    EXEC sp_set_session_context N'SyncFromExpenseHub', NULL;

    INSERT INTO finance.expenses (
        date,
        employee_id,
        state_id,
        tribe_id,
        casino_id,
        amount,
        comments,
        description,
        expense_account,
        amex_id,
        update_by,
        change_log
    )
    VALUES (
        @line_date,
        @employee_id,
        @state_id,
        @tribe_id,
        @casino_id,
        @amount,
        @comments,
        @description,
        @expense_account,
        @amex_id,
        COALESCE(@update_by, N'expense_sheet_inbound'),
        N'Created from amex ESL allocation on ' + CONVERT(nvarchar(30), SYSUTCDATETIME(), 120)
    );

    EXEC sp_set_session_context N'SyncFromExpenseHub', 1;
END;
GO

GRANT EXECUTE ON [finance].[usp_try_materialize_expense_from_esl_amex] TO [dgs_field_api];
GRANT EXECUTE ON [finance].[usp_try_materialize_expense_from_esl_amex] TO [dashboard_perf_ro];
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
        @update_by varchar(50) = COALESCE(JSON_VALUE(@payload, N'$.update_by'), N'expense_sheet_inbound'),
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
        update_by = @update_by,
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
            update_by = @update_by
        FROM finance.expenses ex
        WHERE ex.reference_key = @expense_id;
    END
    ELSE IF @amex_id IS NOT NULL
    BEGIN
        EXEC finance.usp_try_materialize_expense_from_esl_amex
            @hub_key = @hub_key,
            @update_by = @update_by;

        SELECT @expense_id = esl.expense_id
        FROM finance.expense_supervisor_line esl
        WHERE esl.reference_key = @hub_key;

        IF @expense_id IS NULL
        BEGIN
            UPDATE al
            SET
                date = COALESCE(@line_date, al.date),
                amount = COALESCE(@amount, al.amount),
                description = COALESCE(@description, al.description),
                update_date = SYSUTCDATETIME(),
                update_by = @update_by
            FROM finance.amex_landing al
            WHERE al.reference_key = @amex_id;
        END
    END

    EXEC sp_set_session_context N'SyncFromSheet', NULL;
    EXEC sp_set_session_context N'SyncFromExpenseHub', NULL;
END;
GO

PRINT N'finance expense sheet inbound materialize-from-amex installed.';
GO
