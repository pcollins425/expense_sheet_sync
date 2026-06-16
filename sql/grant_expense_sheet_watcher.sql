/*
  expense_sheet_out_watcher (Docker) — queue drain + sheet read view.

  Grants to common service logins used as MSSQL_USER in deploy/expense_sheet_sync/secrets/.env.
  Edit @principals below if your watcher uses a different database user.

  Run with privileged login on dgs_application_db:
    python3 scripts/run_mssql_sql_file.py scripts/sql/grant_expense_sheet_watcher.sql
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
GRANT SELECT, UPDATE, DELETE ON [finance].[expense_sheet_out_queue] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [finance].[vw_expense_supervisor_sheet] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [finance].[expense_supervisor_line] TO [' + REPLACE(@principal, N']', N']]') + N'];';
        EXEC sp_executesql @sql;
        PRINT N'Granted expense sheet watcher permissions to ' + @principal;
    END
    ELSE
        PRINT N'Skipped (user not found): ' + @principal;

    FETCH NEXT FROM c INTO @principal;
END

CLOSE c;
DEALLOCATE c;
GO
