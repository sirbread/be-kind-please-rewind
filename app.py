import sys
import os
import shutil
import difflib
import hashlib
from datetime import datetime
import re
import json
import zipfile
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QFileDialog, QSplitter,
    QListWidgetItem, QLabel, QTextBrowser, QComboBox, QMessageBox,
    QMenu, QAction, QInputDialog, QSpinBox, QCheckBox, QDialog,
    QDialogButtonBox, QTextEdit
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

def current_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def make_snapshot_name(orig_name):
    base, ext = os.path.splitext(orig_name)
    return f"{base}_{current_timestamp()}{ext}"

def save_snapshot(file_path, label=None, notes=None):
    if not os.path.exists(file_path): return None
    snapdir = get_snapshot_dir(file_path)
    dest = os.path.join(snapdir, make_snapshot_name(os.path.basename(file_path)))
    shutil.copy2(file_path, dest)
    
    # Save metadata
    save_snapshot_metadata(dest, label, notes)
    
    return dest

def list_snapshots(file_path):
    snapdir = get_snapshot_dir(file_path)
    if not os.path.exists(snapdir):
        return []
    all_files = [os.path.join(snapdir, f) for f in os.listdir(snapdir)]
    # Filter out metadata files
    files = [f for f in all_files if not f.endswith('.meta.json')]
    def snapkey(f):
        m = re.search(r'_(\d{8}_\d{6}_\d{6})', os.path.basename(f))
        if m:
            try:
                return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S_%f")
            except ValueError:
                pass
        return datetime.fromtimestamp(os.path.getmtime(f))
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
    return snaps[0] if snaps else None

def get_snapshot_metadata_path(snapshot_path):
    """Get the metadata file path for a snapshot."""
    return snapshot_path + ".meta.json"

def save_snapshot_metadata(snapshot_path, label=None, notes=None):
    """Save metadata for a snapshot."""
    metadata = {
        "created": datetime.now().isoformat(),
        "label": label or "",
        "notes": notes or ""
    }
    meta_path = get_snapshot_metadata_path(snapshot_path)
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

def load_snapshot_metadata(snapshot_path):
    """Load metadata for a snapshot."""
    meta_path = get_snapshot_metadata_path(snapshot_path)
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"created": "", "label": "", "notes": ""}

def update_snapshot_metadata(snapshot_path, label=None, notes=None):
    """Update metadata for an existing snapshot."""
    metadata = load_snapshot_metadata(snapshot_path)
    if label is not None:
        metadata["label"] = label
    if notes is not None:
        metadata["notes"] = notes
    meta_path = get_snapshot_metadata_path(snapshot_path)
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

def delete_snapshot(snapshot_path):
    """Delete a snapshot and its metadata."""
    try:
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
        meta_path = get_snapshot_metadata_path(snapshot_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)
        return True
    except Exception:
        return False

def delete_old_snapshots(file_path, keep_count=10):
    """Delete old snapshots, keeping only the specified number."""
    snapshots = list_snapshots(file_path)
    if len(snapshots) <= keep_count:
        return 0
    
    to_delete = snapshots[keep_count:]
    deleted_count = 0
    for snapshot in to_delete:
        if delete_snapshot(snapshot):
            deleted_count += 1
    return deleted_count

def export_snapshots(file_path, export_path):
    """Export all snapshots for a file to a zip archive."""
    try:
        snapshots = list_snapshots(file_path)
        if not snapshots:
            return False
        
        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add original file info
            info = {
                "original_file": file_path,
                "export_date": datetime.now().isoformat(),
                "file_hash": hash_file_path(file_path)
            }
            zf.writestr("export_info.json", json.dumps(info, indent=2))
            
            # Add snapshots and metadata
            for snapshot in snapshots:
                snapshot_name = os.path.basename(snapshot)
                zf.write(snapshot, f"snapshots/{snapshot_name}")
                
                # Add metadata if exists
                meta_path = get_snapshot_metadata_path(snapshot)
                if os.path.exists(meta_path):
                    zf.write(meta_path, f"snapshots/{snapshot_name}.meta.json")
        
        return True
    except Exception:
        return False

