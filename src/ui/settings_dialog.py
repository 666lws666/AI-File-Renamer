"""Settings dialog — placeholder, will be fully built in Phase 2."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QComboBox, QSpinBox, QTextEdit,
    QCheckBox, QFileDialog,
)
from PySide6.QtCore import Qt
from loguru import logger


class SettingsDialog(QDialog):
    """Application settings dialog with tabs."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("设置")
        self.resize(550, 450)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_general_tab(), "通用")
        self.tabs.addTab(self._create_ai_tab(), "AI 服务商")
        self.tabs.addTab(self._create_org_tab(), "文件整理")
        layout.addWidget(self.tabs)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("<b>通用设置</b>"))
        layout.addWidget(QLabel("语言:"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItems(["zh (中文)", "en (English)"])
        layout.addWidget(self.cmb_lang)

        layout.addWidget(QLabel("最大文件大小 (MB):"))
        self.spin_max_size = QSpinBox()
        self.spin_max_size.setRange(1, 500)
        self.spin_max_size.setValue(50)
        layout.addWidget(self.spin_max_size)

        layout.addWidget(QLabel("发送给AI的最大字符数:"))
        self.spin_max_chars = QSpinBox()
        self.spin_max_chars.setRange(500, 16000)
        self.spin_max_chars.setValue(4000)
        layout.addWidget(self.spin_max_chars)

        layout.addStretch()
        return w

    def _create_ai_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("<b>AI 服务商设置</b>"))

        layout.addWidget(QLabel("服务商:"))
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItems(["deepseek", "openai", "claude"])
        self.cmb_provider.currentTextChanged.connect(self._on_provider_changed)
        layout.addWidget(self.cmb_provider)

        layout.addWidget(QLabel("API Key:"))
        row_key = QHBoxLayout()
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        row_key.addWidget(self.txt_api_key)
        btn_show = QPushButton("显示")
        btn_show.setCheckable(True)
        btn_show.toggled.connect(lambda checked: self.txt_api_key.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        ))
        row_key.addWidget(btn_show)
        layout.addLayout(row_key)

        layout.addWidget(QLabel("Base URL:"))
        self.txt_base_url = QLineEdit()
        layout.addWidget(self.txt_base_url)

        layout.addWidget(QLabel("模型:"))
        self.txt_model = QLineEdit()
        layout.addWidget(self.txt_model)

        btn_test = QPushButton("🔗 测试连接")
        btn_test.clicked.connect(self._test_connection)
        layout.addWidget(btn_test)

        layout.addWidget(QLabel("系统提示词:"))
        self.txt_system_prompt = QTextEdit()
        self.txt_system_prompt.setMaximumHeight(120)
        layout.addWidget(self.txt_system_prompt)

        layout.addStretch()
        return w

    def _create_org_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("<b>文件自动整理</b>"))

        self.chk_organize = QCheckBox("重命名后自动归类文件")
        layout.addWidget(self.chk_organize)

        layout.addWidget(QLabel("归类规则:"))
        self.cmb_org_rule = QComboBox()
        self.cmb_org_rule.addItems([
            "by_type (按文件类型)", "by_date (按日期)",
            "by_project (按项目)", "by_category (按分类)"
        ])
        layout.addWidget(self.cmb_org_rule)

        layout.addWidget(QLabel("目标文件夹:"))
        row_dir = QHBoxLayout()
        self.txt_org_root = QLineEdit()
        row_dir.addWidget(self.txt_org_root)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_org_dir)
        row_dir.addWidget(btn_browse)
        layout.addLayout(row_dir)

        layout.addStretch()
        return w

    def _load_settings(self):
        config = self.app.app_config
        self.cmb_provider.setCurrentText(config.provider)
        self.txt_api_key.setText(config.api_key)
        self.txt_base_url.setText(config.base_url)
        self.txt_model.setText(config.model)
        self.spin_max_size.setValue(config.max_file_size_mb)
        self.spin_max_chars.setValue(config.max_content_chars)
        self.chk_organize.setChecked(config.auto_organize)
        self.txt_org_root.setText(config.organization_root)

    def _on_provider_changed(self, provider: str):
        defaults = {
            "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
            "openai": ("https://api.openai.com/v1", "gpt-4o"),
            "claude": ("https://api.anthropic.com", "claude-sonnet-4-20250514"),
        }
        if provider in defaults:
            url, model = defaults[provider]
            self.txt_base_url.setText(url)
            self.txt_model.setText(model)

    def _test_connection(self):
        logger.info("测试 AI 连接...")
        from ..core.ai_engine import AIEngine

        # Temporarily apply current form values to config
        config = self.app.app_config
        config.provider = self.cmb_provider.currentText()
        config.api_key = self.txt_api_key.text()
        config.base_url = self.txt_base_url.text()
        config.model = self.txt_model.text()

        try:
            engine = AIEngine(config)
            ok, msg = engine.test_connection()
        except Exception as e:
            ok, msg = False, str(e)

        if ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "连接成功", msg)
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "连接失败", f"无法连接到 AI 服务:\n{msg}")

    def _browse_org_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if folder:
            self.txt_org_root.setText(folder)

    def _on_save(self):
        config = self.app.app_config
        config.provider = self.cmb_provider.currentText()
        config.api_key = self.txt_api_key.text()
        config.base_url = self.txt_base_url.text()
        config.model = self.txt_model.text()
        config.max_file_size_mb = self.spin_max_size.value()
        config.max_content_chars = self.spin_max_chars.value()
        config.auto_organize = self.chk_organize.isChecked()
        config.organization_root = self.txt_org_root.text()
        self.app.save_config()
        logger.info("设置已保存")
        self.accept()
