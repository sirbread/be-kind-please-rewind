import sys
import os
import shutil
import difflib
import hashlib
from datetime import datetime
import re
import json
import zipfile
import fnmatch

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFileDialog, QSplitter,
    QLabel, QTextBrowser, QComboBox, QMessageBox,
    QInputDialog, QTextEdit, QStyle, QLineEdit, QTreeWidgetItemIterator,
    QSystemTrayIcon, QMenu, QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QIcon

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PIL import Image

def get_documents_dir():
    import os
    from pathlib import Path
    if os.name == "nt":
        try:
            import ctypes.wintypes
            CSIDL_PERSONAL = 5
            SHGFP_TYPE_CURRENT = 0
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
            return buf.value
        except Exception:
            return str(Path.home() / "Documents")
    else:
        return os.path.join(os.path.expanduser("~"), "Documents")

APP_DATA_BASE = os.path.join(get_documents_dir(), "be-kind-please-rewind")
SNAPSHOTS_BASE = os.path.join(APP_DATA_BASE, "snapshots")
os.makedirs(SNAPSHOTS_BASE, exist_ok=True)
SETTINGS_PATH = os.path.join(APP_DATA_BASE, "settings.json")
IGNORE_FILE_PATH = os.path.join(APP_DATA_BASE, ".bkprignore")

DARK_STYLESHEET = """
QWidget { background-color: #2b2b2b; color: #ffffff; font-family: Segoe UI, Arial, sans-serif; font-size: 10pt; }
QMainWindow { background-color: #2b2b2b; }
QTreeWidget { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; padding: 5px; }
QTreeWidget::item { padding: 5px; }
QTreeWidget::item:selected { background-color: #0078d7; color: #ffffff; }
QHeaderView::section { background-color: #3c3f41; padding: 4px; border: 1px solid #4f5254; }
QTextBrowser { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; }
QPushButton { background-color: #4f5254; border: 1px solid #5f6264; padding: 6px 12px; border-radius: 4px; }
QPushButton:hover { background-color: #5f6264; }
QPushButton:pressed { background-color: #0078d7; }
QComboBox { background-color: #4f5254; border: 1px solid #5f6264; padding: 5px; border-radius: 4px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #4f5254; border: 1px solid #5f6264; selection-background-color: #0078d7; }
QLabel#header { font-weight: bold; padding: 5px 0px; font-size: 11pt; }
QLineEdit { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; padding: 5px; }
QSplitter::handle { background-color: #4f5254; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QTextEdit { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; }
"""

DIFF_CSS = """
<style>
body { background-color: #3c3f41; color: #f0f0f0; font-family: Consolas, 'Courier New', monospace; margin: 0; padding: 0; }
.layout-table { width: 100%; border-collapse: collapse; }
.layout-table td { width: 50%; vertical-align: top; }
.layout-table td:first-child { border-right: 1px solid #4f5254; }
.content-table { table-layout: fixed; width: 100%; border-collapse: collapse; font-size: 9.5pt; }
.content-table th { background-color: #2b2b2b; padding: 5px; text-align: left; font-weight: bold; border-bottom: 2px solid #222; }
.content-table td { padding: 1px 5px; vertical-align: top; word-wrap: break-word; }
.lineno { width: 40px; color: #888; text-align: right; padding-right: 10px; -webkit-user-select: none; user-select: none; }
.diff_add { background-color: #2a472a; }
.diff_sub { background-color: #582a2a; }
.empty_row { background-color: #3c3f41; }
pre { margin: 0; white-space: pre-wrap; }
</style>
"""

class ExclusionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("edit exclusions")
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)
        
        info_label = QLabel("add file or folder patterns to exclude (one per line).\nsupports wildcards like `*` and `?`.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.editor = QTextEdit()
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        layout.addWidget(self.editor)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.load_patterns()

    def load_patterns(self):
        if os.path.exists(IGNORE_FILE_PATH):
            with open(IGNORE_FILE_PATH, 'r') as f:
                self.editor.setPlainText(f.read())

    def get_patterns(self):
        return self.editor.toPlainText()

def hash_file_path(path):
    return hashlib.sha256(os.path.abspath(path).lower().encode("utf-8")).hexdigest()

def get_snapshot_dir(file_path):
    file_id = hash_file_path(file_path)
    dir_path = os.path.join(SNAPSHOTS_BASE, file_id)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path

def get_notes_path(file_path):
    return os.path.join(get_snapshot_dir(file_path), "notes.json")

def load_notes(file_path):
    notes_path = get_notes_path(file_path)
    if os.path.exists(notes_path):
        with open(notes_path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_notes(file_path, notes):
    notes_path = get_notes_path(file_path)
    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=4)

def current_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def make_snapshot_name(orig_name):
    base, ext = os.path.splitext(orig_name)
    return f"{base}_{current_timestamp()}{ext}"

def save_snapshot(file_path, note=None):
    if not os.path.exists(file_path): return None, None
    snapdir = get_snapshot_dir(file_path)
    snap_name = make_snapshot_name(os.path.basename(file_path))
    dest = os.path.join(snapdir, snap_name)
    shutil.copy2(file_path, dest)
    if note:
        notes = load_notes(file_path)
        notes[snap_name] = note
        save_notes(file_path, notes)
    return dest, snap_name

def list_snapshots(file_path):
    snapdir = get_snapshot_dir(file_path)
    if not os.path.exists(snapdir): return []
    files = [f for f in os.listdir(snapdir) if f not in ["notes.json", "settings.json"]]
    def snapkey(f):
        m = re.search(r'_(\d{8}_\d{6}_\d{6})', f)
        if m:
            try: return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f")
            except ValueError: pass
        return datetime.fromtimestamp(os.path.getmtime(os.path.join(snapdir, f)))
    return sorted(files, key=snapkey, reverse=True)

def format_snap_time(fname):
    m = re.search(r'_(\d{8}_\d{6}_\d{6})', fname)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f")
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        except ValueError: pass
    return fname

def get_text_diff(snap, curr):
    try:
        with open(snap, encoding="utf-8", errors="ignore") as f: left = f.readlines()
        with open(curr, encoding="utf-8", errors="ignore") as f: right = f.readlines()
    except Exception as e:
        return f"<pre>Could not read files: {e}</pre>"
    seq = difflib.SequenceMatcher(None, left, right)
    l, r = ['<table class="content-table"><tr><th>&nbsp;</th><th>Selected Version</th></tr>'], ['<table class="content-table"><tr><th>&nbsp;</th><th>Current File</th></tr>']
    for opcode, i1,i2, j1,j2 in seq.get_opcodes():
        if opcode == "equal":
            for i, j in zip(range(i1,i2), range(j1,j2)):
                l.append(f'<tr><td class="lineno">{i+1}</td><td><pre>{left[i]}</pre></td></tr>')
                r.append(f'<tr><td class="lineno">{j+1}</td><td><pre>{right[j]}</pre></td></tr>')
        elif opcode == "replace":
            for i in range(i2-i1): l.append(f'<tr class="diff_sub"><td class="lineno">{i1+i+1}</td><td><pre>{left[i1+i]}</pre></td></tr>')
            for j in range(j2-j1): r.append(f'<tr class="diff_add"><td class="lineno">{j1+j+1}</td><td><pre>{right[j1+j]}</pre></td></tr>')
            diff = (i2-i1) - (j2-j1)
            if diff > 0:
                for _ in range(diff): r.append('<tr class="empty_row"><td class="lineno">&nbsp;</td><td>&nbsp;</td></tr>')
            elif diff < 0:
                for _ in range(-diff): l.append('<tr class="empty_row"><td class="lineno">&nbsp;</td><td>&nbsp;</td></tr>')
        elif opcode == "delete":
            for i in range(i1, i2):
                l.append(f'<tr class="diff_sub"><td class="lineno">{i+1}</td><td><pre>{left[i]}</pre></td></tr>')
                r.append('<tr class="empty_row"><td class="lineno">&nbsp;</td><td>&nbsp;</td></tr>')
        elif opcode == "insert":
            for j in range(j1, j2):
                r.append(f'<tr class="diff_add"><td class="lineno">{j+1}</td><td><pre>{right[j]}</pre></td></tr>')
                l.append('<tr class="empty_row"><td class="lineno">&nbsp;</td><td>&nbsp;</td></tr>')
    l.append('</table>'); r.append('</table>')
    return DIFF_CSS + f'<table class="layout-table"><tr><td>{"".join(l)}</td><td>{"".join(r)}</td></tr></table>'

def get_image_preview(image_path):
    try:
        img = Image.open(image_path)
        img.thumbnail((256, 256))
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
    except Exception: return None

def get_latest_snapshot(file_path):
    snaps = list_snapshots(file_path)
    if not snaps: return None
    return os.path.join(get_snapshot_dir(file_path), snaps[0])

class ChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_modified(self, event):
        if not event.is_directory:
            self.callback(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self.callback(event.src_path)

class WatcherThread(QThread):
    file_changed = pyqtSignal(str)
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.observer = Observer()
    def run(self):
        handler = ChangeHandler(self.file_changed.emit)
        unique_dirs = set()
        for p in self.paths:
            if os.path.isdir(p):
                unique_dirs.add(p)
            elif os.path.isfile(p):
                unique_dirs.add(os.path.dirname(p))

        for d in unique_dirs:
             self.observer.schedule(handler, d, recursive=True)

        self.observer.start()
        try:
            while not self.isInterruptionRequested(): self.msleep(200)
        finally:
            self.observer.stop()
            self.observer.join()
    def stop(self): self.requestInterruption()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("be kind, please rewind")
        self.setGeometry(100, 100, 1400, 900)
        self.setWindowIcon(QIcon('bkpr.ico'))
        self.tracked_paths = [] 
        self.file_hashes = {} 
        self.watcher_thread = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_files)
        self.notes = {}
        self.is_quitting = False
        self.ignore_patterns = []
        self.init_ui()
        self.init_tray_icon()
        self.load_ignore_patterns()
        self.load_settings()

    def init_ui(self):
        main = QWidget(); layout = QVBoxLayout(main); self.setCentralWidget(main)
        top = QHBoxLayout()
        self.add_file_btn = QPushButton("+ add file"); self.add_file_btn.clicked.connect(self.add_file)
        self.add_folder_btn = QPushButton("+ add folder"); self.add_folder_btn.clicked.connect(self.add_folder)
        self.remove_btn = QPushButton("- remove"); self.remove_btn.clicked.connect(self.remove_item); self.remove_btn.setEnabled(False)
        self.exclusions_btn = QPushButton("Edit Exclusions"); self.exclusions_btn.clicked.connect(self.open_exclusions_editor)
        self.import_btn = QPushButton("import snapshots"); self.import_btn.clicked.connect(self.import_snapshots)
        self.export_btn = QPushButton("export snapshots"); self.export_btn.clicked.connect(self.export_snapshots); self.export_btn.setEnabled(False)
        self.freq_combo = QComboBox(); self.freq_combo.addItems(["On Change", "Every 30 Seconds", "Every 1 Minute", "Every 5 Minutes"])
        self.freq_combo.currentTextChanged.connect(self.update_monitoring)
        top.addWidget(self.add_file_btn); top.addWidget(self.add_folder_btn); top.addWidget(self.remove_btn)
        top.addWidget(self.exclusions_btn); top.addWidget(self.import_btn); top.addWidget(self.export_btn); top.addStretch()
        top.addWidget(QLabel("tracking frequency:")); top.addWidget(self.freq_combo)

        files_panel = QWidget(); files_layout = QVBoxLayout(files_panel); files_layout.setContentsMargins(0,0,0,0)
        files_layout.addWidget(QLabel("tracked items", objectName="header"))
        self.file_search_box = QLineEdit(); self.file_search_box.setPlaceholderText("search tracked items..."); self.file_search_box.textChanged.connect(self.filter_files_tree)
        files_layout.addWidget(self.file_search_box)
        self.files_tree = QTreeWidget(); self.files_tree.setHeaderHidden(True); self.files_tree.itemClicked.connect(self.on_item_selected)
        files_layout.addWidget(self.files_tree)

        versions_panel = QWidget(); versions_layout = QVBoxLayout(versions_panel); versions_layout.setContentsMargins(0,0,0,0)
        versions_layout.addWidget(QLabel("version history", objectName="header"))
        self.version_search_box = QLineEdit(); self.version_search_box.setPlaceholderText("search versions..."); self.version_search_box.textChanged.connect(self.filter_versions_list)
        versions_layout.addWidget(self.version_search_box)
        self.versions_list = QTreeWidget(); self.versions_list.setHeaderHidden(True); self.versions_list.itemClicked.connect(self.on_version_selected)
        versions_layout.addWidget(self.versions_list)
        
        notes_panel = QVBoxLayout(); notes_panel.addWidget(QLabel("snapshot note", objectName="header"))
        self.note_edit = QTextEdit(); self.note_edit.setPlaceholderText("add a note for the selected snapshot...")
        self.save_note_btn = QPushButton("save note"); self.save_note_btn.clicked.connect(self.save_note); self.save_note_btn.setEnabled(False)
        notes_panel.addWidget(self.note_edit); notes_panel.addWidget(self.save_note_btn)
        versions_layout.addLayout(notes_panel)

        preview_panel = QWidget(); preview_layout = QVBoxLayout(preview_panel); preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.addWidget(QLabel("preview / diff", objectName="header"))
        self.preview_box = QTextBrowser(); self.preview_box.setOpenExternalLinks(False)
        preview_layout.addWidget(self.preview_box)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(files_panel); splitter.addWidget(versions_panel); splitter.addWidget(preview_panel)
        splitter.setSizes([250, 350, 800])

        bottom = QHBoxLayout()
        self.delete_snap_btn = QPushButton("delete snapshot"); self.delete_snap_btn.setEnabled(False); self.delete_snap_btn.clicked.connect(self.delete_snapshot)
        bottom.addWidget(self.delete_snap_btn); bottom.addStretch()
        self.restore_as_copy_btn = QPushButton("restore as copy"); self.restore_as_copy_btn.setEnabled(False); self.restore_as_copy_btn.clicked.connect(self.restore_as_copy)
        bottom.addWidget(self.restore_as_copy_btn)
        self.restore_btn = QPushButton("restore selected version"); self.restore_btn.setEnabled(False); self.restore_btn.clicked.connect(self.restore_version)
        bottom.addWidget(self.restore_btn)

        layout.addLayout(top); layout.addWidget(splitter); layout.addLayout(bottom)

    def init_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('bkpr.ico'))
        self.tray_icon.setToolTip("be kind, please rewind")
        
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show_window)
        
        quit_action = tray_menu.addAction("Exit")
        quit_action.triggered.connect(self.quit_application)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.activateWindow()

    def quit_application(self):
        self.is_quitting = True
        self.close()

    def on_item_selected(self, item, column):
        path = item.data(0, Qt.UserRole)
        is_file = path and os.path.isfile(path)
        is_top_level = item.parent() is None

        self.export_btn.setEnabled(is_file)
        self.remove_btn.setEnabled(is_top_level)

        if is_file:
            self.show_versions()
        else:
            self.versions_list.clear()
            self.preview_box.clear()
            self.note_edit.clear()
            self.restore_btn.setEnabled(False)
            self.restore_as_copy_btn.setEnabled(False)
            self.delete_snap_btn.setEnabled(False)
            self.save_note_btn.setEnabled(False)

    def on_version_selected(self, item, column):
        self.show_preview(item)
        self.delete_snap_btn.setEnabled(True)
        self.save_note_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.restore_as_copy_btn.setEnabled(True)
        self.load_note()
        
    def open_exclusions_editor(self):
        dialog = ExclusionsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            patterns_text = dialog.get_patterns()
            with open(IGNORE_FILE_PATH, 'w') as f:
                f.write(patterns_text)
            self.load_ignore_patterns()
            self.refresh_all_tracking()

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "select file to track")
        if path and path not in self.tracked_paths: self.add_path(path)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "select folder to track")
        if path and path not in self.tracked_paths: self.add_path(path)

    def add_path(self, path):
        if self.is_path_ignored(path):
            QMessageBox.warning(self, "path ignored", "this file or folder cannot be tracked because it matches an exclusion pattern... check your exclusions.")
            return

        note, ok = QInputDialog.getText(self, "initial snapshot note", "enter a note for the first snapshot(s) (optional):")
        if not ok: return
        self.tracked_paths.append(path)
        if os.path.isfile(path):
            self.track_new_file(path, note)
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in files: self.track_new_file(os.path.join(root, name), note)
        self.update_files_tree()
        self.update_monitoring()

    def track_new_file(self, file_path, note):
        if self.is_path_ignored(file_path):
            return
        save_snapshot(file_path, note)
        self.file_hashes[file_path] = self.hash_file(file_path)

    def remove_item(self):
        curr = self.files_tree.currentItem()
        if not curr or curr.parent() is not None:
            return
            
        path = curr.data(0, Qt.UserRole)
        reply = QMessageBox.question(self, "remove item", f"are you sure you want to stop tracking {os.path.basename(path)}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes: return
        
        files_to_purge = []
        if os.path.isdir(path): files_to_purge.extend(self.get_all_files_in_path(path))
        else: files_to_purge.append(path)
        
        if files_to_purge:
            reply_del = QMessageBox.question(self, "delete snapshots", "do you also want to delete all associated snapshots?",
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply_del == QMessageBox.Yes:
                for f in files_to_purge: shutil.rmtree(get_snapshot_dir(f), ignore_errors=True)

        if path in self.tracked_paths:
            self.tracked_paths.remove(path)
            
        for f in files_to_purge: self.file_hashes.pop(f, None)
        
        self.update_files_tree()
        self.versions_list.clear(); self.preview_box.clear(); self.note_edit.clear()
        self.remove_btn.setEnabled(False); self.export_btn.setEnabled(False)
        self.restore_btn.setEnabled(False); self.restore_as_copy_btn.setEnabled(False)
        self.delete_snap_btn.setEnabled(False); self.save_note_btn.setEnabled(False)
        self.update_monitoring()

    def update_files_tree(self):
        current_selection = None
        if self.files_tree.currentItem():
            current_selection = self.files_tree.currentItem().data(0, Qt.UserRole)
            
        self.files_tree.clear()
        for path in sorted(self.tracked_paths):
            if self.is_path_ignored(path):
                continue
            name = os.path.basename(path)
            if os.path.isdir(path):
                parent_item = QTreeWidgetItem(self.files_tree, [name])
                parent_item.setData(0, Qt.UserRole, path)
                parent_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                for f in sorted(self.get_all_files_in_path(path)):
                    child_item = QTreeWidgetItem(parent_item, [os.path.relpath(f, path)])
                    child_item.setData(0, Qt.UserRole, f)
                    child_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                    if f == current_selection:
                        self.files_tree.setCurrentItem(child_item)
            else:
                item = QTreeWidgetItem(self.files_tree, [name])
                item.setData(0, Qt.UserRole, path)
                item.setToolTip(0, path)
                item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                if path == current_selection:
                    self.files_tree.setCurrentItem(item)

        self.filter_files_tree(self.file_search_box.text())

    def filter_files_tree(self, text):
        search_term = text.lower()
        root = self.files_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            is_match = search_term in item.text(0).lower()
            
            if item.childCount() > 0:
                has_visible_child = False
                for j in range(item.childCount()):
                    child = item.child(j)
                    child_is_match = search_term in child.text(0).lower()
                    child.setHidden(not child_is_match)
                    if not child.isHidden():
                        has_visible_child = True
                item.setHidden(not has_visible_child)
            else:
                item.setHidden(not is_match)

        self.files_tree.expandAll()

    def update_monitoring(self):
        if self.watcher_thread: self.watcher_thread.stop(); self.watcher_thread = None
        self.poll_timer.stop()
        if not self.tracked_paths: return
        freq = self.freq_combo.currentText()
        if freq == "On Change":
            self.watcher_thread = WatcherThread(self.tracked_paths)
            self.watcher_thread.file_changed.connect(self.on_file_event)
            self.watcher_thread.start()
        else:
            intervals = {"Every 30 Seconds": 30000, "Every 1 Minute": 60000, "Every 5 Minutes": 300000}
            self.poll_timer.start(intervals[freq])

    def poll_files(self):
        all_tracked_files = self.get_all_tracked_files()
        for file_path in all_tracked_files:
            if not os.path.exists(file_path):
                if file_path in self.file_hashes:
                    self.handle_file_deletion(file_path)
                continue

            current_hash = self.hash_file(file_path)
            last_hash = self.file_hashes.get(file_path)

            if last_hash is None:
                self.handle_file_creation(file_path)
            elif current_hash and current_hash != last_hash:
                self.handle_file_change(file_path, current_hash)

    def on_file_event(self, path):
        if self.is_path_ignored(path):
            return
        self.poll_files()

    def handle_file_change(self, file_path, new_hash):
        save_snapshot(file_path, "auto-snapshot on file change")
        self.file_hashes[file_path] = new_hash
        if hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "sum changed",
                f"'{os.path.basename(file_path)}' was updated. a new snapshot has been created.",
                QSystemTrayIcon.Information,
                3000
            )
        self.refresh_versions_if_selected(file_path)

    def handle_file_creation(self, file_path):
        self.track_new_file(file_path, "auto-snapshot for new file")
        self.update_files_tree()

    def handle_file_deletion(self, file_path):
        self.file_hashes.pop(file_path, None)
        self.update_files_tree()

    def refresh_versions_if_selected(self, file_path):
        current_item = self.files_tree.currentItem()
        if not current_item: return

        selected_path = current_item.data(0, Qt.UserRole)
        
        if selected_path == file_path:
            self.show_versions()
        elif os.path.isdir(selected_path) and file_path.startswith(selected_path):
            self.show_versions()

    def show_versions(self):
        current_item = self.files_tree.currentItem()
        if not current_item: return

        file_path = current_item.data(0, Qt.UserRole)
        if not file_path or not os.path.isfile(file_path):
            self.versions_list.clear()
            return
            
        selected_version_path = None
        if self.versions_list.currentItem():
            selected_version_path = self.versions_list.currentItem().data(0, Qt.UserRole)

        self.versions_list.clear()
        self.preview_box.clear(); self.note_edit.clear()
        self.restore_btn.setEnabled(False); self.restore_as_copy_btn.setEnabled(False); self.delete_snap_btn.setEnabled(False); self.save_note_btn.setEnabled(False)
        
        self.notes = load_notes(file_path)
        versions = list_snapshots(file_path)
        
        new_item_to_select = None
        for v_name in versions:
            display = format_snap_time(v_name)
            version_item = QTreeWidgetItem(self.versions_list, [display])
            version_item.setToolTip(0, v_name)
            version_path = os.path.join(get_snapshot_dir(file_path), v_name)
            version_item.setData(0, Qt.UserRole, version_path)
            version_item.setData(0, Qt.UserRole + 1, file_path)
            version_item.setData(0, Qt.UserRole + 2, v_name)
            if version_path == selected_version_path:
                new_item_to_select = version_item
        
        if new_item_to_select:
            self.versions_list.setCurrentItem(new_item_to_select)
        
        self.filter_versions_list(self.version_search_box.text())

    def filter_versions_list(self, text):
        search_term = text.lower()
        iterator = QTreeWidgetItemIterator(self.versions_list)
        while iterator.value():
            item = iterator.value()
            snap_name = item.data(0, Qt.UserRole + 2)
            note = self.notes.get(snap_name, "")
            is_visible = search_term in item.text(0).lower() or search_term in note.lower()
            item.setHidden(not is_visible)
            iterator += 1

    def show_preview(self, item):
        if not item: return
        version_path = item.data(0, Qt.UserRole)
        orig_path = item.data(0, Qt.UserRole + 1)
        ext = os.path.splitext(version_path)[1].lower()
        if ext in ['.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.log']:
            diff_html = get_text_diff(version_path, orig_path)
            self.preview_box.setHtml(diff_html)
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif']:
            self.preview_box.setHtml(f'<body style="text-align:center;"><img src="file:///{version_path}"><p style="color:white;">{os.path.basename(version_path)}</p></body>')
        else:
            file_size = os.path.getsize(version_path)
            self.preview_box.setText(f"no preview available.\n\nFile: {os.path.basename(version_path)}\nSize: {file_size / 1024:.2f} KB")

    def restore_version(self):
        current_item = self.versions_list.currentItem()
        if not current_item: return
        version_path = current_item.data(0, Qt.UserRole)
        orig_path = current_item.data(0, Qt.UserRole + 1)
        reply = QMessageBox.question(self, "you sure vro?", "this will overwrite the current file. a snapshot will be saved first. continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            latest_snap = get_latest_snapshot(orig_path)
            curr_hash = self.hash_file(orig_path)
            latest_hash = self.hash_file(latest_snap) if latest_snap else None
            if curr_hash != latest_hash:
                save_snapshot(orig_path, "auto-snapshot before restore")
            shutil.copy2(version_path, orig_path)
            self.file_hashes[orig_path] = self.hash_file(orig_path)
            QMessageBox.information(self, "yay", "file restored successfully.")
            self.refresh_versions_if_selected(orig_path)

    def restore_as_copy(self):
        current_item = self.versions_list.currentItem()
        if not current_item: return
        
        version_path = current_item.data(0, Qt.UserRole)
        orig_path = current_item.data(0, Qt.UserRole + 1)
        
        base, ext = os.path.splitext(orig_path)
        suggested_name = f"{base}_restored_copy{ext}"

        save_path, _ = QFileDialog.getSaveFileName(self, "save restored Copy As...", suggested_name)

        if save_path:
            try:
                shutil.copy2(version_path, save_path)
                QMessageBox.information(self, "success", f"restored copy saved to:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "error", f"could not save file:\n{e}")

    def delete_snapshot(self):
        curr = self.versions_list.currentItem()
        if not curr: return
        version_path = curr.data(0, Qt.UserRole); snap_name = curr.data(0, Qt.UserRole + 2); orig_path = curr.data(0, Qt.UserRole+1)
        reply = QMessageBox.question(self, "delete snapshot", f"are you sure you want to permanently delete this snapshot?\n{snap_name}",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            os.remove(version_path)
            notes = load_notes(orig_path)
            if snap_name in notes: del notes[snap_name]; save_notes(orig_path, notes)
            self.show_versions()

    def save_note(self):
        curr = self.versions_list.currentItem()
        if not curr: return
        snap_name = curr.data(0, Qt.UserRole + 2); orig_path = curr.data(0, Qt.UserRole + 1)
        notes = load_notes(orig_path)
        notes[snap_name] = self.note_edit.toPlainText()
        save_notes(orig_path, notes)
        QMessageBox.information(self, "note saved", "snapshot note has been updated.")

    def load_note(self):
        curr = self.versions_list.currentItem()
        if not curr: self.note_edit.clear(); return
        snap_name = curr.data(0, Qt.UserRole + 2); orig_path = curr.data(0, Qt.UserRole + 1)
        self.notes = load_notes(orig_path)
        self.note_edit.setPlainText(self.notes.get(snap_name, ""))

    def import_snapshots(self):
        curr_file_item = self.files_tree.currentItem()
        if not curr_file_item or not os.path.isfile(curr_file_item.data(0, Qt.UserRole)):
            QMessageBox.warning(self, "no file selected", "please select a file to import snapshots for.")
            return
        orig_path = curr_file_item.data(0, Qt.UserRole)
        zip_path, _ = QFileDialog.getOpenFileName(self, "select snapshot zip to import", "", "Zip Files (*.zip)")
        if not zip_path: return
        with zipfile.ZipFile(zip_path, 'r') as zipf: zipf.extractall(get_snapshot_dir(orig_path))
        self.show_versions()
        QMessageBox.information(self, "import complete", "snapshots have been imported.")

    def export_snapshots(self):
        curr_file_item = self.files_tree.currentItem()
        if not curr_file_item or not os.path.isfile(curr_file_item.data(0, Qt.UserRole)): return
        orig_path = curr_file_item.data(0, Qt.UserRole)
        snap_dir = get_snapshot_dir(orig_path)
        zip_path, _ = QFileDialog.getSaveFileName(self, "save snapshot zip", f"{os.path.basename(orig_path)}_snapshots.zip", "Zip Files (*.zip)")
        if not zip_path: return
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for f in os.listdir(snap_dir): zipf.write(os.path.join(snap_dir, f), f)
        QMessageBox.information(self, "export complete", f"snapshots exported to {zip_path}")

    def is_path_ignored(self, path):
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        return False

    def get_all_files_in_path(self, path):
        files = []
        if os.path.isdir(path):
            for root, dirs, fnames in os.walk(path, topdown=True):
                dirs[:] = [d for d in dirs if not self.is_path_ignored(os.path.join(root, d))]
                
                for fname in fnames:
                    file_path = os.path.join(root, fname)
                    if not self.is_path_ignored(file_path):
                        files.append(file_path)
        return files

    def get_all_tracked_files(self):
        all_files = set()
        for path in self.tracked_paths:
            if self.is_path_ignored(path):
                continue
            if os.path.isfile(path):
                all_files.add(path)
            elif os.path.isdir(path):
                all_files.update(self.get_all_files_in_path(path))
        return all_files

    def hash_file(self, path):
        try:
            sha256 = hashlib.sha256()
            with open(path, "rb") as f:
                for b in iter(lambda: f.read(4096), b""): sha256.update(b)
            return sha256.hexdigest()
        except Exception: return None

    def save_settings(self):
        settings = {
            "tracked_paths": self.tracked_paths
        }
        try:
            with open(SETTINGS_PATH, 'w') as f:
                json.dump(settings, f, indent=4)
        except IOError:
            print("sum happened, could not save settings.")

    def load_settings(self):
        if not os.path.exists(SETTINGS_PATH):
            return
        try:
            with open(SETTINGS_PATH, 'r') as f:
                settings_data = json.load(f)
            
            if isinstance(settings_data, list):
                self.tracked_paths = settings_data
            else:
                self.tracked_paths = settings_data.get("tracked_paths", [])

            self.refresh_all_tracking()
        except (IOError, json.JSONDecodeError):
            print("sum happened, could not load settings.")
            self.tracked_paths = []

    def load_ignore_patterns(self):
        if os.path.exists(IGNORE_FILE_PATH):
            with open(IGNORE_FILE_PATH, 'r') as f:
                self.ignore_patterns = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        else:
            self.ignore_patterns = []

    def refresh_all_tracking(self):
        self.file_hashes.clear()
        all_files = self.get_all_tracked_files()
        for file_path in all_files:
            if os.path.exists(file_path):
                self.file_hashes[file_path] = self.hash_file(file_path)

        self.update_files_tree()
        self.update_monitoring()

    def closeEvent(self, event):
        if self.is_quitting:
            self.save_settings()
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
            self.poll_timer.stop()
            if self.watcher_thread:
                self.watcher_thread.stop()
                self.watcher_thread.wait()
            event.accept()
        else:
            event.ignore()
            self.hide()
            if hasattr(self, 'tray_icon'):
                self.tray_icon.showMessage(
                    "bkpr is still running",
                    "minimized to system tray.",
                    QSystemTrayIcon.Information,
                    1500
                )

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_STYLESHEET)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())