def import_snapshots(file_path, import_path):
    """Import snapshots from a zip archive."""
    try:
        with zipfile.ZipFile(import_path, 'r') as zf:
            # Verify it's a valid export
            if "export_info.json" not in zf.namelist():
                return False
            
            snap_dir = get_snapshot_dir(file_path)
            
            # Extract snapshots
            for item in zf.namelist():
                if item.startswith("snapshots/") and item != "snapshots/":
                    zf.extract(item, snap_dir)
                    # Move from snapshots/ subdirectory to snap_dir
                    extracted_path = os.path.join(snap_dir, item)
                    final_path = os.path.join(snap_dir, os.path.basename(item))
                    if extracted_path != final_path:
                        shutil.move(extracted_path, final_path)
            
            # Clean up empty snapshots directory
            snapshots_subdir = os.path.join(snap_dir, "snapshots")
            if os.path.exists(snapshots_subdir) and not os.listdir(snapshots_subdir):
                os.rmdir(snapshots_subdir)
        
        return True
    except Exception:
        return False

class SnapshotMetadataDialog(QDialog):
    """Dialog for editing snapshot metadata."""
    def __init__(self, parent=None, snapshot_path=None):
        super().__init__(parent)
        self.snapshot_path = snapshot_path
        self.setWindowTitle("Edit Snapshot Metadata")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Label
        layout.addWidget(QLabel("Label:"))
        self.label_edit = QInputDialog()
        self.label_input = QInputDialog.getText(self, "", "")[1]  # Get the QLineEdit
        self.label_edit = QInputDialog()
        
        # Create our own input fields
        self.label_field = QInputDialog()
        
        # Simpler approach - just use text inputs
        layout.addWidget(QLabel("Label:"))
        from PyQt5.QtWidgets import QLineEdit
        self.label_edit = QLineEdit()
        layout.addWidget(self.label_edit)
        
        layout.addWidget(QLabel("Notes:"))
        self.notes_edit = QTextEdit()
        layout.addWidget(self.notes_edit)
        
        # Load existing metadata
        if snapshot_path:
            metadata = load_snapshot_metadata(snapshot_path)
            self.label_edit.setText(metadata.get("label", ""))
            self.notes_edit.setText(metadata.get("notes", ""))
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_metadata(self):
        return {
            "label": self.label_edit.text(),
            "notes": self.notes_edit.toPlainText()
        }

