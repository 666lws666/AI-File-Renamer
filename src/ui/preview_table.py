"""Preview table — QTableView showing original/suggested filenames."""

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QTableView, QHeaderView, QStyledItemDelegate, QLineEdit

from ..models.file_item import FileItem, FileStatus


class FileItemTableModel(QAbstractTableModel):
    """Custom table model for displaying FileItem objects."""

    COLUMNS = ["状态", "原文件名", "建议文件名", "类型", "大小"]

    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[FileItem] = []

    @property
    def items(self) -> list[FileItem]:
        return self._items

    def set_items(self, items: list[FileItem]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def add_items(self, items: list[FileItem]):
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items) + len(items) - 1)
        self._items.extend(items)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None

        item = self._items[index.row()]

        if role == Qt.DisplayRole:
            col = index.column()
            if col == 0:  # Status
                return self._status_text(item.status)
            elif col == 1:  # Original
                return item.original_name
            elif col == 2:  # Suggested
                return item.final_name or item.suggested_name
            elif col == 3:  # Type
                return item.file_type.upper()
            elif col == 4:  # Size
                return self._format_size(item.file_size)

        elif role == Qt.ForegroundRole:
            col = index.column()
            if col == 0:
                color = self._status_color(item.status)
                return QBrush(QColor(color))
            if col == 2 and not item.final_name and not item.suggested_name:
                return QBrush(QColor("#999999"))

        elif role == Qt.BackgroundRole:
            if item.status == FileStatus.FAILED:
                return QBrush(QColor("#fff0f0"))
            if item.status == FileStatus.APPLIED:
                return QBrush(QColor("#f0fff0"))

        elif role == Qt.ToolTipRole:
            if item.status == FileStatus.FAILED:
                return f"失败: {item.error_message}"

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if index.column() == 2:  # Suggested name column is editable
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if index.isValid() and index.column() == 2 and role == Qt.EditRole:
            item = self._items[index.row()]
            item.final_name = str(value)
            self.dataChanged.emit(index, index)
            self.data_changed.emit()
            return True
        return False

    @staticmethod
    def _status_text(status: FileStatus) -> str:
        mapping = {
            FileStatus.PENDING: "⏳",
            FileStatus.EXTRACTING: "📖",
            FileStatus.EXTRACTED: "📄",
            FileStatus.SUGGESTING: "🤖",
            FileStatus.SUGGESTED: "✅",
            FileStatus.APPLIED: "✔️",
            FileStatus.FAILED: "❌",
            FileStatus.IGNORED: "⏭️",
        }
        return mapping.get(status, "❓")

    @staticmethod
    def _status_color(status: FileStatus) -> str:
        mapping = {
            FileStatus.SUGGESTED: "#2e7d32",
            FileStatus.APPLIED: "#1565c0",
            FileStatus.FAILED: "#c62828",
            FileStatus.IGNORED: "#9e9e9e",
        }
        return mapping.get(status, "#333333")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"


class PreviewTable(QTableView):
    """TableView for previewing rename suggestions."""

    filename_edited = Signal(int, str)  # row, new_name
    selection_changed_signal = Signal(list)  # list of selected FileItems

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = FileItemTableModel(self)
        self.setModel(self._model)
        self._setup_appearance()

    def _setup_appearance(self):
        # Column sizing
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)

        self.setColumnWidth(0, 50)
        self.setColumnWidth(3, 60)
        self.setColumnWidth(4, 80)

        # Selection
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.setAlternatingRowColors(True)

        # Editing
        self.setEditTriggers(QTableView.DoubleClicked)

        # Visual
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)

    @property
    def table_model(self) -> FileItemTableModel:
        return self._model

    @property
    def items(self) -> list[FileItem]:
        return self._model.items

    def set_items(self, items: list[FileItem]):
        self._model.set_items(items)
        self.resizeRowsToContents()

    def add_items(self, items: list[FileItem]):
        self._model.add_items(items)

    def update_row(self, row: int):
        """Refresh a single row in the table."""
        top_left = self._model.index(row, 0)
        bottom_right = self._model.index(row, self._model.columnCount() - 1)
        self._model.dataChanged.emit(top_left, bottom_right)

    def refresh(self):
        """Refresh the entire table."""
        self._model.layoutChanged.emit()
        self.resizeRowsToContents()

    def get_selected_items(self) -> list[FileItem]:
        """Get FileItems for selected rows."""
        rows = set()
        for idx in self.selectionModel().selectedRows():
            rows.add(idx.row())
        return [self.items[i] for i in sorted(rows)]

    def get_suggested_items(self) -> list[FileItem]:
        """Get items ready for rename (SUGGESTED status, not ignored)."""
        return [i for i in self.items if i.status == FileStatus.SUGGESTED]
