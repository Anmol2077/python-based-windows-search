import os
import sys
import fnmatch
import threading
import time
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import webbrowser
import html
from urllib.parse import quote as urlquote

# Modern theming
import ttkbootstrap as tb  # pip install ttkbootstrap


# ------------------------ Core file ops ------------------------

def search_files(pattern, root_dir='.'):
    """
    Walk the filesystem starting at root_dir and return a list of dicts:
    {name, path, size, mtime}. Paths are absolute.
    """
    results = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in fnmatch.filter(filenames, pattern):
            full_path = os.path.abspath(os.path.join(dirpath, filename))
            try:
                st = os.stat(full_path)
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                size, mtime = 0, 0.0
            results.append({
                "name": filename,
                "path": full_path,
                "size": size,       # bytes
                "mtime": mtime,     # epoch seconds
            })
    return results

def open_in_explorer(target_path):
    """
    Open Windows File Explorer and highlight the file (if possible).
    Fallback: open containing folder.
    """
    try:
        norm = os.path.normpath(target_path)
        if hasattr(os, 'startfile') and os.path.exists(norm):
            subprocess.run(['explorer', '/select,', norm], check=False)
        else:
            parent = os.path.dirname(norm) or norm
            subprocess.run(['explorer', os.path.normpath(parent)], check=False)
    except Exception as e:
        messagebox.showerror("Explorer Error", f"Could not open Explorer for:\n{target_path}\n\n{e}")

def open_file(target_path):
    """
    Open the file with the system's default associated application.
    """
    try:
        if hasattr(os, 'startfile'):
            os.startfile(target_path)  # Windows
        else:
            if sys.platform == 'darwin':
                subprocess.run(['open', target_path], check=False)
            else:
                subprocess.run(['xdg-open', target_path], check=False)
    except Exception as e:
        messagebox.showerror("Open File Error", f"Could not open file:\n{target_path}\n\n{e}")

# ------------------------ Utilities ------------------------

def human_size(n_bytes):
    """Return human-friendly size (e.g., 12.3 KB, 4.5 MB)."""
    try:
        n = float(n_bytes)
    except Exception:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units)-1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"

def fmt_mtime(epoch_sec):
    if not epoch_sec:
        return ""
    dt = datetime.fromtimestamp(epoch_sec)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def file_ext(path):
    return os.path.splitext(path)[1][1:].lower()  # ext without dot

# ------------------------ App ------------------------

