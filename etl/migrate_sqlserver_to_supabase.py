"""
One-off copy of the Register database from local SQL Server (localhost\\SQLEXPRESS) into Supabase.

Needs:  pip install pyodbc "psycopg[binary]" pandas sqlalchemy python-dotenv
        SUPABASE_DB_URL set in the .env file

Run:    python etl/migrate_sqlserver_to_supabase.py            # copy everything not yet copied
        python etl/migrate_sqlserver_to_supabase.py --full     # re-copy every table
        python etl/migrate_sqlserver_to_supabase.py --only PBI_Collection_Register

Re-running is safe: a table whose row count already matches in Supabase is skipped.
Column types are mapped: date/datetime -> timestamp, integers -> bigint, decimals/floats -> double
precision, everything else -> text.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import pyodbc
from sqlalchemy import create_engine, text
from sqlalchemy.types import BigInteger, DateTime, Float, Text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db_connector import ensure_setup, get_engine, qi  # noqa: E402

MAX_IDENT = 63
CHUNK = 20_000
DATE_T = {"date", "datetime", "datetime2", "smalldatetime"}
INT_T = {"bigint", "int", "smallint", "tinyint"}
FLOAT_T = {"float", "real", "decimal", "numeric", "money", "smallmoney"}


def sqlserver_engine(server, database):
    driver = next((d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
                   if d in pyodbc.drivers()), None)
    if not driver:
        raise SystemExit(f"No SQL Server ODBC driver found. Installed: {pyodbc.drivers()}")
    cs = (f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
          "Trusted_Connection=yes;TrustServerCertificate=yes")
    return create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(cs))


def pg_type(sql_type):
    t = sql_type.lower()
    return DateTime() if t in DATE_T else BigInteger() if t in INT_T else Float() if t in FLOAT_T else Text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=r"localhost\SQLEXPRESS")
    ap.add_argument("--database", default="Register")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--only", nargs="*", help="copy just these table names")
    args = ap.parse_args()

    src, dst = sqlserver_engine(args.server, args.database), get_engine()
    ensure_setup(dst)

    with src.connect() as c:
        cat = pd.read_sql(text("SELECT * FROM dbo._catalog"), c)
    todo = cat[cat["status"] == "ok"]
    if args.only:
        todo = todo[todo["table_name"].isin(args.only)]
    print(f"{len(todo)} tables to consider")

    for _, row in todo.iterrows():
        name = row["table_name"][:MAX_IDENT]
        if not args.full:
            with dst.connect() as c:
                exists = c.exec_driver_sql("SELECT to_regclass(%s)", (f"public.{qi(name)}",)).scalar()
                have = c.exec_driver_sql(f"SELECT COUNT(*) FROM {qi(name)}").scalar() if exists else None
            if have is not None and have == row["row_count"]:
                print(f"  = {name}: already there ({have:,} rows)")
                continue
        with src.connect() as c:
            cols = c.exec_driver_sql(
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                (row["table_name"],)).fetchall()
        dtype = {c: pg_type(t) for c, t in cols}
        names = [c for c, _ in cols]
        total = 0
        try:
            with src.connect() as c:
                chunks = pd.read_sql(text(f"SELECT * FROM dbo.[{row['table_name']}]"), c, chunksize=CHUNK)
                first = True
                for df in chunks:
                    df.columns = [str(x)[:MAX_IDENT] for x in df.columns]
                    df = df.astype(object).where(df.notna(), None)
                    df.to_sql(name, dst, schema="public", if_exists="replace" if first else "append",
                              index=False, chunksize=2_000, method="multi",
                              dtype={k[:MAX_IDENT]: v for k, v in dtype.items()} if first else None)
                    first = False
                    total += len(df)
                    print(f"    {name}: {total:,} rows...", end="\r")
                if first:                                     # table exists but has no rows
                    pd.DataFrame(columns=[n[:MAX_IDENT] for n in names]).to_sql(
                        name, dst, schema="public", if_exists="replace", index=False,
                        dtype={k[:MAX_IDENT]: v for k, v in dtype.items()})
            with dst.begin() as c:
                c.exec_driver_sql("DELETE FROM public._catalog WHERE table_name = %s", (name,))
                c.exec_driver_sql(
                    "INSERT INTO public._catalog (table_name, source_path, sheet_name, file_mtime, row_count,"
                    " column_count, status, message, loaded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (name, row["source_path"], row["sheet_name"],
                     None if pd.isna(row["file_mtime"]) else row["file_mtime"].to_pydatetime(),
                     total, int(row["column_count"]), "ok", row["message"],
                     datetime.now() if pd.isna(row["loaded_at"]) else row["loaded_at"].to_pydatetime()))
            print(f"  + {name}: {total:,} rows")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name}: FAILED {e!r}"[:300])


if __name__ == "__main__":
    main()
