#!/usr/bin/env python3
"""Write the ATUS data in the common format (STANDARD.md §8).

Reads the four multi-year CSV files in data/raw/2003-2025/ (atusresp, atussum, atusact,
atuswgts) and writes data/processed/atus-2003-2025-<table>.parquet, holding the variables
this repo has records for. Each file is read back and every cell compared with the CSV,
so the conversion is lossless. Nothing here is shipped until the terms are decided.

Columns whose records have storage_type string (TRCODEP, TRTIER1P, TRTIER2P, TUSTARTTIM,
TUSTOPTIME) are read as text, so activity codes keep their leading zeros ("010101"):
pdt.readers.read_csv_zip would read them as numbers.

Run under the memory cap (CLAUDE.md); the activity file has 5 million rows.
"""

import io
import os
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

try:
    from pdt.release import data_source, write_release
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run through `make data`.")

ROOT = Path(__file__).resolve().parent.parent
# TABLES=respondent,activity builds only those tables (the others are skipped).
TABLES = [t for t in os.environ.get("TABLES", "").split(",") if t]


def text_columns(release, table):
    path = ROOT / "metadata" / "releases" / release / table / "variables.jsonl"
    return {r["name"] for r in map(json.loads, path.open()) if r.get("storage_type") == "string"}


def read(release, table, names):
    if TABLES and table not in TABLES:
        return None
    source = data_source(ROOT, release, table, format="csv")
    path = ROOT / source["path"]
    if not path.exists():
        sys.exit(f"{path} is missing; download it by hand (sources.yaml, manual_steps)")
    text = text_columns(release, table)
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.endswith(".dat"))
        with z.open(member) as f:
            frame = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), usecols=names,
                                dtype={n: str for n in names if n in text}, keep_default_na=False,
                                na_values={n: [""] for n in names})[names]
    return frame.astype(object).where(frame.notna(), None), source["id"]


if __name__ == "__main__":
    write_release(ROOT, read)
