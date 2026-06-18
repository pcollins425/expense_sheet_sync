/*
  expense_sheet_in_watcher + inbound webhook — queue drain + apply procs.

  Run with privileged login on dgs_application_db:
    python3 scripts/run_mssql_sql_file.py scripts/sql/grant_expense_sheet_in_watcher.sql
*/
USE [dgs_application_db];
GO

DECLARE @principals TABLE (name SYSNAME NOT NULL);
INSERT INTO @principals (name) VALUES
    (N'dgs_field_api'),
    (N'dashboard_perf_ro');

DECLARE @principal SYSNAME;
DECLARE @sql NVARCHAR(MAX);

DECLARE c CURSOR LOCAL FAST_FORWARD FOR
    SELECT name FROM @principals;

OPEN c;
FETCH NEXT FROM c INTO @principal;

WHILE @@FETCH_STATUS = 0
BEGIN
    IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @principal)
    BEGIN
        SET @sql = N'
GRANT SELECT, INSERT, UPDATE, DELETE ON [finance].[expense_sheet_in_queue] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [finance].[expense_supervisor_line] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [finance].[expenses] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [finance].[amex_landing] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, INSERT, UPDATE ON [finance].[expense_account_gl_display] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[states] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[tribes] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[casinos] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_in] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_apply_expense_sheet_inbound] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_apply_expense_account_select_inbound] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_try_materialize_expense_from_esl_amex] TO [' + REPLACE(@principal, N']', N']]') + N'];';
        EXEC sp_executesql @sql;
        PRINT N'Granted expense sheet inbound permissions to ' + @principal;
    END
    ELSE
        PRINT N'Skipped (user not found): ' + @principal;

    FETCH NEXT FROM c INTO @principal;
END

CLOSE c;
DEALLOCATE c;
GO