class App(tb.Window):  # Use ttkbootstrap Window for modern theming
    def __init__(self):
        # Default to a clean light theme; toggle will switch to darkly
        super().__init__(themename="flatly")  # 'flatly' (light), 'darkly' (dark)
        self.title("Search")
        self.geometry("1400x800")

        # NOTE: Do NOT assign to self.style (read-only on Window). Use the existing property.
        # self.style = tb.Style()  # <-- REMOVED to fix AttributeError
        self._current_theme = "flatly"  # for toggle
        # self.style is already available via tb.Window; you can use self.style.theme_use(...)

        # Data stores
        self.all_results = []       # full search results (list of dicts)
        self.filtered_results = []  # after filters
        self.sort_state = {}        # column_id -> ("asc"|"desc")

        # ---------- Top: Search controls ----------
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")

        ttk.Label(top, text="Search Pattern:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.pattern_var = tk.StringVar(value="*")
        self.pattern_entry = ttk.Entry(top, textvariable=self.pattern_var, width=36)
        self.pattern_entry.grid(row=0, column=1, sticky="we", padx=(0, 10))

        ttk.Label(top, text="Root Folder:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.root_var = tk.StringVar(value=os.getcwd())
        self.root_entry = ttk.Entry(top, textvariable=self.root_var, width=60)
        self.root_entry.grid(row=0, column=3, sticky="we", padx=(0, 6))
        ttk.Button(top, text="Browse…", command=self._browse_folder).grid(row=0, column=4, sticky="w")

        self.search_btn = ttk.Button(top, text="Search", command=self._on_search)
        self.search_btn.grid(row=0, column=5, padx=(12, 0))
        ttk.Button(top, text="Clear Results", command=self._clear_results).grid(row=0, column=6, padx=(6, 0))

        tip = ttk.Label(top, text="Tip: Use glob pattern (e.g., *.txt or *edcu*220*.dbc).")
        tip.grid(row=1, column=0, columnspan=7, sticky="w", pady=(6, 0))

        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(3, weight=2)

        # ---------- Filters (collapsible) ----------
        self.filters_panel = ttk.Frame(self, padding=(12, 6))
        self.filters_visible = tk.BooleanVar(value=False)

        filters_bar = ttk.Frame(self, padding=(12, 0))
        filters_bar.pack(fill="x")
        ttk.Button(filters_bar, text=" Filters ", command=self._toggle_filters).pack(side="left")
        ttk.Label(filters_bar, text="Click headers to sort • Drag column dividers to resize"
                  ).pack(side="left", padx=(10, 0))

        self._build_filters_ui()

        # ---------- Toolbar ----------
        toolbar = ttk.Frame(self, padding=(12, 6))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Open (Explorer)", command=self._open_selected_explorer).pack(side="left")
        ttk.Button(toolbar, text="Open File", command=self._open_selected_file).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Export HTML", command=self._export_html).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Reset Column Widths", command=self._reset_column_widths).pack(side="left", padx=(12, 0))

        # Theme toggle (light/dark)
        ttk.Button(toolbar, text=" Theme ", command=self._toggle_theme).pack(side="right")

        # ---------- Treeview + scrollbars ----------
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.columns = ("index", "name", "path", "size", "modified")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=self.columns,
            show="headings",
            selectmode="extended"  # allow multi-select
        )
        
        # right after self.tree = ttk.Treeview(...):
        self.tree.column("#0", width=0, stretch=True)  # absorb extra space in the hidden column
        self.tree.bind("<Double-1>", lambda e: self._open_selected_file())
        
        # Headings with sort bindings
        self._setup_tree_headings()

        # Column defaults (widths in pixels)
        self.default_widths = {
            "index": 70,
            "name": 380,
            "path": 800,
            "size": 120,
            "modified": 160,
        }
        self._apply_column_widths(self.default_widths)

        # Attach scrollbars
        self.vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Mouse wheel support
        self._bind_mousewheel(self.tree)

        # Context menu (right-click)
        self._build_context_menu()

        # ---------- Footer / Status ----------
        status_bar = ttk.Frame(self, padding=(12, 8))
        status_bar.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left")

        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=200)

        ttk.Button(status_bar, text="Exit", command=self.destroy).pack(side="right")

        # Keyboard shortcuts
        self.pattern_entry.bind("<Return>", lambda e: self._on_search())
        self.root_entry.bind("<Return>", lambda e: self._on_search())

    # ------------------------ Filters UI ------------------------

    def _build_filters_ui(self):
        # Clear existing
        for child in self.filters_panel.winfo_children():
            child.destroy()

        # Controls
        row = ttk.Frame(self.filters_panel)
        row.pack(fill="x")

        # Name glob (fnmatch)
        ttk.Label(row, text="Name (glob):").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.f_name_glob = tk.StringVar(value="*")
        ttk.Entry(row, textvariable=self.f_name_glob, width=24).grid(row=0, column=1, sticky="w", padx=(0, 12))

        # Path contains
        ttk.Label(row, text="Path contains:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.f_path_contains = tk.StringVar()
        ttk.Entry(row, textvariable=self.f_path_contains, width=30).grid(row=0, column=3, sticky="w", padx=(0, 12))

        # Extension
        ttk.Label(row, text="Ext:").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.f_ext = tk.StringVar()
        ttk.Entry(row, textvariable=self.f_ext, width=10).grid(row=0, column=5, sticky="w", padx=(0, 12))

        # Size range (KB)
        ttk.Label(row, text="Size KB min:").grid(row=0, column=6, sticky="w", padx=(0, 6))
        self.f_size_min = tk.StringVar()
        ttk.Entry(row, textvariable=self.f_size_min, width=10).grid(row=0, column=7, sticky="w", padx=(0, 12))

        ttk.Label(row, text="Size KB max:").grid(row=0, column=8, sticky="w", padx=(0, 6))
        self.f_size_max = tk.StringVar()
        ttk.Entry(row, textvariable=self.f_size_max, width=10).grid(row=0, column=9, sticky="w", padx=(0, 12))

        # Buttons
        btns = ttk.Frame(self.filters_panel)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Apply Filters", command=self._apply_filters).pack(side="left")
        ttk.Button(btns, text="Clear Filters", command=self._clear_filters).pack(side="left", padx=(6, 0))

    def _toggle_filters(self):
        if self.filters_visible.get():
            self.filters_panel.pack_forget()
            self.filters_visible.set(False)
        else:
            self.filters_panel.pack(fill="x")
            self.filters_visible.set(True)

    def _clear_filters(self):
        self.f_name_glob.set("*")
        self.f_path_contains.set("")
        self.f_ext.set("")
        self.f_size_min.set("")
        self.f_size_max.set("")
        self._apply_filters()

    def _apply_filters(self):
        """Filter self.all_results into self.filtered_results, then render."""
        name_glob = self.f_name_glob.get().strip() or "*"
        path_contains = self.f_path_contains.get().strip().lower()
        ext = self.f_ext.get().strip().lower()
        size_min = self._parse_int(self.f_size_min.get())
        size_max = self._parse_int(self.f_size_max.get())
        size_min_b = size_min * 1024 if size_min is not None else None
        size_max_b = size_max * 1024 if size_max is not None else None

        filtered = []
        for item in self.all_results:
            name_ok = fnmatch.fnmatch(item["name"], name_glob)
            path_ok = path_contains in item["path"].lower() if path_contains else True
            ext_ok = (file_ext(item["path"]) == ext) if ext else True
            size_ok = True
            if size_min_b is not None and item["size"] < size_min_b:
                size_ok = False
            if size_max_b is not None and item["size"] > size_max_b:
                size_ok = False

            if name_ok and path_ok and ext_ok and size_ok:
                filtered.append(item)

        self.filtered_results = filtered
        if self.sort_state:
            last_col, order = next(reversed(self.sort_state.items()))
            self._sort_results(last_col, order, render=False)

        self._render_treeview(self.filtered_results)
        self.status_var.set(f"Showing {len(self.filtered_results)} item(s) after filtering.")

    # ------------------------ Treeview Setup & Behavior ------------------------

    def _setup_tree_headings(self):
        headings = {
            "index": "Index",
            "name": "File Name",
            "path": "Full Path",
            "size": "Size",
            "modified": "Modified",
        }
        for col, text in headings.items():
            self.tree.heading(col, text=text, command=lambda c=col: self._on_heading_click(c))

    def _apply_column_widths(self, widths):
        for col, w in widths.items():
            self.tree.column(col, width=w, minwidth=40, stretch=False)

    def _reset_column_widths(self):
        self._apply_column_widths(self.default_widths)

    def _on_heading_click(self, col):
        current = self.sort_state.get(col, "desc")  # default to descending next
        new_dir = "asc" if current == "desc" else "desc"
        self.sort_state = {col: new_dir}
        self._sort_results(col, new_dir, render=True)

    def _sort_results(self, col, direction, render=True):
        reverse = (direction == "desc")

        def key_func(item):
            if col == "index":
                return item["path"]  # stable proxy
            if col == "name":
                return item["name"].lower()
            if col == "path":
                return item["path"].lower()
            if col == "size":
                return item["size"]
            if col == "modified":
                return item["mtime"]
            return item["path"]

        self.filtered_results.sort(key=key_func, reverse=reverse)
        if render:
            self._render_treeview(self.filtered_results)

    def _render_treeview(self, items):
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(items, start=1):
            values = (
                i,
                item["name"],
                item["path"],
                human_size(item["size"]),
                fmt_mtime(item["mtime"]),
            )
            self.tree.insert("", "end", values=values)

    # ------------------------ Mouse wheel scrolling ------------------------

    def _bind_mousewheel(self, widget):
        widget.bind("<Enter>", lambda e: self._bind_all_mousewheel())
        widget.bind("<Leave>", lambda e: self._unbind_all_mousewheel())

    def _bind_all_mousewheel(self):
        self.bind_all("<MouseWheel>", self._on_mousewheel_vertical)     # Windows/macOS
        self.bind_all("<Shift-MouseWheel>", self._on_mousewheel_horizontal)
        self.bind_all("<Button-4>", self._on_mousewheel_linux_up)       # Linux
        self.bind_all("<Button-5>", self._on_mousewheel_linux_down)

    def _unbind_all_mousewheel(self):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Shift-MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel_vertical(self, event):
        delta = -1 * int(event.delta / 120) if sys.platform != "darwin" else -1 * int(event.delta)
        self.tree.yview_scroll(delta, "units")

    def _on_mousewheel_horizontal(self, event):
        delta = -1 * int(event.delta / 120) if sys.platform != "darwin" else -1 * int(event.delta)
        self.tree.xview_scroll(delta, "units")

    def _on_mousewheel_linux_up(self, event):
        self.tree.yview_scroll(-1, "units")

    def _on_mousewheel_linux_down(self, event):
        self.tree.yview_scroll(1, "units")

    # ------------------------ Context menu ------------------------

    def _build_context_menu(self):
        self.ctx = tk.Menu(self, tearoff=0)
        self.ctx.add_command(label="Open (Explorer)", command=self._open_selected_explorer)
        self.ctx.add_command(label="Open File", command=self._open_selected_file)
        self.ctx.add_separator()
        self.ctx.add_command(label="Copy Path", command=self._copy_selected_path)
        self.ctx.add_command(label="Copy Folder", command=self._copy_selected_folder)

        self.tree.bind("<Button-3>", self._show_context_menu)  # right-click
        self.tree.bind("<Shift-F10>", self._show_context_menu)

    def _show_context_menu(self, event=None):
        try:
            row_id = self.tree.identify_row(event.y) if event else None
            if row_id and row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            if event:
                self.ctx.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.ctx.grab_release()
            except Exception:
                pass

    def _copy_selected_path(self):
        item = self._get_first_selected_item()
        if not item:
            return
        path = item["path"]
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status_var.set("Copied path to clipboard.")

    def _copy_selected_folder(self):
        item = self._get_first_selected_item()
        if not item:
            return
        folder = os.path.dirname(item["path"])
        self.clipboard_clear()
        self.clipboard_append(folder)
        self.status_var.set("Copied folder to clipboard.")

    # ------------------------ Actions ------------------------

    def _get_first_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Please select a row first.")
            return None
        values = self.tree.item(sel[0], "values")
        if not values or len(values) < 3:
            return None
        path = values[2]
        for item in self.filtered_results:
            if item["path"] == path:
                return item
        return None

    def _open_selected_explorer(self):
        item = self._get_first_selected_item()
        if item:
            open_in_explorer(item["path"])

    def _open_selected_file(self):
        item = self._get_first_selected_item()
        if item:
            open_file(item["path"])

    # ------------------------ Search ------------------------

    def _browse_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.root_var.get() or os.getcwd())
        if chosen:
            self.root_var.set(chosen)

    def _validate_inputs(self):
        pattern = self.pattern_var.get().strip()
        root_dir = self.root_var.get().strip()
        if not pattern:
            messagebox.showwarning("Input Required", "Please enter a search pattern (e.g., *.txt).")
            return None, None
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showwarning("Invalid Folder", "Please select a valid root folder.")
            return None, None
        return pattern, root_dir

    def _on_search(self):
        pattern, root_dir = self._validate_inputs()
        if pattern is None:
            return

        self.search_btn.config(state="disabled")
        self.status_var.set(f"Searching in {root_dir} with pattern '{pattern}'…")
        self.progress.pack(side="left", padx=(10, 0))
        self.progress.start(12)

        start_ts = time.time()

        def worker():
            try:
                found = search_files(pattern, root_dir=root_dir)
            except Exception as e:
                self.after(0, lambda: self._search_finished([], pattern, root_dir, start_ts, error=e))
                return
            self.after(0, lambda: self._search_finished(found, pattern, root_dir, start_ts, error=None))

        threading.Thread(target=worker, daemon=True).start()

    def _search_finished(self, found, pattern, root_dir, start_ts, error=None):
        self.progress.stop()
        self.progress.pack_forget()
        self.search_btn.config(state="normal")

        if error:
            self.status_var.set("Error during search.")
            messagebox.showerror("Search Error", str(error))
            return

        self.all_results = found
        self.filtered_results = list(found)
        elapsed = time.time() - start_ts
        self.status_var.set(f"Found {len(found)} item(s) in {elapsed:.2f}s — Pattern: {pattern}")

        self.sort_state.clear()
        self._render_treeview(self.filtered_results)

    def _clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self.all_results = []
        self.filtered_results = []  # <-- FIXED indentation
        self.sort_state.clear()
        self.status_var.set("Results cleared.")

    # ------------------------ Export HTML ------------------------

    def _export_html(self):
        if not self.filtered_results:
            messagebox.showinfo("No Results", "Nothing to export. Please run a search first.")
            return

        save_path = filedialog.asksaveasfilename(
            title="Export HTML Report",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")]
        )
        if not save_path:
            return

        pattern_text = self.pattern_var.get().strip()
        root_text = self.root_var.get().strip()
        pattern_esc = html.escape(pattern_text)
        root_esc = html.escape(root_text)
        generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        filters_desc = self._current_filters_description()

        rows_html = []
        for i, item in enumerate(self.filtered_results, start=1):
            name = html.escape(item["name"])
            path = item["path"]
            path_html = html.escape(path)
            path_attr = html.escape(path, quote=True)
            size_h = html.escape(human_size(item["size"]))
            mtime_h = html.escape(fmt_mtime(item["mtime"]))

            file_url = "file:///" + urlquote(path.replace("\\", "/"))
            folder_url = "file:///" + urlquote(os.path.dirname(path).replace("\\", "/"))

            rows_html.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td><a href=\"{file_url}\" target=\"_blank\">{name}</a></td>"
                f"<td class=\"path-cell\">{path_html}"
                "<div class=\"row-actions\">"
                f"<a href=\"{folder_url}\" target=\"_blank\" title=\"Open containing folder\">[Folder]</a>"
                f"<button class=\"copy-btn\" data-path=\"{path_attr}\" onclick=\"copyDataset(this)\">Copy Path</button>"
                "</div>"
                "</td>"
                f"<td>{size_h}</td>"
                f"<td>{mtime_h}</td>"
                "</tr>"
            )

        table_html = "\n".join(rows_html)

        html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>File Search Report</title>
