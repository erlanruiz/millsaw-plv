# Mill Saw PLV Generator

A free Windows tool for wood-products plants that run a computer-controlled chop saw with the
**TROPTIM** optimizer. It turns the cut tables in an Excel mill specification workbook into the
saw's `.plv` program files and sends them to the saw computer over the plant network.

It removes a manual step: copying parts, sizes, and quantities by hand from a spreadsheet into
the saw maker's template. At the plant where it was built, that step took hours each day; with
this tool it takes minutes.

## What it does

1. **New Job** — pick an `.xlsx` mill specification workbook. The app finds the CHOP SAW table
   on every sheet and shows the mill number, style, due date, and number of cut rows.
2. **Process Data** — applies the template formulas (groups parts by length, counts boards, adds
   allowance for waste) and shows the resulting cut list. Double-click a cell to edit it.
3. **Generate PLV** — writes one `.plv` per sheet, or one merged file.
4. **Send to saw** — uploads the file to the saw computer through a small FTP listener that
   accepts files only from approved addresses, only for one user, and only into one folder.

Every run is saved as a *job* folder, so it can be reopened or re-sent later.

## Requirements

- Windows 10 or 11 with Python 3.10 or newer (the saw-side listener also runs on older Windows
  with Python 3.8).
- `pip install -r requirements.txt`
- **A scaffold file you supply.** Copy any `.plv` file produced by your own TROPTIM installation to
  `millsaw/scaffold.plv`. The program clears its program name, description, and every cut length
  before writing new values. No saw file is included in this repository.
- Your mill specification workbook layout. `millsaw/xlsx_reader.py` reads one layout (a banner row
  with the words in `SPEC_BANNER_WORDS`, then a CHOP SAW section). Plants with a different layout
  adjust that one file; the file writer and the sender do not change.

## Quick start

```bat
pip install -r requirements.txt
python run.py
```

Then see `SETUP.md` (step by step for a new PC) and `PHASE2_SETUP.md` (installing the listener on
the saw computer).

## Saw connections

Copy `saws.example.json` to `saws.json` (or use **Manage Saws…** in the app) and enter your own
saw address, user, and password (the example leaves the password blank on purpose). `saws.json` is in
`.gitignore` and must never be published.

## Security design

- The saw computer runs a listener that accepts uploads only from the addresses you list, only for
  one user, and only into the saw's drop folder.
- The listener will not start while its password is still the placeholder `changeme`.
- Keep saw computers on their own network segment, separate from office computers.

## PLV format notes

The `.plv` file is a fixed 4,553,968-byte container. Only three regions change between programs:

| Offset       | Size        | Field                                |
|--------------|-------------|--------------------------------------|
| `0x408`      | 16 bytes    | program name (ASCII, NUL-padded)     |
| `0x510`      | 24 bytes    | program description (ASCII)          |
| `0x10D680..` | 100 × 0x210 | length-record slots M310001–M310100  |

In each slot, `+0x18` holds the length in millimeters (8-byte little-endian double) and `+0x20`
holds the cut count (4-byte little-endian unsigned integer). During development, files rebuilt by
this program matched genuine saw files byte for byte.

## Tests

```bat
python -m pytest tests/
```

## License and trademarks

MIT License — see `LICENSE`. Free to use, change, and share.

TROPTIM, Salvador, and other product names belong to their owners. This project is independent and
is not affiliated with or endorsed by any saw maker or software vendor.

Author: Erlan René Ruiz Nicaragua
