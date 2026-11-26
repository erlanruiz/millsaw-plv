# Mill Saw Machine — Setup Guide (no Python experience needed)

This guide walks you through installing Python and running the app for the
first time on a Windows PC. You only need to do **Steps 1–4 once**. After
that, running the app is just **Step 5**.

---

## Step 1 — Install Python 3.10

1. Press the **Windows key**, type `PowerShell`, right-click **Windows
   PowerShell**, and choose **Run as administrator**.
2. Copy and paste this command, then press **Enter**:

   ```powershell
   winget install Python.Python.3.10
   ```

3. If it asks you to accept terms (`Y/N`), type `Y` and press **Enter**.
4. Wait until you see "Successfully installed".
5. **Close that PowerShell window completely** (this matters — Python is
   only added to your PATH for *new* windows that open after install).

> **If `winget` isn't recognized**, you're on an older Windows. Instead:
> 1. Open <https://www.python.org/downloads/release/python-31011/>
> 2. Scroll down, click **Windows installer (64-bit)**.
> 3. Run it. **Tick the box "Add python.exe to PATH"** at the bottom of
>    the first screen — this is the most important step.
> 4. Click **Install Now** and wait for it to finish.

---

## Step 2 — Verify Python is installed

1. Open a **new** PowerShell window (no need for admin this time).
2. Type:

   ```powershell
   python --version
   ```

3. You should see something like `Python 3.10.11`. If you see
   `'python' is not recognized…` instead, see **Troubleshooting** at the
   bottom.

---

## Step 3 — Go to the project folder in PowerShell

1. In PowerShell, paste this command and press **Enter**:

   ```powershell
   cd "C:\MillSaw"
   ```

2. The prompt should now end in `C:\MillSaw>`. That's
   how you know you're in the right place.

---

## Step 4 — Install the one library the app needs

Still in PowerShell, run:

```powershell
python -m pip install -r requirements.txt
```

You'll see a progress bar and then `Successfully installed openpyxl…`.
This is a one-time install.

---

## Step 5 — Run the app

```powershell
python run.py
```

A window titled **"Mill Saw Machine - PLV Generator - v0.1.0"** opens.
That's the app. Use it like this:

1. Click **New Job (Upload xlsx)…** and pick your mill spec workbook.
2. The app shows every CHOP SAW table it found. Uncheck any you don't
   want.
3. Click **Process Data ▶**. The Ileana grid appears in the lower half.
4. Double-click any cell in the grid if you want to change it.
5. Click **Generate PLV file(s)**. The PLV files land in the job's
   folder under `jobs\<timestamp>\`.

To **reopen an old job**, double-click it in the list on the left.

---

## Step 6 (optional) — Make a one-click shortcut on your desktop

If you'd rather not type commands every time:

1. Right-click your Desktop → **New** → **Shortcut**.
2. For the location, paste exactly this (including the quotes):

   ```
   powershell.exe -NoExit -Command "cd 'C:\MillSaw'; python run.py"
   ```

3. Click **Next**. Name it something like `Mill Saw`. Click **Finish**.

Now double-clicking the shortcut launches the app directly.

---

## Step 7 (optional, advanced) — Build a single .exe

When you want to give a fellow IT person a self-contained app that
doesn't need Python installed:

```powershell
.\build_windows.bat
```

This produces `dist\MillSaw.exe` (about 15 MB). They can copy that one
file to any Windows machine and run it.

---

## Troubleshooting

**`'python' is not recognized as the name of a cmdlet…`**
Python isn't on PATH. Reinstall the python.org installer and make sure
the **"Add python.exe to PATH"** checkbox at the bottom is ticked. Then
**close all PowerShell windows** and open a new one before trying again.

**`'pip' is not recognized…`**
Use `python -m pip …` instead of `pip …`. (That's why the install
command above is `python -m pip install…`.)

**The app window never appears, but PowerShell shows an error**
Copy the last 10 lines of red text and send them — that's the actual
error message. Most often it's a missing library, fixed by re-running
`python -m pip install -r requirements.txt`.

**"Permission denied" when running winget**
You forgot to run PowerShell as administrator. Right-click PowerShell
in the Start menu and pick **Run as administrator**.

**`winget : The term 'winget' is not recognized…`**
Use the python.org installer route in the box under Step 1.

---

## What each command actually does (for the curious)

| Command | What it does |
|---|---|
| `winget install Python.Python.3.10` | Downloads & installs Python 3.10 system-wide |
| `python --version` | Asks Python to print its version — proves it's installed |
| `cd "…\Mill Saw Machine project"` | Tells PowerShell to work inside the project folder |
| `python -m pip install -r requirements.txt` | Reads the `requirements.txt` list and installs the libraries listed there |
| `python run.py` | Runs the app's entry point — opens the GUI window |

That's it. There's no compilation step, no servers to start, no
configuration files to edit.
