"""Watch folder panel — manage and monitor watched folders."""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem,
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QDialogButtonBox, QCheckBox, QFileDialog,
    QMessageBox, QGroupBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush
from loguru import logger

from ..models.watch_config import WatchConfig, WatchMode
from ..models.file_item import FileItem, FileStatus
from ..core.folder_watcher import FolderWatcher
from ..core.file_scanner import FileScanner
from ..core.content_extractor import extract
from ..core.ai_engine import AIEngine


class WatchFolderPanel(QWidget):
    """Panel for managing watched folders that auto-process new files."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.watcher = FolderWatcher()
        self.watcher.file_ready.connect(self._on_file_ready)
        self.watcher.error_occurred.connect(lambda msg: self._log_activity(f"❌ {msg}"))

        # Processing queue
        self._pending_files: list[str] = []

        self._setup_ui()
        self._load_saved_configs()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<h2>文件夹监控</h2>"))
        layout.addWidget(QLabel(
            "监控指定的文件夹，当有新文件出现时自动进行 AI 分析和重命名。"
        ))

        # === Watch list ===
        grp = QGroupBox("已监控的文件夹")
        grp_layout = QVBoxLayout(grp)

        self.watch_list = QListWidget()
        self.watch_list.currentRowChanged.connect(self._on_select)
        grp_layout.addWidget(self.watch_list)

        # Buttons
        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕ 添加监控")
        btn_add.clicked.connect(self._add_watch)
        btn_row.addWidget(btn_add)

        btn_remove = QPushButton("🗑 移除")
        btn_remove.clicked.connect(self._remove_watch)
        btn_row.addWidget(btn_remove)

        btn_row.addStretch()
        self.lbl_status = QLabel("监控服务未启动")
        self.lbl_status.setStyleSheet("color: #999;")
        btn_row.addWidget(self.lbl_status)
        grp_layout.addLayout(btn_row)

        layout.addWidget(grp)

        # === Recent activity ===
        act_grp = QGroupBox("最近活动")
        act_layout = QVBoxLayout(act_grp)
        self.activity_list = QListWidget()
        act_layout.addWidget(self.activity_list)
        layout.addWidget(act_grp)

        layout.addStretch()

    def _load_saved_configs(self):
        """Load watch configs from disk."""
        try:
            import json
            from ..config import CONFIG_DIR
            config_file = CONFIG_DIR / "watch_folders.json"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for d in data:
                    config = WatchConfig(**d)
                    if config.active and os.path.isdir(config.source_dir):
                        self._add_to_list(config)
                        self.watcher.add_watch(config)
                if self.watcher.get_watched_folders():
                    self.watcher.start()
                self._update_status()
        except Exception as e:
            logger.error(f"加载监控配置失败: {e}")

    def _save_configs(self):
        """Save watch configs to disk."""
        import json
        from ..config import CONFIG_DIR
        config_file = CONFIG_DIR / "watch_folders.json"
        try:
            configs = [c.model_dump() for c in self.watcher.get_watched_folders()]
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(configs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存监控配置失败: {e}")

    def _add_to_list(self, config: WatchConfig):
        """Add a watch config to the list widget."""
        mode = "自动应用" if config.mode == WatchMode.AUTO_APPLY else "先审阅"
        text = f"{config.source_dir}  [{mode}]"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, config.id)
        if not config.active:
            item.setForeground(QBrush(QColor("#999")))
        self.watch_list.addItem(item)

    def _on_select(self, row: int):
        pass  # Future: show config details

    def _add_watch(self):
        """Open dialog to add a new watch folder."""
        dialog = WatchFolderDialog(self.app, self)
        if dialog.exec():
            config = dialog.get_config()
            if not os.path.isdir(config.source_dir):
                QMessageBox.warning(self, "错误", f"文件夹不存在: {config.source_dir}")
                return
            self.watcher.add_watch(config)
            self._add_to_list(config)
            self._save_configs()
            self._update_status()
            self._log_activity(f"开始监控: {config.source_dir}")

    def _remove_watch(self):
        """Remove selected watch folder."""
        row = self.watch_list.currentRow()
        if row < 0:
            return
        item = self.watch_list.item(row)
        config_id = item.data(Qt.UserRole)

        self.watcher.remove_watch(config_id)
        self.watch_list.takeItem(row)
        self._save_configs()
        self._update_status()
        self._log_activity("已停止监控")

    def _update_status(self):
        if self.watcher.is_running:
            count = len(self.watcher.get_watched_folders())
            self.lbl_status.setText(f"🟢 正在监控 {count} 个文件夹")
            self.lbl_status.setStyleSheet("color: #2e7d32; font-weight: bold;")
        else:
            self.lbl_status.setText("监控服务未启动")
            self.lbl_status.setStyleSheet("color: #999;")

    def _on_file_ready(self, file_item):
        """Called when a new file is stable and ready for processing."""
        self._log_activity(f"发现新文件: {file_item.original_name}")

        # For auto-apply mode, process immediately
        # Find the config for this file's parent directory
        for config in self.watcher.get_watched_folders():
            if str(file_item.parent_dir).startswith(str(config.source_dir)):
                if config.mode == WatchMode.AUTO_APPLY:
                    self._auto_process(file_item)
                break

    def _auto_process(self, item):
        """Automatically extract, analyze, and rename a new file."""
        try:
            # Extract
            extract(item, max_chars=self.app.app_config.max_content_chars)

            if item.status != FileStatus.EXTRACTED:
                self._log_activity(f"提取失败: {item.original_name} — {item.error_message}")
                return

            # AI analyze
            engine = AIEngine(self.app.app_config)
            engine.suggest(item)

            if item.status != FileStatus.SUGGESTED:
                self._log_activity(f"AI分析失败: {item.original_name} — {item.error_message}")
                return

            # Auto rename
            from ..core.rename_engine import RenameEngine
            renamer = RenameEngine()
            renamer.execute([item])

            if item.status == FileStatus.APPLIED:
                self._log_activity(f"Auto renamed: {item.suggested_name}")
            else:
                self._log_activity(f"Rename failed: {item.original_name}")

        except Exception as e:
            logger.error(f"Auto process failed: {e}")
            self._log_activity(f"Auto process error: {e}")

        except Exception as e:
            logger.error(f"自动处理失败: {file_path} — {e}")
            self._log_activity(f"❌ 处理失败: {os.path.basename(file_path)}")

    def _log_activity(self, message: str):
        """Add a message to the activity log."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{ts}] {message}")
        self.activity_list.insertItem(0, item)
        # Keep last 100 entries
        while self.activity_list.count() > 100:
            self.activity_list.takeItem(self.activity_list.count() - 1)

    def cleanup(self):
        """Stop the watcher when the app closes."""
        self.watcher.stop()


