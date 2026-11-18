"""
Simple version: load MIS register Excel/CSV files into SQL Server database [Register].
One table per sheet (Excel) or per file (CSV). Existing tables are replaced.

Install once (in VS Code terminal, inside your .venv):
    pip install pandas sqlalchemy pyodbc python-calamine openpyxl
Run:
    python etl\\load_register_simple.py
"""
import re
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import pyodbc
from sqlalchemy import create_engine

# ---- settings -------------------------------------------------------------
SERVER = r"localhost\SQLEXPRESS"
DATABASE = "Register"
MIS = Path.home() / r"GDIC\OneDrive - Green Delta Insurance PLC\Shortcuts\MIS - Documents"
FOLDERS = {"Power BI Datasets": "PBI", "Old Registers": "OLD", "CR_Merged_OLD_NEW_CIS": "CR"}
DRIVER = "ODBC Driver 17 for SQL Server"   # check with: print(pyodbc.drivers())


def conn_str(db):
    return (f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={db};"
            "Trusted_Connection=yes;TrustServerCertificate=yes")


def clean(name):
    return re.sub(r"_+", "_", re.sub(r"[^0-9A-Za-z]+", "_", str(name))).strip("_")[:100]


# ---- 1. create the database if it doesn't exist ---------------------------
with pyodbc.connect(conn_str("master"), autocommit=True) as cn:
    cn.execute(f"IF DB_ID('{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")

engine = create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(conn_str(DATABASE)),
                       fast_executemany=True)

# ---- 2. load every Excel sheet / CSV file ---------------------------------
for folder, prefix in FOLDERS.items():
    for f in sorted((MIS / folder).iterdir()):
        ext = f.suffix.lower()
        if f.name.startswith("~$") or ext not in (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv"):
            continue
        print(f"\n{folder}/{f.name}")
        try:
            if ext == ".csv":
                table = f"{prefix}_{clean(f.stem)}"
                first = True
                for chunk in pd.read_csv(f, chunksize=100_000, low_memory=False,
                                         encoding_errors="replace"):
                    chunk.columns = [clean(c) or f"col_{i}" for i, c in enumerate(chunk.columns)]
                    chunk.to_sql(table, engine, if_exists="replace" if first else "append",
                                 index=False, chunksize=5_000)
                    first = False
                print(f"   -> {table}")
            else:
                sheets = pd.read_excel(f, sheet_name=None, engine="calamine")
                for sheet, df in sheets.items():
                    df = df.dropna(how="all").dropna(axis=1, how="all")
                    if df.empty:
                        continue
                    df.columns = [clean(c) or f"col_{i}" for i, c in enumerate(df.columns)]
                    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
                    table = f"{prefix}_{clean(f.stem)}"
                    if len(sheets) > 1:
                        table += f"__{clean(sheet)[:40]}"
                    df.to_sql(table[:128], engine, if_exists="replace", index=False, chunksize=5_000)
                    print(f"   -> {table[:128]}  ({len(df):,} rows)")
        except Exception as e:
            print(f"   !! skipped: {e}")

print("\nDone. In SSMS: Register > Tables > right-click > Refresh")
