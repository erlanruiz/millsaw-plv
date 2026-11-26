"""
Apply the Ileana Template transformations to extracted CHOP SAW rows.

Reproduces the key formulas from the Ileana template's LENGTHS sheet:
    WIDTH        : 3 if length present
    QUALITY      : 1 if length present
    ESC          : 0 for first/last data row, 1 otherwise
    PRT          : 0 always
    LENGTH       : decimal inches (already decimal in xlsx)
    Board cols   : 1.25 / 1.75 / 2.5 -- qty placed in column matching width
    Extra Blanks : sum of (2 if column has data) across the three columns
    CUT          : ROUNDUP((M/4 + 2)/X + (N/3 + 2)/Y + (O/2 + 2)/Z, 0)
                   X, Y, Z = yields for 1.25 / 1.75 / 2.5 (defaults 0.80/0.75/0.75)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from math import ceil
from typing import Dict, List, Optional

from .xlsx_reader import ChopSawTable, CutRow


DEFAULT_YIELD_125 = 0.80
DEFAULT_YIELD_175 = 1.10
DEFAULT_YIELD_250 = 1.10


@dataclass
class Yields:
    """User-adjustable yield percentages, expressed as decimals (0.80 = 80%)."""
    y125: float = DEFAULT_YIELD_125
    y175: float = DEFAULT_YIELD_175
    y250: float = DEFAULT_YIELD_250

    @classmethod
    def default(cls):
        return cls()

    @classmethod
    def from_percent(cls, p125, p175, p250):
        return cls(y125=p125 / 100.0, y175=p175 / 100.0, y250=p250 / 100.0)

    def to_percent(self):
        return (self.y125 * 100, self.y175 * 100, self.y250 * 100)

    def validate(self):
        for name, val in (("1.25", self.y125), ("1.75", self.y175), ("2.5", self.y250)):
            if val <= 0 or val > 1.5:
                raise ValueError(
                    f"Yield for {name} must be greater than 0 and at most 1.5 "
                    f"(150%). Got {val:.4f} ({val*100:.1f}%)."
                )


@dataclass
class IleanaRow:
    idx: int
    length: float
    width: int = 3
    quality: int = 1
    esc: int = 1
    prt: int = 0
    qty_125: int = 0
    qty_175: int = 0
    qty_250: int = 0
    cut: int = 0
    extra_blanks: int = 0


def _classify_width(w):
    if abs(w - 1.25) < 0.05:
        return "125"
    if abs(w - 1.75) < 0.05:
        return "175"
    if abs(w - 2.5) < 0.05:
        return "250"
    if abs(w - 2.75) < 0.05:
        return "250"
    if abs(w - 3.0) < 0.05:
        return "250"
    if w < 1.5:
        return "125"
    if w < 2.1:
        return "175"
    return "250"


def build_ileana_table(table, yields=None):
    if yields is None:
        yields = Yields.default()
    yields.validate()

    by_length = {}
    for cut in table.rows:
        if cut.qty <= 0 or cut.length <= 0:
            continue
        key = round(cut.length, 4)
        row = by_length.get(key)
        if row is None:
            row = IleanaRow(idx=0, length=key)
            by_length[key] = row
        bucket = _classify_width(cut.width)
        if bucket == "125":
            row.qty_125 += cut.qty
        elif bucket == "175":
            row.qty_175 += cut.qty
        else:
            row.qty_250 += cut.qty

    rows = list(by_length.values())
    rows.sort(key=lambda r: -r.length)
    for i, r in enumerate(rows, start=1):
        r.idx = i

    for r in rows:
        r.esc = 1
    if rows:
        rows[0].esc = 0
        rows[-1].esc = 0

    for r in rows:
        # Reproduce the Ileana template formula EXACTLY:
        #   CUT = ROUNDUP( (M/4+2)/X + (N/3+2)/Y + (O/2+2)/Z , 0)
        # Note: even widths with qty=0 contribute the (0+2)/yield = 2/yield
        # term, which acts as an "extra blank" board reservation. This
        # matches what the Macro EXCEL SALVADOR produces for every row.
        cut_total = (
            (r.qty_125 / 4 + 2) / yields.y125
            + (r.qty_175 / 3 + 2) / yields.y175
            + (r.qty_250 / 2 + 2) / yields.y250
        )
        r.cut = int(ceil(cut_total)) if cut_total > 0 else 0

        eb = 0
        if r.qty_125 > 0:
            eb += 2
        if r.qty_175 > 0:
            eb += 2
        if r.qty_250 > 0:
            eb += 2
        r.extra_blanks = eb

    return rows


def to_display_grid(rows):
    header = ["#", "WIDTH", "QUALITY", "ESC", "PRT", "LENGTH",
              "CUT", "1.25", "1.75", "2.5", "Extra Blanks"]
    grid = [header]
    for r in rows:
        grid.append([
            str(r.idx),
            str(r.width),
            str(r.quality),
            str(r.esc),
            str(r.prt),
            f"{r.length:g}",
            str(r.cut),
            str(r.qty_125) if r.qty_125 else "",
            str(r.qty_175) if r.qty_175 else "",
            str(r.qty_250) if r.qty_250 else "",
            str(r.extra_blanks),
        ])
    return grid
