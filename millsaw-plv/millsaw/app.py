"""
Mill Saw Machine - Desktop application (Tkinter).

Workflow: pick / create a job (uploads xlsx) -> review CHOP SAW tables ->
Process Data -> review Ileana grid -> Generate PLV(s) -> optionally
Send to Saw via FTP.
"""

from __future__ import annotations
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .job_manager import JobManager, JobMeta
from .xlsx_reader import read_workbook, ChopSawTable
from .ileana_builder import (
    build_ileana_table, IleanaRow, Yields, to_display_grid,
)
from .plv_writer import write_plv, read_back_summary, read_back_metadata
from .saws import Saw, SawList, SawRegistry, send_plv, test_connection, SendError
from .app_settings import AppSettings, AppSettingsStore


APP_TITLE = "Mill Saw Machine - PLV Generator"
APP_VERSION = "0.2.0"


def _safe_filename(s: str) -> str:
    keep = "".join(c if c.isalnum() or c in "_-" else "_" for c in s)
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_") or "PROGRAM"


def _data_root() -> Path:
    """
    Return the folder where jobs/, output/, and saws.json should live.

    When running from source (python run.py), this is the project root.
    When running from a PyInstaller .exe, sys.frozen is True and __file__
    points into _MEIPASS (a temp dir), so we use the .exe's location instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class TableSelection:
    table: ChopSawTable
    keep: bool = True
    rows: List[IleanaRow] = field(default_factory=list)


class MillSawApp:
    def __init__(self, root: tk.Tk, jobs_dir: Path, output_dir: Path):
        self.root = root
        self.jobs_dir = jobs_dir
        self.output_dir = output_dir
        self.jm = JobManager(jobs_dir)
        self.saw_registry = SawRegistry(jobs_dir.parent)

        self.current_job: Optional[JobMeta] = None
        self.tables: List[TableSelection] = []
        self.merge_var = tk.BooleanVar(value=False)
        # User-saved defaults (Set as default button writes here)
        self.app_settings = AppSettingsStore(jobs_dir.parent)
        s_init = self.app_settings.load()
        # Yield percent inputs (whole-percent values, e.g. 80, 110, 110)
        self.yield_125_var = tk.StringVar(value=f"{s_init.yield_125_pct:g}")
        self.yield_175_var = tk.StringVar(value=f"{s_init.yield_175_pct:g}")
        self.yield_250_var = tk.StringVar(value=f"{s_init.yield_250_pct:g}")

        root.title(f"{APP_TITLE} - v{APP_VERSION}")
        root.geometry("1100x720")
        self._build_ui()
        self._refresh_jobs()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        ttk.Button(bar, text="New Job (Upload xlsx)…",
                   command=self.cmd_new_job).pack(side="left")
        ttk.Button(bar, text="Reopen Selected Job",
                   command=self.cmd_open_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Delete Selected Job",
                   command=self.cmd_delete_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Refresh", command=self._refresh_jobs).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Manage Saws…",
                   command=self.cmd_manage_saws).pack(side="right", padx=(0, 4))
        self.send_btn = ttk.Button(bar, text="Send to Saw…",
                                   command=self.cmd_send_to_saw)
        self.send_btn.pack(side="right", padx=(0, 4))

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True, pady=8)

        # ---- jobs list (left)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        ttk.Label(left, text="Jobs (newest first):").pack(anchor="w")
        cols = ("created", "name", "status", "plvs")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for c, w, label in (
            ("created", 140, "Created"), ("name", 160, "Job"),
            ("status", 90, "Status"), ("plvs", 60, "PLVs"),
        ):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.cmd_open_selected())

        # ---- right detail
        right = ttk.Frame(body)
        body.add(right, weight=3)

        self.detail_label = ttk.Label(right, text="No job loaded.",
                                      font=("TkDefaultFont", 10, "bold"))
        self.detail_label.pack(anchor="w")

        picker_frame = ttk.LabelFrame(right, text="Detected CHOP SAW tables", padding=4)
        picker_frame.pack(fill="x", pady=(8, 0))
        self.tables_frame = ttk.Frame(picker_frame)
        self.tables_frame.pack(fill="x")

        yield_row = ttk.Frame(picker_frame)
        yield_row.pack(fill="x", pady=(6, 0))
        ttk.Label(yield_row, text="YIELD %:").pack(side="left")
        for label, var in (
            ("1.25\"", self.yield_125_var),
            ("1.75\"", self.yield_175_var),
            ("2.5\"", self.yield_250_var),
        ):
            ttk.Label(yield_row, text=label, padding=(8, 0, 2, 0)).pack(side="left")
            ttk.Entry(yield_row, textvariable=var, width=5, justify="right").pack(side="left")
        ttk.Button(yield_row, text="Reset to factory",
                   command=self._yields_reset_factory).pack(side="left", padx=4)
        ttk.Button(yield_row, text="Set as default",
                   command=self._yields_save_as_default).pack(side="left", padx=4)
        ttk.Label(yield_row, text="(factory: 80 / 110 / 110)",
                  foreground="#555").pack(side="left")

        opts_row = ttk.Frame(picker_frame)
        opts_row.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(opts_row, text="Merge all kept tables into one PLV",
                        variable=self.merge_var).pack(side="left")
        ttk.Button(opts_row, text="Process Data ▶",
                   command=self.cmd_process_data).pack(side="right")

        grid_frame = ttk.LabelFrame(right, text="Ileana LENGTHS preview", padding=4)
        grid_frame.pack(fill="both", expand=True, pady=(8, 0))
        nbk_holder = ttk.Frame(grid_frame)
        nbk_holder.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(nbk_holder)
        self.notebook.pack(fill="both", expand=True)
        self.tab_grids: Dict[str, ttk.Treeview] = {}
        self.tab_table_keys: Dict[str, str] = {}

        actions = ttk.Frame(grid_frame)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Label(actions, text="Double-click a cell in the preview to edit it."
                  ).pack(side="left")
        ttk.Button(actions, text="Generate PLV file(s)",
                   command=self.cmd_generate_plv).pack(side="right")

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(outer, textvariable=self.status_var, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom", pady=(4, 0))

    def _refresh_jobs(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for j in self.jm.list_jobs():
            self.tree.insert("", "end", iid=j.job_id, values=(
                j.created.replace("T", " "), j.name, j.status, len(j.plv_files),
            ))

    def _selected_job_id(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    # ---------------- command handlers ----------------

    def cmd_new_job(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose mill spec xlsx",
            filetypes=[("Excel workbook", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            meta = self.jm.create_job(path, name=Path(path).stem)
        except Exception as e:
            messagebox.showerror("Failed to create job", str(e))
            return
        self._refresh_jobs()
        self.tree.selection_set(meta.job_id)
        self._load_job(meta.job_id)

    def cmd_open_selected(self) -> None:
        jid = self._selected_job_id()
        if not jid:
            messagebox.showinfo("No selection", "Select a job from the list first.")
            return
        self._load_job(jid)

    def cmd_delete_selected(self) -> None:
        jid = self._selected_job_id()
        if not jid:
            return
        if not messagebox.askyesno("Delete job", f"Permanently delete job '{jid}'?"):
            return
        self.jm.delete_job(jid)
        if self.current_job and self.current_job.job_id == jid:
            self.current_job = None
            self.tables = []
            self.detail_label.config(text="No job loaded.")
            self._rebuild_table_picker()
            self._rebuild_grids()
        self._refresh_jobs()

    def cmd_process_data(self) -> None:
        if not self.tables:
            messagebox.showinfo("Nothing to process", "No CHOP SAW tables loaded.")
            return
        try:
            yields = self._read_yields()
        except ValueError as e:
            messagebox.showerror("Invalid yield value", str(e))
            return
        if self.current_job:
            p125, p175, p250 = yields.to_percent()
            self.current_job.yield_125_pct = p125
            self.current_job.yield_175_pct = p175
            self.current_job.yield_250_pct = p250
            self.jm.update_meta(self.current_job)
        processed = 0
        for sel in self.tables:
            if not sel.table.has_data():
                sel.rows = []
                continue
            try:
                sel.rows = build_ileana_table(sel.table, yields=yields)
                processed += 1
            except Exception as e:
                messagebox.showerror(
                    "Process failed",
                    f"Sheet '{sel.table.sheet_name}': {e}\n\n{traceback.format_exc()}"
                )
                return
        self._rebuild_grids()
        kept_count = sum(1 for s in self.tables if s.keep and s.rows)
        p125, p175, p250 = yields.to_percent()
        self._set_status(
            f"Processed {processed} table(s) at yields "
            f"{p125:g}/{p175:g}/{p250:g}%; {kept_count} marked Keep "
            f"will be generated as PLV."
        )

    def _read_yields(self) -> Yields:
        def _parse(name, var):
            raw = var.get().strip().rstrip("%")
            if not raw:
                raise ValueError(f"Yield for {name} is empty.")
            try:
                v = float(raw)
            except ValueError:
                raise ValueError(f"Yield for {name}: '{var.get()}' is not a number.")
            if v <= 0 or v > 150:
                raise ValueError(f"Yield for {name} must be 0..100. Got {v:g}.")
            return v
        p125 = _parse('1.25"', self.yield_125_var)
        p175 = _parse('1.75"', self.yield_175_var)
        p250 = _parse('2.5"',  self.yield_250_var)
        return Yields.from_percent(p125, p175, p250)

    def _yields_reset_factory(self) -> None:
        """Snap the YIELD % boxes back to factory defaults 80/110/110."""
        self.yield_125_var.set("80")
        self.yield_175_var.set("110")
        self.yield_250_var.set("110")

    def _yields_save_as_default(self) -> None:
        """Persist current yield values as the default for future NEW jobs."""
        try:
            yields = self._read_yields()
        except ValueError as e:
            messagebox.showerror("Invalid yield value", str(e))
            return
        p125, p175, p250 = yields.to_percent()
        self.app_settings.save(AppSettings(
            yield_125_pct=p125, yield_175_pct=p175, yield_250_pct=p250,
        ))
        self._set_status(
            f"Default yields saved: {p125:g} / {p175:g} / {p250:g}%. "
            f"Future new jobs will start with these values."
        )

    def cmd_generate_plv(self) -> None:
        if not self.current_job:
            messagebox.showinfo("No job", "Load or create a job first.")
            return
        kept = [t for t in self.tables if t.keep and t.rows]
        if not kept:
            messagebox.showinfo("No data",
                                "Run 'Process Data' first to populate the LENGTHS grid.")
            return
        out_dir = self.jm.get_job_dir(self.current_job.job_id)
        generated: List[Path] = []
        try:
            if self.merge_var.get() and len(kept) > 1:
                merged_rows: List[IleanaRow] = []
                idx = 1
                for sel in kept:
                    for r in sel.rows:
                        nr = IleanaRow(
                            idx=idx, length=r.length, width=r.width, quality=r.quality,
                            esc=r.esc, prt=r.prt, qty_125=r.qty_125,
                            qty_175=r.qty_175, qty_250=r.qty_250, cut=r.cut,
                            extra_blanks=r.extra_blanks,
                        )
                        merged_rows.append(nr)
                        idx += 1
                for i, r in enumerate(merged_rows):
                    r.esc = 0 if i in (0, len(merged_rows) - 1) else 1
                first = kept[0].table
                progname = first.program_name()
                progdes = first.program_description()
                out_file = out_dir / f"{_safe_filename(progname)}.plv"
                write_plv(out_file, progname, progdes, merged_rows)
                generated.append(out_file)
            else:
                for sel in kept:
                    progname = sel.table.program_name()
                    progdes = sel.table.program_description()
                    # Compact filename to stay under MAX_PATH on deep copies.
                    # Prefer just the program name; if multiple kept sheets
                    # share the same program name, suffix with a short tag.
                    base = _safe_filename(progname)
                    sheet_tag = _safe_filename(sel.table.sheet_name)[:18]
                    candidate = base + "_" + sheet_tag + ".plv"
                    if len(candidate) > 40:
                        candidate = base + "_" + sheet_tag[:8] + ".plv"
                    fname = candidate
                    out_file = out_dir / fname
                    write_plv(out_file, progname, progdes, sel.rows)
                    generated.append(out_file)
        except Exception as e:
            messagebox.showerror("PLV generation failed",
                                 f"{e}\n\n{traceback.format_exc()}")
            return

        for f in generated:
            self.jm.add_plv(self.current_job.job_id, f)
        self.current_job = self.jm.get_job(self.current_job.job_id)
        self._refresh_jobs()
        self.tree.selection_set(self.current_job.job_id)

        names = ", ".join(p.name for p in generated)
        messagebox.showinfo("Done",
                            f"Generated {len(generated)} PLV file(s):\n\n{names}\n\n"
                            f"Saved in:\n{out_dir}")
        self._set_status(f"Generated {len(generated)} PLV(s) -> {out_dir}")

    def cmd_manage_saws(self) -> None:
        ManageSawsDialog(self.root, self.saw_registry).show()

    def cmd_send_to_saw(self) -> None:
        if not self.current_job:
            messagebox.showinfo("No job", "Load or create a job first.")
            return
        meta = self.jm.get_job(self.current_job.job_id)
        if not meta or not meta.plv_files:
            messagebox.showinfo("No PLV files",
                                "Run 'Generate PLV file(s)' first.")
            return
        saws = self.saw_registry.load()
        if not saws.saws:
            if messagebox.askyesno(
                "No saw configured",
                "No saw machines configured.\n\nOpen 'Manage Saws…' now?"
            ):
                self.cmd_manage_saws()
            return
        SendToSawDialog(
            self.root, self.saw_registry,
            self.jm.get_job_dir(meta.job_id),
            meta.plv_files,
        ).show()

    # ---------------- internal helpers ----------------

    def _load_job(self, job_id: str) -> None:
        meta = self.jm.get_job(job_id)
        if not meta:
            messagebox.showerror("Missing", f"Job '{job_id}' not found.")
            return
        self.current_job = meta
        self.yield_125_var.set(f"{meta.yield_125_pct:g}")
        self.yield_175_var.set(f"{meta.yield_175_pct:g}")
        self.yield_250_var.set(f"{meta.yield_250_pct:g}")
        src = self.jm.get_source_path(job_id)
        try:
            tables = read_workbook(src)
        except Exception as e:
            messagebox.showerror("Read error",
                                 f"Couldn't open the source xlsx:\n{e}")
            return
        self.tables = [TableSelection(table=t, keep=t.has_data()) for t in tables]
        self.detail_label.config(
            text=f"Job: {meta.name}    |    Source: {meta.source_filename}    |    "
                 f"Detected {len(self.tables)} CHOP SAW table(s) "
                 f"({sum(1 for t in self.tables if t.keep)} with data)."
        )
        self._rebuild_table_picker()
        self._rebuild_grids()
        self._set_status(f"Loaded job '{meta.name}'.")

    def _rebuild_table_picker(self) -> None:
        for w in self.tables_frame.winfo_children():
            w.destroy()
        if not self.tables:
            ttk.Label(self.tables_frame, text="(no CHOP SAW tables found)"
                      ).pack(anchor="w")
            return
        hdr = ttk.Frame(self.tables_frame)
        hdr.pack(fill="x")
        for label, w in (("Keep", 6), ("Sheet", 28), ("Mill #", 12),
                         ("Style", 8), ("Due", 12), ("Rows", 8), ("Total qty", 10)):
            ttk.Label(hdr, text=label, width=w).pack(side="left")
        for sel in self.tables:
            row = ttk.Frame(self.tables_frame)
            row.pack(fill="x", pady=1)
            v = tk.BooleanVar(value=sel.keep)
            sel._tkvar = v  # type: ignore[attr-defined]

            def _toggle(s=sel, var=v):
                s.keep = var.get()
                self._refresh_tab_labels()

            ttk.Checkbutton(row, variable=v, command=_toggle).pack(side="left", padx=6)
            ttk.Label(row, text=sel.table.sheet_name, width=28, anchor="w"
                      ).pack(side="left")
            ttk.Label(row, text=sel.table.mill_number or "-", width=12, anchor="w"
                      ).pack(side="left")
            ttk.Label(row, text=sel.table.style or "-", width=8, anchor="w"
                      ).pack(side="left")
            due = sel.table.due_date.strftime("%m/%d/%y") if sel.table.due_date else "-"
            ttk.Label(row, text=due, width=12, anchor="w").pack(side="left")
            ttk.Label(row, text=str(len(sel.table.rows)), width=8, anchor="w"
                      ).pack(side="left")
            ttk.Label(row, text=str(sel.table.total_pieces()), width=10, anchor="w"
                      ).pack(side="left")

    def _rebuild_grids(self) -> None:
        for tid in list(self.notebook.tabs()):
            self.notebook.forget(tid)
        self.tab_grids.clear()
        self.tab_table_keys.clear()
        if not self.tables:
            return
        for sel in self.tables:
            if not sel.rows:
                continue
            tab = ttk.Frame(self.notebook)
            label = sel.table.sheet_name if sel.keep else f"(skipped) {sel.table.sheet_name}"
            self.notebook.add(tab, text=label)
            grid = self._make_grid(tab, sel.rows)
            tab_id = str(self.notebook.tabs()[-1])
            self.tab_grids[tab_id] = grid
            self.tab_table_keys[tab_id] = sel.table.sheet_name
            grid.bind("<Double-1>", lambda e, g=grid, s=sel: self._edit_cell(e, g, s))

    def _make_grid(self, parent, rows: List[IleanaRow]) -> ttk.Treeview:
        cols = ("idx", "width", "quality", "esc", "prt", "length",
                "cut", "q125", "q175", "q250", "extra")
        labels = ("#", "WIDTH", "QUALITY", "ESC", "PRT", "LENGTH (in)",
                  "CUT", "1.25", "1.75", "2.5", "Extra Blanks")
        widths = (50, 70, 80, 60, 60, 110, 70, 70, 70, 70, 110)

        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        tv = ttk.Treeview(holder, columns=cols, show="headings", height=14)
        for c, label, w in zip(cols, labels, widths):
            tv.heading(c, text=label)
            tv.column(c, width=w, minwidth=w, anchor="center", stretch=False)
        for r in rows:
            tv.insert("", "end", values=(
                r.idx, r.width, r.quality, r.esc, r.prt,
                f"{r.length:g}", r.cut,
                r.qty_125 or "", r.qty_175 or "",
                r.qty_250 or "", r.extra_blanks,
            ))
        vsb = ttk.Scrollbar(holder, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tv.bind("<MouseWheel>", lambda e: tv.yview_scroll(int(-e.delta / 120), "units"))
        tv.bind("<Shift-MouseWheel>", lambda e: tv.xview_scroll(int(-e.delta / 120), "units"))
        return tv

    def _edit_cell(self, event, tv: ttk.Treeview, sel: TableSelection) -> None:
        region = tv.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = tv.identify_column(event.x)
        item = tv.identify_row(event.y)
        if not item:
            return
        col_index = int(col.lstrip("#")) - 1
        col_keys = ["idx", "width", "quality", "esc", "prt", "length",
                    "cut", "q125", "q175", "q250", "extra"]
        if col_index >= len(col_keys):
            return
        key = col_keys[col_index]
        if key in ("idx", "extra"):
            return
        cur_vals = list(tv.item(item, "values"))
        cur = cur_vals[col_index]
        new = self._prompt_value(f"Edit {key.upper()}", str(cur))
        if new is None:
            return
        row_idx = tv.index(item)
        if row_idx >= len(sel.rows):
            return
        r = sel.rows[row_idx]
        try:
            if key == "length":
                r.length = float(new)
            elif key == "cut":
                r.cut = max(0, int(float(new)))
            elif key == "q125":
                r.qty_125 = max(0, int(float(new) or 0))
            elif key == "q175":
                r.qty_175 = max(0, int(float(new) or 0))
            elif key == "q250":
                r.qty_250 = max(0, int(float(new) or 0))
            elif key in ("width", "quality", "esc", "prt"):
                attr = {"width":"width","quality":"quality","esc":"esc","prt":"prt"}[key]
                setattr(r, attr, int(float(new)))
        except ValueError:
            messagebox.showerror("Bad value", f"Could not parse {new!r} as a number.")
            return
        cur_vals[col_index] = new
        tv.item(item, values=cur_vals)

    def _prompt_value(self, title: str, initial: str) -> Optional[str]:
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=title, padding=8).pack(anchor="w")
        var = tk.StringVar(value=initial)
        ent = ttk.Entry(dlg, textvariable=var, width=24)
        ent.pack(padx=8, pady=4)
        ent.select_range(0, "end")
        ent.focus_set()
        result = {"v": None}
        def ok():
            result["v"] = var.get()
            dlg.destroy()
        def cancel():
            dlg.destroy()
        btns = ttk.Frame(dlg); btns.pack(pady=8)
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=cancel).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda _e: ok())
        dlg.bind("<Escape>", lambda _e: cancel())
        self.root.wait_window(dlg)
        return result["v"]

    def _refresh_tab_labels(self) -> None:
        by_name = {s.table.sheet_name: s for s in self.tables}
        for tab_id in self.notebook.tabs():
            sheet_name = self.tab_table_keys.get(tab_id)
            if not sheet_name:
                continue
            sel = by_name.get(sheet_name)
            if not sel:
                continue
            label = sheet_name if sel.keep else f"(skipped) {sheet_name}"
            self.notebook.tab(tab_id, text=label)

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)


# ============================ Saw dialogs ===================================

class ManageSawsDialog:
    def __init__(self, parent, registry):
        self.parent = parent
        self.registry = registry
        self.saw_list = registry.load()

    def show(self):
        dlg = tk.Toplevel(self.parent)
        self.dlg = dlg
        dlg.title("Manage Saw Machines")
        dlg.transient(self.parent)
        dlg.grab_set()
        dlg.geometry("640x360")
        cols = ("name", "host", "port", "user", "remote")
        labels = ("Name", "Host", "Port", "User", "Remote dir")
        widths = (120, 160, 60, 100, 160)
        frame = ttk.Frame(dlg, padding=8); frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for c, lab, w in zip(cols, labels, widths):
            self.tree.heading(c, text=lab); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self._refresh()
        bar = ttk.Frame(frame); bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Add…", command=self._add).pack(side="left")
        ttk.Button(bar, text="Edit…", command=self._edit).pack(side="left", padx=4)
        ttk.Button(bar, text="Remove", command=self._remove).pack(side="left")
        ttk.Button(bar, text="Test connection", command=self._test).pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=dlg.destroy).pack(side="right")

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for s in self.saw_list.saws:
            self.tree.insert("", "end", iid=s.name,
                             values=(s.name, s.host, s.port, s.username, s.remote_dir))

    def _selected(self):
        sel = self.tree.selection()
        return self.saw_list.find(sel[0]) if sel else None

    def _save(self):
        self.registry.save(self.saw_list)

    def _add(self):
        s = SawEditorDialog(self.dlg).edit(Saw(name="", host=""))
        if not s:
            return
        if not s.name.strip():
            messagebox.showerror("Invalid", "Name is required.")
            return
        if self.saw_list.find(s.name):
            messagebox.showerror("Duplicate", f"A saw named '{s.name}' already exists.")
            return
        self.saw_list.saws.append(s)
        self._save(); self._refresh()

    def _edit(self):
        cur = self._selected()
        if not cur:
            return
        updated = SawEditorDialog(self.dlg).edit(Saw(
            name=cur.name, host=cur.host, port=cur.port,
            username=cur.username, password=cur.password,
            remote_dir=cur.remote_dir, passive=cur.passive,
            timeout_sec=cur.timeout_sec,
        ))
        if not updated:
            return
        for i, s in enumerate(self.saw_list.saws):
            if s.name == cur.name:
                self.saw_list.saws[i] = updated
                break
        self._save(); self._refresh()

    def _remove(self):
        cur = self._selected()
        if not cur:
            return
        if not messagebox.askyesno("Remove", f"Remove saw '{cur.name}'?"):
            return
        self.saw_list.saws = [s for s in self.saw_list.saws if s.name != cur.name]
        self._save(); self._refresh()

    def _test(self):
        cur = self._selected()
        if not cur:
            messagebox.showinfo("No selection", "Select a saw first.")
            return
        try:
            msg = test_connection(cur)
        except SendError as e:
            messagebox.showerror("Connection failed",
                                 f"Could not connect to '{cur.name}':\n\n{e}")
            return
        messagebox.showinfo("Connection OK", f"{cur.name}: {msg}")


class SawEditorDialog:
    def __init__(self, parent):
        self.parent = parent
        self.result = None

    def edit(self, initial):
        dlg = tk.Toplevel(self.parent)
        dlg.title("Saw machine"); dlg.transient(self.parent); dlg.grab_set()
        vars_ = {
            "name": tk.StringVar(value=initial.name),
            "host": tk.StringVar(value=initial.host),
            "port": tk.StringVar(value=str(initial.port)),
            "username": tk.StringVar(value=initial.username),
            "password": tk.StringVar(value=initial.password),
            "remote_dir": tk.StringVar(value=initial.remote_dir),
            "passive": tk.BooleanVar(value=initial.passive),
            "timeout_sec": tk.StringVar(value=str(initial.timeout_sec)),
        }
        frm = ttk.Frame(dlg, padding=10); frm.pack(fill="both", expand=True)
        rows = [
            ("Name (label):", "name", False),
            ("Host (IP or DNS):", "host", False),
            ("Port:", "port", False),
            ("Username:", "username", False),
            ("Password:", "password", True),
            ("Remote dir:", "remote_dir", False),
            ("Timeout (sec):", "timeout_sec", False),
        ]
        for r, (lab, key, secret) in enumerate(rows):
            ttk.Label(frm, text=lab).grid(row=r, column=0, sticky="e", pady=2, padx=(0, 6))
            ttk.Entry(frm, textvariable=vars_[key], width=32,
                      show="*" if secret else "").grid(row=r, column=1, sticky="we", pady=2)
        ttk.Checkbutton(frm, text="Passive mode (recommended for firewalls)",
                        variable=vars_["passive"]).grid(row=len(rows), column=1, sticky="w", pady=4)
        bar = ttk.Frame(frm); bar.grid(row=len(rows)+1, column=0, columnspan=2, pady=(10, 0), sticky="e")

        def ok():
            try:
                self.result = Saw(
                    name=vars_["name"].get().strip(),
                    host=vars_["host"].get().strip(),
                    port=int(vars_["port"].get() or 21),
                    username=vars_["username"].get().strip() or "millsaw",
                    password=vars_["password"].get(),
                    remote_dir=vars_["remote_dir"].get().strip() or "/",
                    passive=bool(vars_["passive"].get()),
                    timeout_sec=int(vars_["timeout_sec"].get() or 30),
                )
            except ValueError as e:
                messagebox.showerror("Invalid value", str(e))
                return
            dlg.destroy()

        def cancel():
            self.result = None
            dlg.destroy()

        ttk.Button(bar, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=cancel).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda _e: ok()); dlg.bind("<Escape>", lambda _e: cancel())
        self.parent.wait_window(dlg)
        return self.result


class SendToSawDialog:
    def __init__(self, parent, registry, job_dir, plv_files):
        self.parent = parent
        self.registry = registry
        self.job_dir = job_dir
        self.plv_files = list(plv_files)

    def show(self):
        dlg = tk.Toplevel(self.parent)
        self.dlg = dlg
        dlg.title("Send PLV to Saw"); dlg.transient(self.parent); dlg.grab_set()
        dlg.geometry("520x320")
        frm = ttk.Frame(dlg, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Choose saw:").grid(row=0, column=0, sticky="e", pady=2)
        saw_names = [s.name for s in self.registry.load().saws]
        self.saw_var = tk.StringVar(value=saw_names[0] if saw_names else "")
        ttk.Combobox(frm, values=saw_names, state="readonly",
                     textvariable=self.saw_var, width=30).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(frm, text="Choose PLV file:").grid(row=1, column=0, sticky="ne", pady=(8, 2))
        self.file_lb = tk.Listbox(frm, height=6, selectmode="extended")
        for fn in self.plv_files:
            self.file_lb.insert("end", fn)
        if self.plv_files:
            self.file_lb.selection_set(0)
        self.file_lb.grid(row=1, column=1, sticky="we", pady=(8, 2))
        ttk.Label(frm, text="(Ctrl-click to pick more than one)",
                  foreground="#555").grid(row=2, column=1, sticky="w")
        self.progress = ttk.Progressbar(frm, mode="determinate", length=420)
        self.progress.grid(row=3, column=0, columnspan=2, pady=(14, 4), sticky="we")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=self.status_var, foreground="#222"
                  ).grid(row=4, column=0, columnspan=2, sticky="w")
        bar = ttk.Frame(frm); bar.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="e")
        self.send_btn = ttk.Button(bar, text="Upload", command=self._upload)
        self.send_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=dlg.destroy).pack(side="left", padx=4)
        frm.columnconfigure(1, weight=1)

    def _upload(self):
        name = self.saw_var.get()
        if not name:
            messagebox.showinfo("No saw", "No saw machine is selected.")
            return
        sel_idx = self.file_lb.curselection()
        if not sel_idx:
            messagebox.showinfo("No file", "Pick at least one PLV file.")
            return
        files = [self.plv_files[i] for i in sel_idx]
        saw = self.registry.load().find(name)
        if not saw:
            messagebox.showerror("Missing", f"Saw '{name}' is no longer configured.")
            return
        self.send_btn.config(state="disabled")
        try:
            for fn in files:
                local = self.job_dir / fn
                self.status_var.set(f"Uploading {fn} to {saw.name}…")
                self.progress.config(value=0, maximum=max(1, local.stat().st_size))
                self.dlg.update_idletasks()
                def _progress(sent, total, _self=self):
                    _self.progress.config(value=sent, maximum=max(1, total))
                    _self.dlg.update_idletasks()
                try:
                    send_plv(saw, local, progress=_progress)
                except SendError as e:
                    messagebox.showerror("Upload failed", f"{fn}: {e}")
                    self.status_var.set(f"FAILED on {fn}")
                    return
            self.status_var.set(f"All uploads OK -> {saw.name}.")
            messagebox.showinfo("Done", f"Uploaded {len(files)} file(s) to {saw.name}.")
        finally:
            self.send_btn.config(state="normal")


# ============================ entry point ===================================

def main() -> int:
    base = _data_root()
    jobs_dir = base / "jobs"
    output_dir = base / "output"
    root = tk.Tk()
    try:
        style = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except tk.TclError:
        pass
    MillSawApp(root, jobs_dir, output_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
