import csv
import os

import polars as pl


def read_columns(file_path: str) -> list[str]:
    """
    Reads just the header row of an uploaded CSV/Excel file and returns the
    column names -- used right after upload to power the frontend's target
    column dropdown, before any Celery/Spark processing has started.

    Deliberately does not spin up a Spark session (overkill for reading one
    row) and, for CSV, deliberately does not ask Polars to scan/infer the
    file's schema -- both would mean touching more of a multi-GB upload than
    necessary just to list its columns.
    """
    extension = os.path.splitext(file_path)[1].lower()

    if extension in (".xlsx", ".xls"):
        # Excel files are always fully loaded into memory elsewhere in this
        # pipeline too (see the Excel->CSV conversion step in tasks.py), so
        # there's no lighter-weight read available here worth the extra
        # complexity -- these files are never the "millions of rows" case
        # PySpark is responsible for.
        return pl.read_excel(file_path).columns

    # CSV: read only the first physical line rather than letting Polars scan
    # the file, so this stays instant even for a multi-GB upload. Python's
    # csv module (not a naive `line.split(",")`) correctly handles a quoted
    # header value that itself contains a comma or newline.
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        first_line = f.readline()

    return next(csv.reader([first_line]))
