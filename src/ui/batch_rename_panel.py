"""Batch rename panel — the main workflow panel."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QMessageBox,
)
from PySide6.QtCore import QThread, Signal, Qt
from loguru import logger

from ..core.file_scanner import FileScanner
from ..core.content_extractor import extract
from ..core.ai_engine import AIEngine
from ..core.rename_engine import RenameEngine
from ..core.rename_history import RenameHistory
from ..models.file_item import FileItem, FileStatus
from .preview_table import PreviewTable


class BatchRenamePanel(QWidget):
    """Main workspace for batch file renaming."""

    def __init__(self, app):
        super().__init__()
        self.app = app

        # Engines
        self.scanner = FileScanner(max_file_size_mb=app.app_config.max_file_size_mb)
        self.history = RenameHistory()
        self.rename_engine = RenameEngine(self.history)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # === Header ===
        layout.addWidget(QLabel("<h2>批量重命名</h2>"))

        # === Toolbar ===
        toolbar = QHBoxLayout()

        self.btn_scan_analyze = QPushButton("🔍 扫描并AI分析")
        self.btn_scan_analyze.setStyleSheet("QPushButton { padding: 8px 16px; font-size: 14px; }")
        self.btn_scan_analyze.clicked.connect(self._on_scan_and_analyze)
        toolbar.addWidget(self.btn_scan_analyze)

        self.btn_apply = QPushButton("✅ 应用重命名")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("QPushButton { padding: 8px 16px; font-size: 14px; }")
        self.btn_apply.clicked.connect(self._on_apply_rename)
        toolbar.addWidget(self.btn_apply)

        self.btn_undo = QPushButton("↩ 撤销上次")
        self.btn_undo.clicked.connect(self.undo_last)
        toolbar.addWidget(self.btn_undo)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # === Progress bar ===
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # === Preview table ===
        self.table = PreviewTable()
        layout.addWidget(self.table, 1)

        # === Status bar ===
        status_layout = QHBoxLayout()
        self.lbl_status = QLabel("请添加文件或文件夹开始")
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        self.lbl_count = QLabel("")
        status_layout.addWidget(self.lbl_count)
        layout.addLayout(status_layout)

    # === Public API ===

    def add_files(self, files: list[str]):
        """Add individual files to the table."""
        items = self.scanner.scan_files(files)
        self.table.add_items(items)
        self._update_status(f"已添加 {len(files)} 个文件，共 {len(self.table.items)} 个")

    def add_folder(self, folder: str):
        """Scan a folder and add files to the table."""
        items = self.scanner.scan_directory(folder)
        self.table.set_items(items)
        self._update_status(f"从 {folder} 扫描到 {len(items)} 个文件")

    def undo_last(self):
        """Undo the most recent rename batch."""
        batch_id = self.history.get_last_batch_id()
        if not batch_id:
            QMessageBox.information(self, "撤销", "没有可撤销的操作。")
            return

        reply = QMessageBox.question(
            self, "确认撤销",
            f"将撤销最近一批重命名操作，确定吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            count = self.rename_engine.undo_last()
            QMessageBox.information(self, "撤销完成", f"已恢复 {count} 个文件。")
            self.table.refresh()
            self._update_status(f"已撤销 {count} 个文件")

    def on_settings_changed(self):
        """Called when settings are saved."""
        self.scanner = FileScanner(max_file_size_mb=self.app.app_config.max_file_size_mb)
        logger.info("扫描器设置已更新")

    # === Pipeline ===

    def _on_scan_and_analyze(self):
        """Run the full scan → extract → AI pipeline."""
        items = self.table.items
        if not items:
            QMessageBox.warning(self, "提示", "请先添加文件或文件夹。")
            return

        # Check API key
        config = self.app.app_config
        if not config.api_key:
            QMessageBox.warning(
                self, "需要 API Key",
                "请先在设置中配置 AI 服务商的 API Key（菜单：工具 → 设置）。"
            )
            return

        self._run_pipeline(items)

    def _run_pipeline(self, items: list[FileItem]):
        """Execute pipeline in a background thread."""
        self.btn_scan_analyze.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(items) * 2)  # Extract + AI stages

        self.worker = PipelineWorker(items, self.app.app_config)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_updated.connect(self._on_file_updated)
        self.worker.finished.connect(self._on_pipeline_complete)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current: int, stage: str):
        self.progress.setValue(current)
        self._update_status(f"{stage}... {current}/{self.progress.maximum() // 2}")

    def _on_file_updated(self, idx: int):
        self.table.update_row(idx)
        # Update suggested count
        suggested = len(self.table.get_suggested_items())
        self.lbl_count.setText(f"{suggested} 个就绪 / 共 {len(self.table.items)} 个")

    def _on_pipeline_complete(self, items: list[FileItem]):
        self.table.set_items(items)
        self.table.refresh()
        self.progress.setVisible(False)
        self.btn_scan_analyze.setEnabled(True)

        suggested = len(self.table.get_suggested_items())
        failed = len([i for i in items if i.status == FileStatus.FAILED])

        if suggested > 0:
            self.btn_apply.setEnabled(True)
            self._update_status(f"分析完成！{suggested} 个文件就绪，{failed} 个失败。请预览后点击「应用重命名」")
        else:
            self._update_status(f"分析完成，但没有成功获得建议。{failed} 个失败。请检查 API Key 和网络连接。")

    def _on_error(self, error_msg: str):
        self.progress.setVisible(False)
        self.btn_scan_analyze.setEnabled(True)
        self._update_status(f"错误: {error_msg}")
        QMessageBox.critical(self, "处理错误", error_msg)

    def _on_apply_rename(self):
        """Apply confirmed renames."""
        items = self.table.get_suggested_items()
        if not items:
            QMessageBox.information(self, "提示", "没有可以重命名的文件。")
            return

        reply = QMessageBox.question(
            self, "确认重命名",
            f"将对 {len(items)} 个文件执行重命名操作。\n\n"
            f"重命名后可通过「撤销上次」恢复。\n\n确定要继续吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            batch_id = self.rename_engine.execute(items)
            self.table.refresh()
            applied = len([i for i in items if i.status == FileStatus.APPLIED])
            QMessageBox.information(
                self, "重命名完成",
                f"成功重命名 {applied} 个文件。\n批次ID: {batch_id[:8]}..."
            )
            self.btn_apply.setEnabled(False)
            self._update_status(f"已重命名 {applied} 个文件。点击「撤销上次」可恢复。")

        except Exception as e:
            logger.error(f"重命名执行失败: {e}")
            QMessageBox.critical(self, "错误", f"重命名失败: {e}")

    def _update_status(self, msg: str):
        self.lbl_status.setText(msg)


class PipelineWorker(QThread):
    """Background worker for scan → extract → AI pipeline."""

    progress = Signal(int, str)          # current, stage name
    file_updated = Signal(int)           # row index
    finished = Signal(list)              # final items
    error_occurred = Signal(str)         # error message

    def __init__(self, items: list[FileItem], config):
        super().__init__()
        self.items = items
        self.config = config

    def run(self):
        try:
            total = len(self.items)

            # === Stage 1: Extract content ===
            for i, item in enumerate(self.items):
                if item.status in (FileStatus.APPLIED, FileStatus.IGNORED):
                    continue
                self.progress.emit(i, "提取内容")
                extract(item, max_chars=self.config.max_content_chars)
                self.file_updated.emit(i)

            # === Stage 2: AI suggestion ===
            ai_engine = AIEngine(self.config)
            for i, item in enumerate(self.items):
                if item.status != FileStatus.EXTRACTED:
                    continue
                self.progress.emit(total + i, "AI 分析")
                ai_engine.suggest(item)
                self.file_updated.emit(i)

            self.finished.emit(self.items)

        except Exception as e:
            logger.error(f"Pipeline worker error: {e}")
            self.error_occurred.emit(str(e))
