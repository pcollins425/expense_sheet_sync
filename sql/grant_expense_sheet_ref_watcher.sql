-- Reference-tab watcher (SQL → Google Sheet): read clients.* + expense_account_gl_display.

USE [dgs_application_db];
GO

DECLARE @principals TABLE (name SYSNAME NOT NULL);
INSERT INTO @principals (name) VALUES (N'dgs_field_api'), (N'dashboard_perf_ro');

DECLARE @principal SYSNAME;
DECLARE @sql NVARCHAR(MAX);

DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM @principals;
OPEN c;
FETCH NEXT FROM c INTO @principal;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @principal)
    BEGIN
        SET @sql = N'
GRANT SELECT, UPDATE, DELETE ON [finance].[expense_sheet_out_queue] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [finance].[expense_account_gl_display] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [finance].[expense_supervisor_line] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[states] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[tribes] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT ON [clients].[casinos] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_out_by_gl_code] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_out_by_fk] TO [' + REPLACE(@principal, N']', N']]') + N'];';
        EXEC sp_executesql @sql;
        PRINT N'Granted SQL→Sheet ref watcher permissions to ' + @principal;
    END
    FETCH NEXT FROM c INTO @principal;
END
CLOSE c;
DEALLOCATE c;
GO
