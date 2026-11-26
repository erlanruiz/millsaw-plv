"""
Read mill specification xlsx workbooks (one CHOP SAW cut table per sheet).

Each sheet may contain MULTIPLE station tables stacked vertically
(CHOP SAW, then RIP SAW, then BAND SAW, etc.). We extract only the
first CHOP SAW table on each sheet and stop reading at the boundary
of the next station section, so we don't accidentally double-count
qty values that are repeated in adjacent station tables.

Layout (verified against 446 MILL SPECS / 039 Mill Specs):
  Row 1  col G  : "<Company> Mill Specification Sheet"  (repeats for each station)
  Row 4  col A  : "MILL #" label
  Row 5  col A  : MILL # value
  Row 4  col L  : "STYLE" label
  Row 5  col L  : STYLE value
  Row 6  col U  : "DUE DATE" label
  Row 7  col S  : DUE DATE value (datetime)
  Row 6  col AI : "MILL STATION" label
  Row 7  col AI : station name (CHOP SAW / RIP SAW / BAND SAW / ...)
  Row 11 col AG : data starts here for the section
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Tuple

import openpyxl  # type: ignore


WIDTH_COL = 33   # AG
LENGTH_COL = 36  # AJ
QTY_COL = 39     # AM
STATION_COL = 35  # AI

# Other station names we should treat as "stop reading here".
KNOWN_STATIONS = {
    "CHOP SAW", "RIP SAW", "BAND SAW", "ROUTER",
    "DRILL", "PLANER", "OPTICUT", "JOINER", "SLED",
}


@dataclass
class CutRow:
    width: float
    length: float
    qty: int

    def length_mm(self) -> float:
        return round(self.length * 25.4, 2)


@dataclass
class ChopSawTable:
    sheet_name: str
    mill_number: str
    style: str
    due_date: Optional[date]
    rows: List[CutRow] = field(default_factory=list)

    def has_data(self) -> bool:
        return any(r.qty > 0 for r in self.rows)

    def total_pieces(self) -> int:
        return sum(r.qty for r in self.rows if r.qty > 0)

    def program_name(self) -> str:
        s = (self.mill_number or "").strip()
        if not s:
            return "PROGRAM"
        out = []
        prev_digit = False
        for ch in s:
            if ch in "-_ ":
                out.append("_")
                prev_digit = False
            elif ch.isalpha() and prev_digit:
                out.append("_" + ch)
                prev_digit = False
            else:
                out.append(ch)
                prev_digit = ch.isdigit()
        result = ""
        for ch in "".join(out):
            if ch == "_" and result.endswith("_"):
                continue
            result += ch
        return result.strip("_")

    def program_description(self) -> str:
        if self.due_date:
            day = self.due_date.strftime("%A")
            return f"{day}_{self.style}_{self.due_date.month}_{self.due_date.day}_{self.due_date.year % 100:02d}"
        return f"{self.style or 'JOB'}"


def _is_station_header(value) -> bool:
    """True if the cell value looks like a MILL STATION name (CHOP SAW, RIP SAW, ...)."""
    if not value or not isinstance(value, str):
        return False
    up = value.strip().upper()
    if up in KNOWN_STATIONS:
        return True
    # Catch-all: anything ending in "SAW" that's a short label
    if up.endswith("SAW") and len(up) <= 20:
        return True
    return False


# Words that identify the banner row repeated above each station of the spec sheet.
# Adjust them to match your own spreadsheets.
SPEC_BANNER_WORDS = ("MILL", "SPECIFICATION")


def _is_specsheet_banner(value) -> bool:
    """The '<Company> Mill Specification Sheet' banner that repeats per section."""
    if not value or not isinstance(value, str):
        return False
    up = value.strip().upper()
    return all(word in up for word in SPEC_BANNER_WORDS)


def _find_chop_saw_section(ws) -> Optional[Tuple[int, int]]:
    """
    Locate the first CHOP SAW section on this sheet.

    Returns (header_row, end_row_exclusive) where:
      - header_row is the row containing 'CHOP SAW' in col AI
      - end_row_exclusive is the row where the NEXT station/banner starts
        (or ws.max_row + 1 if there's none below)
    Or None if no CHOP SAW header is found.
    """
    chop_row = None
    max_r = min(ws.max_row, 2000)
    for r in range(1, max_r + 1):
        # CHOP SAW is normally at col AI (35) but check a small range to be safe.
        for col in (STATION_COL, STATION_COL - 1, STATION_COL + 1):
            v = ws.cell(row=r, column=col).value
            if v and isinstance(v, str) and v.strip().upper() == "CHOP SAW":
                chop_row = r
                break
        if chop_row is not None:
            break

    if chop_row is None:
        # Fallback: any CHOP SAW text anywhere on the sheet
        for r in range(1, max_r + 1):
            for c in range(1, min(ws.max_column + 1, 60)):
                v = ws.cell(row=r, column=c).value
                if v and isinstance(v, str) and v.strip().upper() == "CHOP SAW":
                    chop_row = r
                    break
            if chop_row is not None:
                break

    if chop_row is None:
        return None

    # Now find where this section ENDS - the next station header below or
    # the next 'Mill Specification Sheet' banner.
    end_row = max_r + 1
    for r in range(chop_row + 5, max_r + 1):
        # Stop on a new station header in col AI
        v = ws.cell(row=r, column=STATION_COL).value
        if _is_station_header(v) and (not isinstance(v, str)
                                      or v.strip().upper() != "CHOP SAW"):
            end_row = r
            break
        # Stop on a repeated 'Mill Specification Sheet'
        for c in (7, 8, 9):  # col G area
            if _is_specsheet_banner(ws.cell(row=r, column=c).value):
                end_row = r
                break
        if end_row != max_r + 1:
            break

    return (chop_row, end_row)


def _read_metadata(ws) -> Tuple[str, str, Optional[date]]:
    mill = str(ws.cell(row=5, column=1).value or "").strip()
    style = str(ws.cell(row=5, column=12).value or "").strip()
    due_v = ws.cell(row=7, column=19).value
    due_date: Optional[date] = None
    if isinstance(due_v, datetime):
        due_date = due_v.date()
    elif isinstance(due_v, date):
        due_date = due_v
    return mill, style, due_date


def _read_rows(ws, start_row: int, end_row_exclusive: int) -> List[CutRow]:
    """Read CutRows from [start_row, end_row_exclusive)."""
    rows: List[CutRow] = []
    for r in range(start_row, end_row_exclusive):
        w = ws.cell(row=r, column=WIDTH_COL).value
        ln = ws.cell(row=r, column=LENGTH_COL).value
        qty = ws.cell(row=r, column=QTY_COL).value
        try:
            qty_int = int(float(qty)) if qty is not None and qty != "" else 0
        except (ValueError, TypeError):
            qty_int = 0
        if qty_int <= 0:
            continue
        try:
            width_f = float(w) if w is not None and w != "" else 0.0
            length_f = float(ln) if ln is not None and ln != "" else 0.0
        except (ValueError, TypeError):
            continue
        if length_f <= 0 or width_f <= 0:
            continue
        rows.append(CutRow(width=width_f, length=length_f, qty=qty_int))
    return rows


def read_workbook(path) -> List[ChopSawTable]:
    """Open xlsx and return one ChopSawTable per sheet that has a CHOP SAW section."""
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    tables: List[ChopSawTable] = []
    for sn in wb.sheetnames:
        ws = wb[sn]
        bounds = _find_chop_saw_section(ws)
        if bounds is None:
            continue
        chop_row, end_row = bounds
        # Data starts a few rows below the CHOP SAW header (col headers occupy rows
        # ~chop_row+2 to chop_row+3 in the standard layout). Start at chop_row + 4
        # to be conservative; _read_rows skips empty/zero rows anyway.
        data_start = chop_row + 4
        mill, style, due = _read_metadata(ws)
        rows = _read_rows(ws, data_start, end_row)
        tables.append(ChopSawTable(
            sheet_name=sn, mill_number=mill, style=style,
            due_date=due, rows=rows,
        ))
    return tables
