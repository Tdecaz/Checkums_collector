"""Tkinter based GUI for the checksum collector application."""
from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional

from .models import AmbiguousEntry, MatchResult
from .parser import PDFParser, combine_fragments


class Application(tk.Tk):
    """Main Tkinter application."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Checksum Collector")
        self.geometry("1100x700")

        self.parser = PDFParser()

        self.input_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.status_var = tk.StringVar(value="Select folders and start the scan.")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="Idle")

        self.matches: List[MatchResult] = []
        self.ambiguous_entries: Dict[str, AmbiguousEntry] = {}
        self.errors: List[str] = []

        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._scan_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._poll_queue()

    # UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        padding = {"padx": 10, "pady": 5}

        path_frame = ttk.Frame(self)
        path_frame.pack(fill=tk.X, **padding)

        ttk.Label(path_frame, text="Input folder with PDFs:").grid(row=0, column=0, sticky=tk.W)
        input_entry = ttk.Entry(path_frame, textvariable=self.input_folder, width=80)
        input_entry.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(path_frame, text="Browse", command=self._select_input_folder).grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(path_frame, text="Output folder for Excel report:").grid(row=1, column=0, sticky=tk.W)
        output_entry = ttk.Entry(path_frame, textvariable=self.output_folder, width=80)
        output_entry.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(path_frame, text="Browse", command=self._select_output_folder).grid(row=1, column=2, sticky=tk.W, padx=5)

        control_frame = ttk.Frame(self)
        control_frame.pack(fill=tk.X, **padding)

        self.start_button = ttk.Button(control_frame, text="Start Scan", command=self._start_scan)
        self.start_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(control_frame, text="Cancel", command=self._cancel_scan, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=5)

        ttk.Label(control_frame, textvariable=self.progress_text).pack(side=tk.LEFT, padx=10)

        progress_frame = ttk.Frame(self)
        progress_frame.pack(fill=tk.X, **padding)

        progress_bar = ttk.Progressbar(progress_frame, maximum=100, variable=self.progress_var)
        progress_bar.pack(fill=tk.X)

        status_label = ttk.Label(self, textvariable=self.status_var)
        status_label.pack(fill=tk.X, **padding)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, **padding)

        columns = ("pdf", "page", "filename", "checksum", "notes")
        self.result_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        self.result_tree.heading("pdf", text="PDF")
        self.result_tree.heading("page", text="Page")
        self.result_tree.heading("filename", text="Filename")
        self.result_tree.heading("checksum", text="SHA-1")
        self.result_tree.heading("notes", text="Notes")

        self.result_tree.column("pdf", width=200, anchor=tk.W)
        self.result_tree.column("page", width=60, anchor=tk.CENTER)
        self.result_tree.column("filename", width=240, anchor=tk.W)
        self.result_tree.column("checksum", width=220, anchor=tk.W)
        self.result_tree.column("notes", width=300, anchor=tk.W)

        self.result_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.result_tree.yview)
        tree_scroll.pack(fill=tk.Y, side=tk.RIGHT)
        self.result_tree.configure(yscrollcommand=tree_scroll.set)

        action_frame = ttk.Frame(self)
        action_frame.pack(fill=tk.X, **padding)

        self.review_button = ttk.Button(action_frame, text="Review Ambiguous Items", command=self._open_review, state=tk.DISABLED)
        self.review_button.pack(side=tk.LEFT)

        self.export_button = ttk.Button(action_frame, text="Export to Excel", command=self._export_results, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=5)

        self.error_button = ttk.Button(action_frame, text="Show Errors", command=self._show_errors, state=tk.DISABLED)
        self.error_button.pack(side=tk.LEFT, padx=5)

    # Folder selection -------------------------------------------------
    def _select_input_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder with PDF files")
        if folder:
            self.input_folder.set(folder)

    def _select_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder for Excel output")
        if folder:
            self.output_folder.set(folder)

    # Scan orchestration -----------------------------------------------
    def _start_scan(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            messagebox.showinfo("Scan Running", "A scan is already in progress.")
            return

        input_dir = self.input_folder.get()
        output_dir = self.output_folder.get()
        if not os.path.isdir(input_dir):
            messagebox.showerror("Invalid Input", "Please select a valid input folder containing PDF files.")
            return
        if not os.path.isdir(output_dir):
            messagebox.showerror("Invalid Output", "Please select a valid output folder.")
            return

        self.start_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.review_button.configure(state=tk.DISABLED)
        self.export_button.configure(state=tk.DISABLED)
        self.error_button.configure(state=tk.DISABLED)

        self.matches.clear()
        self.ambiguous_entries.clear()
        self.errors.clear()
        self.result_tree.delete(*self.result_tree.get_children())
        self.status_var.set("Scanning...")
        self.progress_var.set(0)
        self.progress_text.set("Preparing")

        self.parser.reset()

        self._scan_thread = threading.Thread(
            target=self._run_scan,
            args=(input_dir,),
            daemon=True,
        )
        self._scan_thread.start()

    def _run_scan(self, input_dir: str) -> None:
        def progress_callback(index: int, total: int, pdf_path: str) -> None:
            percent = (index - 1) / total * 100 if total else 0
            self._queue.put(("progress", (percent, index, total, os.path.basename(pdf_path))))

        matches, ambiguous, errors = self.parser.parse_folder(input_dir, progress_callback=progress_callback)
        self._queue.put(("completed", (matches, ambiguous, errors)))

    def _cancel_scan(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            self.parser.stop()
            self.status_var.set("Cancellation requested...")
        else:
            self.cancel_button.configure(state=tk.DISABLED)

    # Queue polling ----------------------------------------------------
    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self._queue.get_nowait()
                if event == "progress":
                    percent, index, total, name = payload  # type: ignore[assignment]
                    self.progress_var.set(percent)
                    self.progress_text.set(f"Processing {index} of {total}: {name}")
                elif event == "completed":
                    matches, ambiguous, errors = payload  # type: ignore[assignment]
                    self._on_scan_completed(matches, ambiguous, errors)
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    def _on_scan_completed(
        self,
        matches: List[MatchResult],
        ambiguous: List[AmbiguousEntry],
        errors: List[str],
    ) -> None:
        self.cancel_button.configure(state=tk.DISABLED)
        self.start_button.configure(state=tk.NORMAL)
        self.progress_var.set(100)
        self.progress_text.set("Complete")

        self.matches = matches
        self.ambiguous_entries = {entry.entry_id: entry for entry in ambiguous}
        self.errors = errors

        self._refresh_results_tree()

        summary_parts = [f"Matches: {len(self.matches)}", f"Ambiguous: {len(self.ambiguous_entries)}"]
        if errors:
            summary_parts.append(f"Errors: {len(errors)}")
            self.error_button.configure(state=tk.NORMAL)
        else:
            self.error_button.configure(state=tk.DISABLED)
        self.status_var.set(" | ".join(summary_parts))

        if self.ambiguous_entries:
            self.review_button.configure(state=tk.NORMAL)
        else:
            self.review_button.configure(state=tk.DISABLED)

        self.export_button.configure(state=tk.NORMAL if self.matches else tk.DISABLED)

    def _refresh_results_tree(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        for result in self.matches:
            self.result_tree.insert(
                "",
                tk.END,
                values=(result.pdf_name, result.page, result.filename, result.checksum, result.notes),
            )

    # Ambiguous review -------------------------------------------------
    def _open_review(self) -> None:
        if not self.ambiguous_entries:
            messagebox.showinfo("No Ambiguous Items", "There are no ambiguous items to review.")
            return
        ReviewWindow(self, self.ambiguous_entries, self._on_review_complete)

    def _on_review_complete(self, updated_entries: Dict[str, AmbiguousEntry], new_matches: List[MatchResult]) -> None:
        self.ambiguous_entries = updated_entries
        self.matches.extend(new_matches)
        unresolved = [entry for entry in self.ambiguous_entries.values() if entry.status == "pending"]
        self.review_button.configure(state=tk.NORMAL if unresolved else tk.DISABLED)
        self.export_button.configure(state=tk.NORMAL if self.matches else tk.DISABLED)
        summary_parts = [f"Matches: {len(self.matches)}", f"Ambiguous: {len(unresolved)}"]
        if self.errors:
            summary_parts.append(f"Errors: {len(self.errors)}")
        self.status_var.set(" | ".join(summary_parts))
        self._refresh_results_tree()

    # Export -----------------------------------------------------------
    def _export_results(self) -> None:
        if not self.matches:
            messagebox.showinfo("No Data", "There are no matches to export.")
            return
        output_dir = self.output_folder.get()
        if not os.path.isdir(output_dir):
            messagebox.showerror("Invalid Output", "Please select a valid output folder.")
            return
        default_name = "checksum_report.xlsx"
        output_path = os.path.join(output_dir, default_name)
        path = filedialog.asksaveasfilename(
            title="Save Excel Report",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
            initialdir=output_dir,
        )
        if not path:
            return
        try:
            export_to_excel(path, self.matches, list(self.ambiguous_entries.values()))
            messagebox.showinfo("Export Complete", f"Report saved to {path}")
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Export Failed", f"Unable to export data: {exc}")

    # Errors -----------------------------------------------------------
    def _show_errors(self) -> None:
        if not self.errors:
            messagebox.showinfo("No Errors", "No errors were recorded during the scan.")
            return
        messagebox.showerror("Processing Errors", "\n".join(self.errors))


class ReviewWindow(tk.Toplevel):
    """Window used to review and resolve ambiguous entries."""

    def __init__(
        self,
        master: Application,
        entries: Dict[str, AmbiguousEntry],
        callback,
    ) -> None:
        super().__init__(master)
        self.title("Ambiguous Items Review")
        self.geometry("1000x600")
        self.transient(master)
        self.grab_set()

        self.master_app = master
        self.callback = callback
        self.entries = entries
        self.new_matches: List[MatchResult] = []

        self._build_ui()
        self._refresh_tree()

    def _build_ui(self) -> None:
        padding = {"padx": 10, "pady": 5}
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, **padding)

        columns = (
            "status",
            "pdf",
            "page",
            "filename",
            "filename_fragments",
            "checksum",
            "checksum_fragments",
            "notes",
        )
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "status": "Status",
            "pdf": "PDF",
            "page": "Page",
            "filename": "Filename",
            "filename_fragments": "Filename fragments",
            "checksum": "Checksum",
            "checksum_fragments": "Checksum fragments",
            "notes": "Notes",
        }
        for column, title in headings.items():
            self.tree.heading(column, text=title)
        widths = {
            "status": 80,
            "pdf": 180,
            "page": 60,
            "filename": 200,
            "filename_fragments": 220,
            "checksum": 220,
            "checksum_fragments": 220,
            "notes": 240,
        }
        for column, width in widths.items():
            anchor = tk.W if column != "page" else tk.CENTER
            self.tree.column(column, width=width, anchor=anchor)

        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll.pack(fill=tk.Y, side=tk.RIGHT)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, **padding)

        ttk.Button(button_frame, text="Join Filenames", command=self._join_filenames).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Join Checksums", command=self._join_checksums).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Edit Selected", command=self._edit_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Pair Selected", command=self._pair_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Mark as Valid", command=self._mark_as_valid).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Discard Selected", command=self._discard_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Mark Reviewed", command=self._mark_reviewed).pack(side=tk.LEFT, padx=5)

        close_frame = ttk.Frame(self)
        close_frame.pack(fill=tk.X, **padding)
        ttk.Button(close_frame, text="Done", command=self._close).pack(side=tk.RIGHT)

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in self.entries.values():
            if entry.status == "pending":
                self.tree.insert(
                    "",
                    tk.END,
                    iid=entry.entry_id,
                    values=(
                        entry.status,
                        entry.pdf_name,
                        entry.page,
                        entry.filename_value or "",
                        entry.filename_fragment_text(),
                        entry.checksum_value or "",
                        entry.checksum_fragment_text(),
                        entry.notes,
                    ),
                )

    # Actions ----------------------------------------------------------
    def _selected_entries(self) -> List[AmbiguousEntry]:
        selection = self.tree.selection()
        return [self.entries[item] for item in selection]

    def _join_filenames(self) -> None:
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("No Selection", "Please select entries to join filenames.")
            return
        for entry in entries:
            if entry.filename_value:
                continue
            if entry.filename_fragments:
                entry.filename_value = combine_fragments(entry.filename_fragments)
        self._refresh_tree()

    def _join_checksums(self) -> None:
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("No Selection", "Please select entries to join checksums.")
            return
        for entry in entries:
            if entry.checksum_value:
                continue
            if entry.checksum_fragments:
                entry.checksum_value = combine_fragments(entry.checksum_fragments)
        self._refresh_tree()

    def _edit_selected(self) -> None:
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("No Selection", "Please select an entry to edit.")
            return
        if len(entries) > 1:
            messagebox.showinfo("Single Selection Required", "Please edit one entry at a time.")
            return
        entry = entries[0]
        filename = simpledialog.askstring(
            "Edit Filename",
            "Enter filename value:",
            initialvalue=entry.filename_value or combine_fragments(entry.filename_fragments),
            parent=self,
        )
        if filename is not None:
            entry.filename_value = filename.strip() or None
        checksum = simpledialog.askstring(
            "Edit Checksum",
            "Enter SHA-1 checksum (40 hex chars):",
            initialvalue=entry.checksum_value or combine_fragments(entry.checksum_fragments),
            parent=self,
        )
        if checksum is not None:
            checksum = checksum.strip()
            if checksum and len(re.sub(r"[^0-9a-fA-F]", "", checksum)) != 40:
                messagebox.showerror("Invalid Checksum", "Checksum must contain 40 hexadecimal characters.")
            else:
                entry.checksum_value = re.sub(r"[^0-9a-fA-F]", "", checksum) if checksum else None
        self._refresh_tree()

    def _pair_selected(self) -> None:
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("No Selection", "Select entries that contain filenames and checksums to pair.")
            return
        filename_entries = [e for e in entries if e.filename_value and not e.checksum_value]
        checksum_entries = [e for e in entries if e.checksum_value and not e.filename_value]
        full_entries = [e for e in entries if e.filename_value and e.checksum_value]

        if full_entries:
            for entry in full_entries:
                self._promote_entry_to_match(entry, note="Marked as pair from review")
            self._refresh_tree()
            return

        if not filename_entries or not checksum_entries:
            messagebox.showerror(
                "Cannot Pair",
                "Select entries that provide filenames and entries that provide checksums.",
            )
            return

        if len(filename_entries) != len(checksum_entries):
            messagebox.showerror(
                "Mismatched Selection",
                "Select an equal number of filename and checksum entries to pair.",
            )
            return

        for filename_entry, checksum_entry in zip(filename_entries, checksum_entries):
            self._create_match_from_entries(filename_entry, checksum_entry)
        self._refresh_tree()

    def _mark_as_valid(self) -> None:
        entries = self._selected_entries()
        if not entries:
            messagebox.showinfo("No Selection", "Select entries that contain both filename and checksum values.")
            return
        for entry in entries:
            if entry.filename_value and entry.checksum_value:
                self._promote_entry_to_match(entry, note="Confirmed during review")
        self._refresh_tree()

    def _discard_selected(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        if not messagebox.askyesno("Discard Entries", "Discard selected entries?"):
            return
        for entry in entries:
            entry.status = "discarded"
        self._refresh_tree()

    def _mark_reviewed(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        for entry in entries:
            entry.status = "reviewed"
        self._refresh_tree()

    def _promote_entry_to_match(self, entry: AmbiguousEntry, note: str) -> None:
        if not (entry.filename_value and entry.checksum_value):
            return
        self.new_matches.append(
            MatchResult(
                pdf_path=entry.pdf_path,
                pdf_name=entry.pdf_name,
                page=entry.page,
                filename=entry.filename_value,
                checksum=entry.checksum_value.lower(),
                notes=f"{note}. {entry.notes}",
                confidence="manual",
            )
        )
        entry.status = "resolved"

    def _create_match_from_entries(self, filename_entry: AmbiguousEntry, checksum_entry: AmbiguousEntry) -> None:
        if not filename_entry.filename_value or not checksum_entry.checksum_value:
            return
        self.new_matches.append(
            MatchResult(
                pdf_path=filename_entry.pdf_path,
                pdf_name=filename_entry.pdf_name,
                page=filename_entry.page,
                filename=filename_entry.filename_value,
                checksum=checksum_entry.checksum_value.lower(),
                notes=f"Paired during review. {filename_entry.notes} | {checksum_entry.notes}",
                confidence="manual",
            )
        )
        filename_entry.status = "resolved"
        checksum_entry.status = "resolved"

    def _close(self) -> None:
        self.callback(self.entries, self.new_matches)
        self.destroy()


def export_to_excel(path: str, matches: List[MatchResult], ambiguous: List[AmbiguousEntry]) -> None:
    """Export results to an Excel workbook."""

    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openpyxl is required to export Excel files") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Matches"
    sheet.append(["PDF", "Page", "Filename", "SHA-1", "Notes", "Confidence"])
    for match in matches:
        sheet.append([
            match.pdf_name,
            match.page,
            match.filename,
            match.checksum,
            match.notes,
            match.confidence,
        ])

    ambiguous_sheet = workbook.create_sheet(title="Ambiguous")
    ambiguous_sheet.append(
        [
            "PDF",
            "Page",
            "Filename",
            "Filename fragments",
            "Checksum",
            "Checksum fragments",
            "Status",
            "Notes",
        ]
    )
    for entry in ambiguous:
        ambiguous_sheet.append(
            [
                entry.pdf_name,
                entry.page,
                entry.filename_value or "",
                entry.filename_fragment_text(),
                entry.checksum_value or "",
                entry.checksum_fragment_text(),
                entry.status,
                entry.notes,
            ]
        )

    workbook.save(path)
