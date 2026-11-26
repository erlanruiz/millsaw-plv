"""
Command-line wrapper, useful for scripting / smoke testing without the GUI.

Usage:
    python -m millsaw.cli <input.xlsx> [--out-dir DIR] [--merge]
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .xlsx_reader import read_workbook
from .ileana_builder import build_ileana_table, Yields, to_display_grid
from .plv_writer import write_plv


def _safe(s: str) -> str:
    keep = "".join(c if c.isalnum() or c in "_-" else "_" for c in s)
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_") or "PROGRAM"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", help="path to mill spec workbook")
    ap.add_argument("--out-dir", default="output",
                    help="where to write generated PLV files (default: output/)")
    ap.add_argument("--merge", action="store_true",
                    help="merge all sheets' rows into a single PLV")
    ap.add_argument("--sheet", action="append",
                    help="only process this sheet (may be given multiple times)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--yield-125", type=float, default=80.0,
                    help="yield %% for 1.25\" boards (default: 80)")
    ap.add_argument("--yield-175", type=float, default=75.0,
                    help="yield %% for 1.75\" boards (default: 75)")
    ap.add_argument("--yield-250", type=float, default=75.0,
                    help="yield %% for 2.5\" boards (default: 75)")
    args = ap.parse_args(argv)
    yields = Yields.from_percent(args.yield_125, args.yield_175, args.yield_250)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tables = read_workbook(args.xlsx)
    if args.sheet:
        wanted = set(args.sheet)
        tables = [t for t in tables if t.sheet_name in wanted]

    keep = [t for t in tables if t.has_data()]
    if not keep:
        print("No CHOP SAW tables with data were found.", file=sys.stderr)
        return 1

    generated = []
    if args.merge:
        first = keep[0]
        merged = []
        idx = 1
        for t in keep:
            for r in build_ileana_table(t, yields=yields):
                r.idx = idx
                merged.append(r)
                idx += 1
        for i, r in enumerate(merged):
            r.esc = 0 if i in (0, len(merged) - 1) else 1
        out = out_dir / f"{_safe(first.program_name())}.plv"
        write_plv(out, first.program_name(), first.program_description(), merged)
        generated.append(out)
    else:
        for t in keep:
            rows = build_ileana_table(t, yields=yields)
            fname = f"{_safe(t.program_name())}_{_safe(t.sheet_name)}.plv"
            out = out_dir / fname
            write_plv(out, t.program_name(), t.program_description(), rows)
            generated.append(out)

    if not args.quiet:
        for g in generated:
            print(f"wrote {g} ({g.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
