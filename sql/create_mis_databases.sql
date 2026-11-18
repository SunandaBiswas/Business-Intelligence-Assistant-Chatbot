/* ==========================================================
   Create one database per top-level folder in
   SharePoint: MIS > Documents (greendelta12.sharepoint.com/sites/mis)
   Safe to re-run: each database is created only if it doesn't exist.
   Run in SSMS: File > Open > this file, connect to your server, press F5.
   ========================================================== */
USE master;
GO

DECLARE @dbs TABLE (name SYSNAME, sharepoint_folder NVARCHAR(200));
INSERT INTO @dbs (name, sharepoint_folder) VALUES
 (N'Annual_Business_Conference_Slides', N'Annual Business Conference Slides'),
 (N'Campaign',                          N'Campaign'),
 (N'CR_Merged_OLD_NEW_CIS',             N'CR_Merged_OLD_NEW_CIS'),
 (N'Customer_List',                     N'Customer List'),
 (N'Digital',                           N'Digital'),
 (N'Employee_Data',                     N'Employee Data'),
 (N'External_Communications',           N'External Communications'),
 (N'General',                           N'General'),
 (N'Old_Registers',                     N'Old Registers'),
 (N'Power_BI_Datasets',                 N'Power BI Datasets'),
 (N'Profit_and_Loss_Statement',         N'Profit and Loss Statement'),
 (N'SQL_Queries',                       N'SQL Queries'),
 (N'Working_Folder',                    N'Working Folder');

DECLARE @name SYSNAME, @sql NVARCHAR(MAX);
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM @dbs;
OPEN c;
FETCH NEXT FROM c INTO @name;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF DB_ID(@name) IS NULL
    BEGIN
        SET @sql = N'CREATE DATABASE ' + QUOTENAME(@name) + N';';
        EXEC (@sql);
        PRINT N'Created: ' + @name;
    END
    ELSE
        PRINT N'Already exists: ' + @name;
    FETCH NEXT FROM c INTO @name;
END
CLOSE c; DEALLOCATE c;
GO

/* Check the result */
SELECT name, create_date
FROM sys.databases
WHERE name IN (N'Annual_Business_Conference_Slides', N'Campaign', N'CR_Merged_OLD_NEW_CIS',
               N'Customer_List', N'Digital', N'Employee_Data', N'External_Communications',
               N'General', N'Old_Registers', N'Power_BI_Datasets',
               N'Profit_and_Loss_Statement', N'SQL_Queries', N'Working_Folder')
ORDER BY name;
GO