class WatchFolderDialog(QDialog):
    """Dialog for configuring a new watch folder."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("添加文件夹监控")
        self.resize(450, 250)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)

        # Folder
        row = QHBoxLayout()
        self.txt_folder = QLineEdit()
        self.txt_folder.setPlaceholderText("选择要监控的文件夹...")
        row.addWidget(self.txt_folder)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(btn_browse)
        layout.addRow("文件夹:", row)

        # Mode
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("先审阅再重命名（推荐）", WatchMode.REVIEW_FIRST)
        self.cmb_mode.addItem("自动重命名（无需确认）", WatchMode.AUTO_APPLY)
        layout.addRow("模式:", self.cmb_mode)

        # Recursive
        self.chk_recursive = QCheckBox("包含子文件夹")
        self.chk_recursive.setChecked(True)
        layout.addRow("", self.chk_recursive)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要监控的文件夹")
        if folder:
            self.txt_folder.setText(folder)

    def _validate(self):
        folder = self.txt_folder.text().strip()
        if not folder:
            QMessageBox.warning(self, "提示", "请选择一个文件夹。")
            return
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "提示", f"文件夹不存在: {folder}")
            return
        self.accept()

    def get_config(self) -> WatchConfig:
        return WatchConfig(
            source_dir=self.txt_folder.text().strip(),
            mode=self.cmb_mode.currentData(),
            recursive=self.chk_recursive.isChecked(),
        )
