import sys
import os
import shutil
import difflib
import hashlib
from datetime import datetime
import re
import json
import zipfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QFileDialog, QSplitter,
    QListWidgetItem, QLabel, QTextBrowser, QComboBox, QMessageBox,
    QInputDialog, QLineEdit, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

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

SNAPSHOTS_BASE = os.path.join(get_documents_dir(), "be-kind-please-rewind", "snapshots")
os.makedirs(SNAPSHOTS_BASE, exist_ok=True)

DARK_STYLESHEET = """
QWidget { background-color: #2b2b2b; color: #ffffff; font-family: Segoe UI, Arial, sans-serif; font-size: 10pt; }
QMainWindow { background-color: #2b2b2b; }
QListWidget { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; padding: 5px; }
QListWidget::item { padding: 5px; }
QListWidget::item:selected { background-color: #0078d7; color: #ffffff; }
QTextBrowser { background-color: #3c3f41; border: 1px solid #4f5254; border-radius: 4px; }
QPushButton { background-color: #4f5254; border: 1px solid #5f6264; padding: 6px 12px; border-radius: 4px; }
QPushButton:hover { background-color: #5f6264; }
QPushButton:pressed { background-color: #0078d7; }
QComboBox { background-color: #4f5254; border: 1px solid #5f6264; padding: 5px; border-radius: 4px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #4f5254; border: 1px solid #5f6264; selection-background-color: #0078d7; }
QLabel#header { font-weight: bold; padding: 5px 0px; font-size: 11pt; }
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
            return json.load(f)
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
    if not os.path.exists(snapdir):
        return []
    files = [f for f in os.listdir(snapdir) if f != "notes.json"]
    def snapkey(f):
        m = re.search(r'_(\d{8}_\d{6}_\d{6})', f)
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f")
            except ValueError:
                pass
        return datetime.fromtimestamp(os.path.getmtime(os.path.join(snapdir, f)))
    return sorted(files, key=snapkey, reverse=True)

def format_snap_time(fname):
    m = re.search(r'_(\d{8}_\d{6}_\d{6})', fname)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f")
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        except ValueError:
            pass
    return fname

def get_text_diff(snap, curr):
    try:
        with open(snap, encoding="utf-8", errors="ignore") as f: left = f.readlines()
        with open(curr, encoding="utf-8", errors="ignore") as f: right = f.readlines()
    except Exception as e:
        return f"<pre>Could not read files: {e}</pre>"
    seq = difflib.SequenceMatcher(None, left, right)
    l, r = ['<table class="content-table"><tr><th>&nbsp;</th><th>Selected Version</th></tr>'], \
           ['<table class="content-table"><tr><th>&nbsp;</th><th>Current File</th></tr>']
    for opcode, i1,i2, j1,j2 in seq.get_opcodes():
        if opcode == "equal":
            for i, j in zip(range(i1,i2), range(j1,j2)):
                l.append(f'<tr><td class="lineno">{i+1}</td><td><pre>{left[i]}</pre></td></tr>')
                r.append(f'<tr><td class="lineno">{j+1}</td><td><pre>{right[j]}</pre></td></tr>')
        elif opcode == "replace":
            for i in range(i2-i1):
                l.append(f'<tr class="diff_sub"><td class="lineno">{i1+i+1}</td><td><pre>{left[i1+i]}</pre></td></tr>')
            for j in range(j2-j1):
                r.append(f'<tr class="diff_add"><td class="lineno">{j1+j+1}</td><td><pre>{right[j1+j]}</pre></td></tr>')
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
    l.append('</table>')
    r.append('</table>')
    return DIFF_CSS + f'<table class="layout-table"><tr><td>{"".join(l)}</td><td>{"".join(r)}</td></tr></table>'

def get_image_preview(image_path, size=QSize(256,256)):
    try:
        img = Image.open(image_path)
        img.thumbnail((size.width(), size.height()))
        img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
    except Exception:
        return None

def get_latest_snapshot(file_path):
    snaps = list_snapshots(file_path)
    if not snaps: return None
    return os.path.join(get_snapshot_dir(file_path), snaps[0])

class ChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.last = {}
    def on_modified(self, event):
        if not event.is_directory:
            path = event.src_path
            now = datetime.now().timestamp()
            if path in self.last and now - self.last[path] < 1: return
            self.last[path] = now
            self.callback(path)

class WatcherThread(QThread):
    file_changed = pyqtSignal(str)
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.observer = Observer()
    def run(self):
        handler = ChangeHandler(self.file_changed.emit)
        dirs = set(os.path.dirname(p) for p in self.paths)
        for d in dirs:
            self.observer.schedule(handler, d, recursive=False)
        self.observer.start()
        try:
            while not self.isInterruptionRequested():
                self.msleep(200)
        finally:
            self.observer.stop()
            self.observer.join()
    def stop(self):
        self.requestInterruption()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("be kind, please rewind")
        self.setGeometry(100, 100, 1400, 900)
        self.tracked = {}
        self.watcher_thread = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_files)
        self.init_ui()
        self.update_monitoring()

    def init_ui(self):
        main = QWidget()
        layout = QVBoxLayout(main)
        self.setCentralWidget(main)

        top = QHBoxLayout()
        self.add_btn = QPushButton("+ add file")
        self.add_btn.clicked.connect(self.add_file)
        self.remove_btn = QPushButton("- remove file")
        self.remove_btn.clicked.connect(self.remove_file)
        self.remove_btn.setEnabled(False)
        self.import_btn = QPushButton("import snapshots")
        self.import_btn.clicked.connect(self.import_snapshots)
        self.export_btn = QPushButton("export snapshots")
        self.export_btn.clicked.connect(self.export_snapshots)
        self.export_btn.setEnabled(False)
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["On Change", "Every 30 Seconds", "Every 1 Minute", "Every 5 Minutes"])
        self.freq_combo.currentTextChanged.connect(self.update_monitoring)
        top.addWidget(self.add_btn)
        top.addWidget(self.remove_btn)
        top.addWidget(self.import_btn)
        top.addWidget(self.export_btn)
        top.addStretch()
        top.addWidget(QLabel("tracking frequency:"))
        top.addWidget(self.freq_combo)

        files_panel = QWidget()
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(0,0,0,0)
        files_layout.addWidget(QLabel("tracked files", objectName="header"))
        self.files_list = QListWidget()
        self.files_list.itemClicked.connect(self.on_file_selected)
        files_layout.addWidget(self.files_list)

        versions_panel = QWidget()
        versions_layout = QVBoxLayout(versions_panel)
        versions_layout.setContentsMargins(0,0,0,0)
        versions_layout.addWidget(QLabel("version history", objectName="header"))
        self.versions_list = QListWidget()
        self.versions_list.itemClicked.connect(self.on_version_selected)
        versions_layout.addWidget(self.versions_list)
        
        notes_panel = QVBoxLayout()
        notes_panel.addWidget(QLabel("Snapshot Note", objectName="header"))
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("add a note for the selected snapshot...")
        self.save_note_btn = QPushButton("save note")
        self.save_note_btn.clicked.connect(self.save_note)
        self.save_note_btn.setEnabled(False)
        notes_panel.addWidget(self.note_edit)
        notes_panel.addWidget(self.save_note_btn)
        versions_layout.addLayout(notes_panel)


        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.addWidget(QLabel("preview / diff", objectName="header"))
        self.preview_box = QTextBrowser()
        self.preview_box.setOpenExternalLinks(False)
        preview_layout.addWidget(self.preview_box)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(files_panel)
        splitter.addWidget(versions_panel)
        splitter.addWidget(preview_panel)
        splitter.setSizes([250, 350, 800])

        bottom = QHBoxLayout()
        self.delete_snap_btn = QPushButton("delete snapshot")
        self.delete_snap_btn.setEnabled(False)
        self.delete_snap_btn.clicked.connect(self.delete_snapshot)
        bottom.addWidget(self.delete_snap_btn)
        bottom.addStretch()
        self.restore_btn = QPushButton("restore selected version")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self.restore_version)
        bottom.addWidget(self.restore_btn)

        layout.addLayout(top)
        layout.addWidget(splitter)
        layout.addLayout(bottom)

    def on_file_selected(self, item):
        self.show_versions(item)
        self.remove_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def on_version_selected(self, item):
        self.show_preview(item)
        self.delete_snap_btn.setEnabled(True)
        self.save_note_btn.setEnabled(True)
        self.load_note()

    def add_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "select file to track")
        if file_path and file_path not in self.tracked:
            note, ok = QInputDialog.getText(self, "initial snapshot note", "enter a note for the first snapshot (optional):")
            if ok:
                save_snapshot(file_path, note)
                new_hash = self.hash_file(file_path)
                self.tracked[file_path] = new_hash
                item = QListWidgetItem(os.path.basename(file_path))
                item.setToolTip(file_path)
                item.setData(Qt.UserRole, file_path)
                self.files_list.addItem(item)
                self.update_monitoring()

    def remove_file(self):
        curr = self.files_list.currentItem()
        if not curr: return
        file_path = curr.data(Qt.UserRole)
        reply = QMessageBox.question(self, "remove file", 
            f"are you sure you want to stop tracking {os.path.basename(file_path)}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            reply_del = QMessageBox.question(self, "delete snapshots",
                "do you also want to delete all associated snapshots for this file?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply_del == QMessageBox.Yes:
                shutil.rmtree(get_snapshot_dir(file_path), ignore_errors=True)

            self.files_list.takeItem(self.files_list.row(curr))
            del self.tracked[file_path]
            self.versions_list.clear()
            self.preview_box.clear()
            self.note_edit.clear()
            self.remove_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.restore_btn.setEnabled(False)
            self.delete_snap_btn.setEnabled(False)
            self.save_note_btn.setEnabled(False)
            self.update_monitoring()

    def update_monitoring(self):
        if self.watcher_thread: self.watcher_thread.stop(); self.watcher_thread = None
        self.poll_timer.stop()
        if not self.tracked: return
        freq = self.freq_combo.currentText()
        if freq == "On Change":
            self.watcher_thread = WatcherThread(list(self.tracked.keys()))
            self.watcher_thread.file_changed.connect(self.on_file_event)
            self.watcher_thread.start()
        else:
            intervals = {"Every 30 Seconds": 30000, "Every 1 Minute": 60000, "Every 5 Minutes": 300000}
            self.poll_timer.start(intervals[freq])

    def poll_files(self):
        for path, last_hash in list(self.tracked.items()):
            curr_hash = self.hash_file(path)
            if curr_hash and curr_hash != last_hash:
                self.do_file_change(path, curr_hash)

    def on_file_event(self, file_path):
        self.poll_files()

    def do_file_change(self, file_path, new_hash):
        save_snapshot(file_path, "auto-snapshot on file change")
        self.tracked[file_path] = new_hash
        curr_item = self.files_list.currentItem()
        if curr_item and curr_item.data(Qt.UserRole) == file_path:
            self.show_versions(curr_item)

    def show_versions(self, item):
        self.versions_list.clear()
        self.preview_box.clear()
        self.note_edit.clear()
        self.restore_btn.setEnabled(False)
        self.delete_snap_btn.setEnabled(False)
        self.save_note_btn.setEnabled(False)
        file_path = item.data(Qt.UserRole)
        versions = list_snapshots(file_path)
        for v_name in versions:
            display = format_snap_time(v_name)
            version_item = QListWidgetItem(display)
            version_item.setToolTip(v_name)
            version_item.setData(Qt.UserRole, os.path.join(get_snapshot_dir(file_path), v_name))
            version_item.setData(Qt.UserRole + 1, file_path)
            version_item.setData(Qt.UserRole + 2, v_name)
            self.versions_list.addItem(version_item)

    def show_preview(self, item):
        if not item: return
        version_path = item.data(Qt.UserRole)
        orig_path = item.data(Qt.UserRole + 1)
        ext = os.path.splitext(version_path)[1].lower()
        if ext in ['.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.log']:
            diff_html = get_text_diff(version_path, orig_path)
            self.preview_box.setHtml(diff_html)
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif']:
            pixmap = get_image_preview(version_path)
            if pixmap:
                self.preview_box.clear()
                self.preview_box.setHtml(f'<body style="text-align:center;"><img src="file:///{version_path}"><p style="color:white;">{os.path.basename(version_path)}</p></body>')
            else:
                self.preview_box.setText(f"could not load preview for {os.path.basename(version_path)}")
        else:
            file_size = os.path.getsize(version_path)
            self.preview_box.setText(f"no preview available.\n\nFile: {os.path.basename(version_path)}\nSize: {file_size / 1024:.2f} KB")
        self.restore_btn.setEnabled(True)

    def restore_version(self):
        current_item = self.versions_list.currentItem()
        if not current_item: return
        version_path = current_item.data(Qt.UserRole)
        orig_path = current_item.data(Qt.UserRole + 1)
        reply = QMessageBox.question(self, "you sure vro?", "this will overwrite the current file. a snapshot will be saved first if needed. continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            latest_snap = get_latest_snapshot(orig_path)
            curr_hash = self.hash_file(orig_path)
            latest_hash = self.hash_file(latest_snap) if latest_snap else None
            if curr_hash != latest_hash:
                save_snapshot(orig_path, "auto-snapshot before restore")
            shutil.copy2(version_path, orig_path)
            self.tracked[orig_path] = self.hash_file(orig_path)
            QMessageBox.information(self, "yay", "file restored successfully.")
            self.show_versions(self.files_list.currentItem())

    def delete_snapshot(self):
        curr = self.versions_list.currentItem()
        if not curr: return
        version_path = curr.data(Qt.UserRole)
        snap_name = curr.data(Qt.UserRole + 2)
        orig_path = curr.data(Qt.UserRole+1)
        
        reply = QMessageBox.question(self, "delete snapshot", f"are you sure you want to delete this snapshot?\n{snap_name}",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            os.remove(version_path)
            notes = load_notes(orig_path)
            if snap_name in notes:
                del notes[snap_name]
                save_notes(orig_path, notes)
            self.show_versions(self.files_list.currentItem())

    def save_note(self):
        curr = self.versions_list.currentItem()
        if not curr: return
        snap_name = curr.data(Qt.UserRole + 2)
        orig_path = curr.data(Qt.UserRole + 1)
        notes = load_notes(orig_path)
        notes[snap_name] = self.note_edit.toPlainText()
        save_notes(orig_path, notes)
        QMessageBox.information(self, "note saved", "snapshot note has been updated.")

    def load_note(self):
        curr = self.versions_list.currentItem()
        if not curr: self.note_edit.clear(); return
        snap_name = curr.data(Qt.UserRole + 2)
        orig_path = curr.data(Qt.UserRole + 1)
        notes = load_notes(orig_path)
        self.note_edit.setPlainText(notes.get(snap_name, ""))

    def import_snapshots(self):
        curr_file_item = self.files_list.currentItem()
        if not curr_file_item:
            QMessageBox.warning(self, "no file selected", "please select a tracked file to import snapshots for.")
            return

        orig_path = curr_file_item.data(Qt.UserRole)
        zip_path, _ = QFileDialog.getOpenFileName(self, "select snapshot zip to import", "", "Zip Files (*.zip)")
        if not zip_path: return

        snap_dir = get_snapshot_dir(orig_path)
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(snap_dir)
        
        self.show_versions(curr_file_item)
        QMessageBox.information(self, "import complete", "snapshots have been imported.")

    def export_snapshots(self):
        curr_file_item = self.files_list.currentItem()
        if not curr_file_item: return
        orig_path = curr_file_item.data(Qt.UserRole)
        snap_dir = get_snapshot_dir(orig_path)
        
        zip_path, _ = QFileDialog.getSaveFileName(self, "save snapshot zip", f"{os.path.basename(orig_path)}_snapshots.zip", "Zip Files (*.zip)")
        if not zip_path: return

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for f in os.listdir(snap_dir):
                zipf.write(os.path.join(snap_dir, f), f)
        
        QMessageBox.information(self, "export complete", f"snapshots exported to {zip_path}")

    def hash_file(self, path):
        try:
            sha256 = hashlib.sha256()
            with open(path, "rb") as f:
                for b in iter(lambda: f.read(4096), b""):
                    sha256.update(b)
            return sha256.hexdigest()
        except Exception:
            return None

    def closeEvent(self, event):
        self.poll_timer.stop()
        if self.watcher_thread:
            self.watcher_thread.stop()
            self.watcher_thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())