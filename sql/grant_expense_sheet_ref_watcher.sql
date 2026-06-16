-- Reference-tab sheet watcher (account_select, States, Tribes, Casinos, root expense account).

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
GRANT SELECT ON [finance].[vw_expense_supervisor_sheet] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [finance].[expense_account_gl_display] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [finance].[expenses] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [finance].[expense_supervisor_line] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [clients].[states] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [clients].[tribes] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT SELECT, UPDATE ON [clients].[casinos] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_out_refresh] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_out_by_gl_code] TO [' + REPLACE(@principal, N']', N']]') + N'];
GRANT EXECUTE ON [finance].[usp_enqueue_expense_sheet_out_by_fk] TO [' + REPLACE(@principal, N']', N']]') + N'];';
        EXEC sp_executesql @sql;
        PRINT N'Granted expense sheet ref watcher permissions to ' + @principal;
    END
    FETCH NEXT FROM c INTO @principal;
END
CLOSE c;
DEALLOCATE c;
GO