<style>
body {{
    font-family: Segoe UI, Arial, sans-serif;
    margin: 20px;
    color: #222;
}}
h1 {{
    margin: 0 0 10px 0;
    font-size: 22px;
}}
.summary {{
    margin-bottom: 12px;
    color: #444;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    table-layout: fixed;
}}
th, td {{
    border: 1px solid #ddd;
    padding: 8px;
    vertical-align: top;
    word-wrap: break-word;
}}
th {{
    background: #f2f3f5;
    text-align: left;
}}
tr:nth-child(even) {{
    background: #fafbfc;
}}
td.path-cell {{
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
}}
.row-actions {{
    margin-top: 4px;
    font-size: 12px;
}}
.copy-btn {{
    margin-left: 8px;
    padding: 2px 6px;
    font-size: 12px;
}}
.footer {{
    margin-top: 16px;
    color: #666;
    font-size: 12px;
}}
</style>
<script>
function copyToClipboard(text) {{
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try {{
    document.execCommand("copy");
    alert("Copied to clipboard:\\n" + text);
  }} catch (err) {{
    alert("Copy failed: " + err);
  }}
  document.body.removeChild(ta);
}}
function copyDataset(el) {{
  const val = el.getAttribute('data-path') || '';
  copyToClipboard(val);
}}
</script>
</head>
<body>
  <h1>File Search Report</h1>
  <div class="summary">
    <div><b>Pattern:</b> {pattern_esc}</div>
    <div><b>Root Folder:</b> {root_esc}</div>
    <div><b>Generated:</b> {generated}</div>
    <div><b>Results:</b> {len(self.filtered_results)}</div>
    <div><b>Filters:</b> {html.escape(filters_desc)}</div>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:70px">Index</th>
        <th style="width:320px">File Name</th>
        <th>Full Path</th>
        <th style="width:110px">Size</th>
        <th style="width:160px">Modified</th>
      </tr>
    </thead>
    <tbody>
      {table_html}
    </tbody>
  </table>
  <div class="footer">Generated by File Search (Treeview UI)</div>
