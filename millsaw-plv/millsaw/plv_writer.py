"""
Write a TROPTIM .plv binary file from Ileana-formatted rows.

The .plv from the TROPTIM optimizer is a fixed 4,553,968-byte container.
Two sample PLVs only differ in 73 bytes (program-name, description, and
the LENGTH/CUT records). We use a clean scaffold (one of the samples
with all M310 length values cleared) and patch in the variable bytes.
"""

from __future__ import annotations
import struct
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .ileana_builder import IleanaRow


PLV_FILE_SIZE = 4_553_968

OFFSET_PROGNAME = 0x408
LEN_PROGNAME = 16

OFFSET_PROGDES = 0x510
LEN_PROGDES = 24

# W=3, Q=1 length-record block (where the Ileana macro routes everything).
M310_BASE = 0x10D680
M310_SLOT_STRIDE = 0x210
M310_SLOTS = 100

# Within a slot:
SLOT_LEN_OFFSET = 0x18    # 8-byte little-endian double = LENGTH in mm
SLOT_QTY_OFFSET = 0x20    # 4-byte little-endian uint32 = CUT count


def _scaffold_path() -> Path:
    """
    Find scaffold.plv whether running from source or a frozen .exe.
    PyInstaller unpacks data files under sys._MEIPASS.
    """
    here = Path(__file__).resolve().parent
    candidates = [here / "scaffold.plv"]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.insert(0, Path(base) / "millsaw" / "scaffold.plv")
        candidates.insert(0, Path(base) / "scaffold.plv")
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def _load_scaffold_clean() -> bytearray:
    path = _scaffold_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Missing PLV scaffold file: {path}\n"
            f"Place a clean reference PLV at this location."
        )
    buf = bytearray(path.read_bytes())
    if len(buf) != PLV_FILE_SIZE:
        raise ValueError(
            f"Scaffold has unexpected size {len(buf):,} (expected {PLV_FILE_SIZE:,})"
        )
    # Wipe ProgName / ProgDes
    for i in range(LEN_PROGNAME):
        buf[OFFSET_PROGNAME + i] = 0
    for i in range(LEN_PROGDES):
        buf[OFFSET_PROGDES + i] = 0
    # Wipe length + qty inside every M310 slot
    for s in range(M310_SLOTS):
        slot = M310_BASE + s * M310_SLOT_STRIDE
        for j in range(8):
            buf[slot + SLOT_LEN_OFFSET + j] = 0
        for j in range(4):
            buf[slot + SLOT_QTY_OFFSET + j] = 0
    return buf


def _patch_ascii(buf: bytearray, offset: int, length: int, value: str) -> None:
    raw = value.encode("ascii", errors="replace")[:length]
    for i in range(length):
        buf[offset + i] = raw[i] if i < len(raw) else 0


def _patch_slot(buf: bytearray, slot_idx: int, length_mm: float, cut_qty: int) -> None:
    if slot_idx < 0 or slot_idx >= M310_SLOTS:
        raise IndexError(f"slot_idx {slot_idx} out of range (max {M310_SLOTS - 1})")
    base = M310_BASE + slot_idx * M310_SLOT_STRIDE
    struct.pack_into("<d", buf, base + SLOT_LEN_OFFSET, length_mm)
    if cut_qty < 0:
        cut_qty = 0
    if cut_qty > 0xFFFFFFFF:
        cut_qty = 0xFFFFFFFF
    struct.pack_into("<I", buf, base + SLOT_QTY_OFFSET, cut_qty)


def write_plv(out_path,
              program_name: str,
              program_description: str,
              rows: Sequence[IleanaRow]) -> Path:
    """Generate a .plv at out_path. Returns the resolved Path."""
    if len(rows) > M310_SLOTS:
        raise ValueError(
            f"Too many length entries: got {len(rows)}, "
            f"PLV W3/Q1 bucket holds only {M310_SLOTS} slots."
        )
    buf = _load_scaffold_clean()
    _patch_ascii(buf, OFFSET_PROGNAME, LEN_PROGNAME, program_name)
    _patch_ascii(buf, OFFSET_PROGDES, LEN_PROGDES, program_description)
    for i, row in enumerate(rows):
        length_mm = round(row.length * 25.4, 4)
        _patch_slot(buf, i, length_mm, int(row.cut))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(buf))
    return out


def read_back_summary(plv_path) -> List:
    """Return list of (slot_idx, length_mm, qty) for all non-empty M310 slots."""
    data = Path(plv_path).read_bytes()
    out = []
    for s in range(M310_SLOTS):
        base = M310_BASE + s * M310_SLOT_STRIDE
        length_mm = struct.unpack_from("<d", data, base + SLOT_LEN_OFFSET)[0]
        qty = struct.unpack_from("<I", data, base + SLOT_QTY_OFFSET)[0]
        if length_mm > 0 or qty > 0:
            out.append((s, length_mm, qty))
    return out


def read_back_metadata(plv_path):
    data = Path(plv_path).read_bytes()
    pn = data[OFFSET_PROGNAME:OFFSET_PROGNAME + LEN_PROGNAME].split(b"\x00", 1)[0].decode("ascii", "replace")
    pd = data[OFFSET_PROGDES:OFFSET_PROGDES + LEN_PROGDES].split(b"\x00", 1)[0].decode("ascii", "replace")
    return pn, pd