class SnapshotManagementDialog(QDialog):
    """Dialog for managing snapshots (delete old ones, import/export)."""
    def __init__(self, parent=None, file_path=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle("Manage Snapshots")
        self.setModal(True)
        self.resize(400, 200)
        
        layout = QVBoxLayout(self)
        
        # Delete old snapshots
        delete_layout = QHBoxLayout()
        delete_layout.addWidget(QLabel("Keep last"))
        self.keep_count = QSpinBox()
        self.keep_count.setMinimum(1)
        self.keep_count.setMaximum(100)
        self.keep_count.setValue(10)
        delete_layout.addWidget(self.keep_count)
        delete_layout.addWidget(QLabel("snapshots"))
        delete_layout.addStretch()
        
        self.delete_btn = QPushButton("Delete Old Snapshots")
        self.delete_btn.clicked.connect(self.delete_old_snapshots)
        delete_layout.addWidget(self.delete_btn)
        
        layout.addLayout(delete_layout)
        
        # Import/Export
        io_layout = QHBoxLayout()
        self.export_btn = QPushButton("Export Snapshots")
        self.export_btn.clicked.connect(self.export_snapshots)
        io_layout.addWidget(self.export_btn)
        
        self.import_btn = QPushButton("Import Snapshots")
        self.import_btn.clicked.connect(self.import_snapshots)
        io_layout.addWidget(self.import_btn)
        
        layout.addLayout(io_layout)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        # Update snapshot count
        self.update_info()
    
    def update_info(self):
        if self.file_path:
            snapshots = list_snapshots(self.file_path)
            count = len(snapshots)
            self.setWindowTitle(f"Manage Snapshots ({count} total)")
    
    def delete_old_snapshots(self):
        if not self.file_path:
            return
        
        keep_count = self.keep_count.value()
        deleted = delete_old_snapshots(self.file_path, keep_count)
        
        if deleted > 0:
            QMessageBox.information(self, "Success", f"Deleted {deleted} old snapshots.")
            self.update_info()
        else:
            QMessageBox.information(self, "No Action", "No snapshots were deleted.")
    
    def export_snapshots(self):
        if not self.file_path:
            return
        
        export_path, _ = QFileDialog.getSaveFileName(
            self, "Export Snapshots", 
            f"{os.path.basename(self.file_path)}_snapshots.zip",
            "ZIP files (*.zip)"
        )
        
        if export_path:
            if export_snapshots(self.file_path, export_path):
                QMessageBox.information(self, "Success", "Snapshots exported successfully.")
            else:
                QMessageBox.warning(self, "Error", "Failed to export snapshots.")
    
    def import_snapshots(self):
        if not self.file_path:
            return
        
        import_path, _ = QFileDialog.getOpenFileName(
            self, "Import Snapshots", "", "ZIP files (*.zip)"
        )
        
        if import_path:
            if import_snapshots(self.file_path, import_path):
                QMessageBox.information(self, "Success", "Snapshots imported successfully.")
                self.update_info()
                # Signal parent to refresh
                if hasattr(self.parent(), 'refresh_current_file'):
                    self.parent().refresh_current_file()
            else:
                QMessageBox.warning(self, "Error", "Failed to import snapshots.")

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
        self.setGeometry(100, 100, 1200, 800)
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
        self.add_btn = QPushButton("+ add file to track")
        self.add_btn.clicked.connect(self.add_file)
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["On Change", "Every 30 Seconds", "Every 1 Minute", "Every 5 Minutes"])
        self.freq_combo.currentTextChanged.connect(self.update_monitoring)
        top.addWidget(self.add_btn)
        top.addStretch()
        top.addWidget(QLabel("tracking frequency:"))
        top.addWidget(self.freq_combo)

        files_panel = QWidget()
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(0,0,0,0)
        files_layout.addWidget(QLabel("tracked files", objectName="header"))
        self.files_list = QListWidget()
        self.files_list.itemClicked.connect(self.show_versions)
        self.files_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files_list.customContextMenuRequested.connect(self.show_files_context_menu)
        files_layout.addWidget(self.files_list)

        versions_panel = QWidget()
        versions_layout = QVBoxLayout(versions_panel)
        versions_layout.setContentsMargins(0,0,0,0)
        versions_layout.addWidget(QLabel("version history", objectName="header"))
        self.versions_list = QListWidget()
        self.versions_list.itemClicked.connect(self.show_preview)
        self.versions_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.versions_list.customContextMenuRequested.connect(self.show_versions_context_menu)
        versions_layout.addWidget(self.versions_list)

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
        splitter.setSizes([250, 250, 700])

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.restore_btn = QPushButton("restore selected version")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self.restore_version)
        bottom.addWidget(self.restore_btn)

        layout.addLayout(top)
        layout.addWidget(splitter)
        layout.addLayout(bottom)

    def show_files_context_menu(self, position):
        """Show context menu for files list."""
        item = self.files_list.itemAt(position)
        if item:
            menu = QMenu()
            
            manage_action = QAction("Manage Snapshots", self)
            manage_action.triggered.connect(lambda: self.manage_snapshots(item))
            menu.addAction(manage_action)
            
            remove_action = QAction("Remove from Tracking", self)
            remove_action.triggered.connect(lambda: self.remove_file_from_tracking(item))
            menu.addAction(remove_action)
            
            menu.exec_(self.files_list.mapToGlobal(position))
    
    def show_versions_context_menu(self, position):
        """Show context menu for versions list."""
        item = self.versions_list.itemAt(position)
        if item:
            menu = QMenu()
            
            edit_action = QAction("Edit Label/Notes", self)
            edit_action.triggered.connect(lambda: self.edit_snapshot_metadata(item))
            menu.addAction(edit_action)
            
            delete_action = QAction("Delete Snapshot", self)
            delete_action.triggered.connect(lambda: self.delete_snapshot_item(item))
            menu.addAction(delete_action)
            
            menu.exec_(self.versions_list.mapToGlobal(position))
    
    def manage_snapshots(self, file_item):
        """Open snapshot management dialog."""
        file_path = file_item.data(Qt.UserRole)
        dialog = SnapshotManagementDialog(self, file_path)
        dialog.exec_()
    
    def remove_file_from_tracking(self, file_item):
        """Remove a file from tracking."""
        file_path = file_item.data(Qt.UserRole)
        filename = os.path.basename(file_path)
        
        reply = QMessageBox.question(
            self, "Remove File", 
            f"Remove '{filename}' from tracking?\n\nThis will stop tracking the file but won't delete existing snapshots.",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Remove from tracked files
            if file_path in self.tracked:
                del self.tracked[file_path]
            
            # Remove from UI
            row = self.files_list.row(file_item)
            self.files_list.takeItem(row)
            
            # Clear versions and preview
            self.versions_list.clear()
            self.preview_box.clear()
            self.restore_btn.setEnabled(False)
            
            # Update monitoring
            self.update_monitoring()
    
    def edit_snapshot_metadata(self, version_item):
        """Edit metadata for a snapshot."""
        snapshot_path = version_item.data(Qt.UserRole)
        dialog = SnapshotMetadataDialog(self, snapshot_path)
        
        if dialog.exec_() == QDialog.Accepted:
            metadata = dialog.get_metadata()
            update_snapshot_metadata(snapshot_path, metadata["label"], metadata["notes"])
            
            # Update the display
            self.refresh_versions_display()
    
    def delete_snapshot_item(self, version_item):
        """Delete a specific snapshot."""
        snapshot_path = version_item.data(Qt.UserRole)
        filename = os.path.basename(snapshot_path)
        
        reply = QMessageBox.question(
            self, "Delete Snapshot", 
            f"Delete snapshot '{filename}'?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if delete_snapshot(snapshot_path):
                # Remove from UI
                row = self.versions_list.row(version_item)
                self.versions_list.takeItem(row)
                
                # Clear preview if this was the selected item
                if self.versions_list.currentItem() is None:
                    self.preview_box.clear()
                    self.restore_btn.setEnabled(False)
                
                QMessageBox.information(self, "Success", "Snapshot deleted successfully.")
            else:
                QMessageBox.warning(self, "Error", "Failed to delete snapshot.")
    
    def refresh_versions_display(self):
        """Refresh the versions list display."""
        current_file_item = self.files_list.currentItem()
        if current_file_item:
            self.show_versions(current_file_item)
    
    def refresh_current_file(self):
        """Refresh the current file's versions (called from dialogs)."""
        self.refresh_versions_display()

    def add_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "select file to track")
        if file_path and file_path not in self.tracked:
            save_snapshot(file_path)
            new_hash = self.hash_file(file_path)
            self.tracked[file_path] = new_hash
            item = QListWidgetItem(os.path.basename(file_path))
            item.setToolTip(file_path)
            item.setData(Qt.UserRole, file_path)
            self.files_list.addItem(item)
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
        save_snapshot(file_path)
        self.tracked[file_path] = new_hash
        curr_item = self.files_list.currentItem()
        if curr_item and curr_item.data(Qt.UserRole) == file_path:
            self.show_versions(curr_item)

    def show_versions(self, item):
        self.versions_list.clear()
        self.preview_box.clear()
        self.restore_btn.setEnabled(False)
        file_path = item.data(Qt.UserRole)
        versions = list_snapshots(file_path)
        for v in versions:
            # Get metadata
            metadata = load_snapshot_metadata(v)
            
            # Create display text
            time_str = format_snap_time(os.path.basename(v))
            display_parts = [time_str]
            
            if metadata.get("label"):
                display_parts.append(f"[{metadata['label']}]")
            
            display_text = " ".join(display_parts)
            
            version_item = QListWidgetItem(display_text)
            version_item.setToolTip(f"File: {os.path.basename(v)}\nNotes: {metadata.get('notes', 'No notes')}")
            version_item.setData(Qt.UserRole, v)
            version_item.setData(Qt.UserRole + 1, file_path)
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
            #only save a snapshot if the current file differs from the latest snapshot
            latest_snap = get_latest_snapshot(orig_path)
            curr_hash = self.hash_file(orig_path)
            latest_hash = self.hash_file(latest_snap) if latest_snap else None
            if curr_hash != latest_hash:
                save_snapshot(orig_path)
            shutil.copy2(version_path, orig_path)
            save_snapshot(orig_path)
            self.tracked[orig_path] = self.hash_file(orig_path)
            QMessageBox.information(self, "yay", "file restored successfully.")
            self.show_versions(self.files_list.currentItem())

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