</body>
</html>
"""
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html_doc)
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not write HTML file:\n{e}")
            return

        open_url = "file:///" + save_path.replace("\\", "/")
        if messagebox.askyesno("Export Complete", f"HTML report saved to:\n{save_path}\n\nOpen it now?"):
            webbrowser.open_new_tab(open_url)

    def _current_filters_description(self):
        parts = []
        ng = self.f_name_glob.get().strip()
        if ng and ng != "*":
            parts.append(f"name={ng}")
        pc = self.f_path_contains.get().strip()
        if pc:
            parts.append(f"path contains='{pc}'")
        ex = self.f_ext.get().strip()
        if ex:
            parts.append(f"ext={ex}")
        mn = self.f_size_min.get().strip()
        mx = self.f_size_max.get().strip()
        if mn or mx:
            parts.append(f"sizeKB in [{mn or '-∞'}, {mx or '∞'}]")
        return ", ".join(parts) if parts else "none"

    # ------------------------ Helpers ------------------------

    @staticmethod
    def _parse_int(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None

    # ------------------------ Theme toggle (ttkbootstrap) ------------------------

    def _toggle_theme(self):
        # Flip between a light and a dark modern theme
        self._current_theme = "darkly" if self._current_theme == "flatly" else "flatly"
        self.style.theme_use(self._current_theme)

# ------------------------ Main ------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
