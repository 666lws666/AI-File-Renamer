"""Main window — menu bar, toolbar, central stacked panel."""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QStatusBar, QMenuBar, QMenu,
    QStackedWidget, QLabel, QPushButton,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from .batch_rename_panel import BatchRenamePanel
from .watch_folder_panel import WatchFolderPanel
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("AI File Renamer — 文件智能重命名")
        self.resize(1100, 700)

        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_area()
        self._setup_status_bar()

    def _setup_menu_bar(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("文件(&F)")
        add_files_action = QAction("添加文件...", self)
        add_files_action.triggered.connect(self._add_files)
        file_menu.addAction(add_files_action)

        add_folder_action = QAction("添加文件夹...", self)
        add_folder_action.triggered.connect(self._add_folder)
        file_menu.addAction(add_folder_action)

        file_menu.addSeparator()
        exit_action = QAction("退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menu_bar.addMenu("编辑(&E)")
        undo_action = QAction("撤销上次重命名", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._undo_last)
        edit_menu.addAction(undo_action)

        # Tools menu
        tools_menu = menu_bar.addMenu("工具(&T)")
        templates_action = QAction("模板管理...", self)
        templates_action.triggered.connect(self._open_template_editor)
        tools_menu.addAction(templates_action)

        tools_menu.addSeparator()
        settings_action = QAction("设置...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)

        # Help menu
        help_menu = menu_bar.addMenu("帮助(&H)")
        about_action = QAction("关于...", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Add Files
        btn_add_files = QPushButton("📄 添加文件")
        btn_add_files.clicked.connect(self._add_files)
        toolbar.addWidget(btn_add_files)

        # Add Folder
        btn_add_folder = QPushButton("📁 添加文件夹")
        btn_add_folder.clicked.connect(self._add_folder)
        toolbar.addWidget(btn_add_folder)

        toolbar.addSeparator()

        # View switch
        self.btn_view_rename = QPushButton("📝 重命名")
        self.btn_view_rename.clicked.connect(lambda: self.stacked.setCurrentIndex(0))
        toolbar.addWidget(self.btn_view_rename)

        self.btn_view_watch = QPushButton("👁 监控")
        self.btn_view_watch.clicked.connect(lambda: self.stacked.setCurrentIndex(1))
        toolbar.addWidget(self.btn_view_watch)

        toolbar.addSeparator()

        # Undo
        btn_undo = QPushButton("↩ 撤销")
        btn_undo.clicked.connect(self._undo_last)
        toolbar.addWidget(btn_undo)

        toolbar.addSeparator()

        # Settings
        btn_settings = QPushButton("⚙ 设置")
        btn_settings.clicked.connect(self._open_settings)
        toolbar.addWidget(btn_settings)

    def _setup_central_area(self):
        self.stacked = QStackedWidget()

        # Panel 0: batch rename
        self.batch_panel = BatchRenamePanel(self.app)
        self.stacked.addWidget(self.batch_panel)

        # Panel 1: watch folders
        self.watch_panel = WatchFolderPanel(self.app)
        self.stacked.addWidget(self.watch_panel)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked)
        self.setCentralWidget(central)

    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)

    # --- Actions ---

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要重命名的文件", "",
            "支持的文件 (*.pdf *.docx *.doc *.xlsx *.xls *.pptx *.ppt "
            "*.txt *.md *.csv *.html *.jpg *.jpeg *.png *.gif *.bmp *.webp "
            "*.mp4 *.mov *.mkv);;所有文件 (*.*)"
        )
        if files:
            self.batch_panel.add_files(files)
            self.status_label.setText(f"已添加 {len(files)} 个文件")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.batch_panel.add_folder(folder)
            self.status_label.setText(f"正在扫描: {folder}")

    def _undo_last(self):
        self.batch_panel.undo_last()

    def _open_settings(self):
        dialog = SettingsDialog(self.app, self)
        if dialog.exec():
            self.batch_panel.on_settings_changed()

    def _open_template_editor(self):
        from .template_editor import TemplateEditorDialog
        dialog = TemplateEditorDialog(self.app, self)
        dialog.exec()

    def _show_about(self):
        QMessageBox.about(
            self, "关于 AI File Renamer",
            "<h3>AI File Renamer v0.1.0</h3>"
            "<p>基于 AI 的智能文件重命名工具</p>"
            "<p>使用 DeepSeek / OpenAI / Claude 云端 API 分析文件内容，"
            "生成清晰、可搜索、规范化的文件名。</p>"
        )

    def closeEvent(self, event):
        """Clean up resources on close."""
        self.watch_panel.cleanup()
        super().closeEvent(event)
