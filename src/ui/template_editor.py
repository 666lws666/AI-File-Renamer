"""Template editor dialog — create and edit naming templates."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDialogButtonBox, QListWidget, QListWidgetItem, QComboBox,
    QPushButton, QGroupBox, QMessageBox, QWidget,
)
from PySide6.QtCore import Qt
from loguru import logger

from ..models.template import NamingTemplate, TemplateField, BUILTIN_FIELDS
from ..config import save_config


class TemplateEditorDialog(QDialog):
    """Dialog for creating and editing naming templates."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("模板管理")
        self.resize(550, 450)
        self._templates: list[NamingTemplate] = []
        self._setup_ui()
        self._load_templates()

    def _setup_ui(self):
        layout = QHBoxLayout(self)

        # === Left: Template list ===
        left = QVBoxLayout()

        self.template_list = QListWidget()
        self.template_list.currentRowChanged.connect(self._on_select_template)
        left.addWidget(QLabel("<b>模板列表</b>"))
        left.addWidget(self.template_list)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("新建")
        self.btn_new.clicked.connect(self._new_template)
        btn_row.addWidget(self.btn_new)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._delete_template)
        btn_row.addWidget(self.btn_delete)
        left.addLayout(btn_row)

        layout.addLayout(left, 1)

        # === Right: Template editor ===
        right = QVBoxLayout()

        # Name
        right.addWidget(QLabel("模板名称:"))
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("例如: 会议记录模板")
        right.addWidget(self.txt_name)

        # Pattern
        right.addWidget(QLabel("格式模式:"))
        pat_row = QHBoxLayout()
        self.txt_pattern = QLineEdit()
        self.txt_pattern.setPlaceholderText("{date}_{title}.{ext}")
        pat_row.addWidget(self.txt_pattern)
        right.addLayout(pat_row)
        lbl_hint = QLabel("可用变量: {date} {title} {type} {tags} {language} {ext} {original_name}")
        lbl_hint.setStyleSheet("color: #666; font-size: 11px;")
        lbl_hint.setWordWrap(True)
        right.addWidget(lbl_hint)

        # Separator
        right.addWidget(QLabel("分隔符:"))
        self.cmb_separator = QComboBox()
        self.cmb_separator.addItems(["_", "-", " ", ".", "+", ""])
        self.cmb_separator.setCurrentText("_")
        right.addWidget(self.cmb_separator)

        # Date format
        right.addWidget(QLabel("日期格式:"))
        self.cmb_datefmt = QComboBox()
        self.cmb_datefmt.addItems([
            "%Y-%m-%d (2025-01-15)",
            "%Y%m%d (20250115)",
            "%Y-%m (2025-01)",
            "%Y (2025)",
            "%y%m%d (250115)",
        ])
        right.addWidget(self.cmb_datefmt)

        # Preview
        right.addWidget(QLabel("<b>实时预览</b>"))
        self.lbl_preview = QLabel("2025-07-26_示例文件名.txt")
        self.lbl_preview.setStyleSheet("background: #f5f5f5; padding: 8px; border: 1px solid #ddd; border-radius: 4px;")
        right.addWidget(self.lbl_preview)

        # Connect preview updates
        self.txt_pattern.textChanged.connect(self._update_preview)
        self.cmb_separator.currentTextChanged.connect(self._update_preview)

        right.addStretch()
        layout.addLayout(right, 2)

        # === Buttons ===
        btn_box = QHBoxLayout()
        btn_save = QPushButton("💾 保存模板")
        btn_save.clicked.connect(self._save_current)
        btn_box.addStretch()
        btn_box.addWidget(btn_save)
        right.addLayout(btn_box)

    def _load_templates(self):
        """Load templates from config."""
        try:
            import json
            from ..config import get_templates_dir

            tmpl_dir = get_templates_dir()
            self._templates = []

            # Load default built-in template
            default = NamingTemplate(
                name="默认模板",
                pattern="{date}_{title}.{ext}",
                separator="_",
                date_format="%Y-%m-%d",
            )
            self._templates.append(default)

            # Load saved templates
            for f in sorted(tmpl_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    self._templates.append(NamingTemplate(**data))
                except Exception as e:
                    logger.warning(f"模板加载失败: {f} — {e}")

            self._refresh_list()

        except Exception as e:
            logger.error(f"模板加载失败: {e}")

    def _refresh_list(self):
        """Refresh the template list widget."""
        self.template_list.clear()
        for tmpl in self._templates:
            self.template_list.addItem(f"{tmpl.name}  [{tmpl.pattern}]")

        if self._templates:
            self.template_list.setCurrentRow(0)

    def _on_select_template(self, idx: int):
        """Display selected template for editing."""
        if idx < 0 or idx >= len(self._templates):
            return

        tmpl = self._templates[idx]
        self.txt_name.setText(tmpl.name)
        self.txt_pattern.setText(tmpl.pattern)
        self.cmb_separator.setCurrentText(tmpl.separator)

        # Find date format
        for i in range(self.cmb_datefmt.count()):
            if self.cmb_datefmt.itemText(i).startswith(tmpl.date_format):
                self.cmb_datefmt.setCurrentIndex(i)
                break

        self._update_preview()

    def _update_preview(self):
        """Update the live preview label."""
        pattern = self.txt_pattern.text() or "{date}_{title}.{ext}"
        sep = self.cmb_separator.currentText()

        # Create a mock filename
        preview = pattern.replace("{date}", "2025-07-26")
        preview = preview.replace("{title}", "示例文件名")
        preview = preview.replace("{type}", "report")
        preview = preview.replace("{tags}", "AI_工具")
        preview = preview.replace("{language}", "zh")
        preview = preview.replace("{ext}", "txt")
        preview = preview.replace("{original_name}", "原始文件名")

        self.lbl_preview.setText(preview)

    def _new_template(self):
        """Create a new template."""
        new_tmpl = NamingTemplate(
            name="新模板",
            pattern="{date}_{title}.{ext}",
        )
        self._templates.append(new_tmpl)
        self._refresh_list()
        self.template_list.setCurrentRow(len(self._templates) - 1)
        logger.info("创建新模板")

    def _delete_template(self):
        """Delete the selected template."""
        idx = self.template_list.currentRow()
        if idx < 0:
            return
        if idx == 0:
            QMessageBox.warning(self, "提示", "不能删除默认模板。")
            return

        reply = QMessageBox.question(self, "确认", "确定删除此模板？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self._templates[idx]
            self._refresh_list()
            logger.info("模板已删除")

    def _save_current(self):
        """Save the currently editing template."""
        idx = self.template_list.currentRow()
        if idx < 0:
            return

        tmpl = self._templates[idx]
        tmpl.name = self.txt_name.text() or "未命名模板"
        tmpl.pattern = self.txt_pattern.text() or "{date}_{title}.{ext}"
        tmpl.separator = self.cmb_separator.currentText()

        # Extract date format
        fmt_text = self.cmb_datefmt.currentText()
        tmpl.date_format = fmt_text.split(" ")[0]

        # Save to disk
        import json
        from ..config import get_templates_dir
        tmpl_file = get_templates_dir() / f"{tmpl.id}.json"
        with open(tmpl_file, "w", encoding="utf-8") as f:
            json.dump(tmpl.model_dump(), f, indent=2, ensure_ascii=False)

        self._refresh_list()
        QMessageBox.information(self, "已保存", f"模板「{tmpl.name}」已保存。")
        logger.info(f"模板已保存: {tmpl.name}")
