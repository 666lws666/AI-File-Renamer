"""M1 MockBatchController — Qt Model/Property/Slot, zero side effects."""
import re
from PySide6.QtCore import (QObject, Signal, Property, Slot, QAbstractListModel,
                             QModelIndex, Qt, QByteArray)

STATES = ["pending","analyzing","review_pending","undone","applied","failed","cancelled","ignored"]
LABELS = {"pending":"待处理","analyzing":"分析中","review_pending":"待确认","undone":"已撤销","applied":"已应用","failed":"失败","cancelled":"已取消","ignored":"已忽略"}
NAMES = ["季度销售报告_2025Q1","项目需求_AI重命名工具","合同_供应商A_v3","会议纪要_2025-07-26","发票_INV-2025-0042","照片_IMG_0421.jpg","扫描件_合同第3页","视频_产品演示_final","设计稿_v2_首页","数据分析_2025H1","周报_2025W30","论文_机器学习应用","简历_张三_2025","证件照_白底","预算表_2025年度","培训材料_新员工开发指南手册最终版v3","用户指南_Xuxia_v1","市场调研报告_2025","技术笔记_AI架构","年度回顾总结"]
EXTENSIONS = [".pdf",".pdf",".pdf",".md",".pdf",".jpg",".pdf",".mp4",".pdf",".xlsx",".docx",".pdf",".pdf",".jpg",".xlsx",".pptx",".pdf",".pdf",".md",".pdf"]
CYCLE = [0,1,2,3,4,5,6,7,0,1,2,4,5,2,4,2,4,0,2,7]
ERRORS = ["","","","","","","","","","","","","","","","batch.error.rateLimit","","","",""]

class MockTaskListModel(QAbstractListModel):
    taskIdRole = Qt.UserRole + 1; originalNameRole = Qt.UserRole + 2; suggestedNameRole = Qt.UserRole + 3
    extensionRole = Qt.UserRole + 4; statusRole = Qt.UserRole + 5; statusLabelRole = Qt.UserRole + 6
    selectedRole = Qt.UserRole + 7; thumbnailKindRole = Qt.UserRole + 8; errorMessageRole = Qt.UserRole + 9
    canApplyRole = Qt.UserRole + 10; canRetryRole = Qt.UserRole + 11; canIgnoreRole = Qt.UserRole + 12
    canCancelRole = Qt.UserRole + 13; canUndoRole = Qt.UserRole + 14; isEditingRole = Qt.UserRole + 15
    validationErrorRole = Qt.UserRole + 16
    _ROLES = {taskIdRole:b"taskId",originalNameRole:b"originalName",suggestedNameRole:b"suggestedName",
              extensionRole:b"extension",statusRole:b"status",statusLabelRole:b"statusLabel",
              selectedRole:b"selected",thumbnailKindRole:b"thumbnailKind",errorMessageRole:b"errorMessage",
              canApplyRole:b"canApply",canRetryRole:b"canRetry",canIgnoreRole:b"canIgnore",
              canCancelRole:b"canCancel",canUndoRole:b"canUndo",isEditingRole:b"isEditing",
              validationErrorRole:b"validationError"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks = []
        for i in range(20):
            st = STATES[CYCLE[i]]
            self._tasks.append({
                "taskId": f"m1-{i:03d}", "originalName": f"D:/docs/{NAMES[i]}{EXTENSIONS[i]}",
                "suggestedName": f"2025-{NAMES[i]}{EXTENSIONS[i]}" if st not in ("pending","analyzing","failed") else "",
                "extension": EXTENSIONS[i], "status": st, "statusLabel": LABELS[st],
                "selected": False, "thumbnailKind": "doc", "errorMessage": ERRORS[i],
                "isEditing": False, "validationError": ""
            })
        self._update_actions()

    def _update_actions(self):
        for t in self._tasks:
            s = t["status"]
            t["canApply"] = s in ("review_pending","undone"); t["canRetry"] = s in ("failed","cancelled","review_pending")
            t["canIgnore"] = s not in ("applied",); t["canCancel"] = s in ("pending","analyzing")
            t["canUndo"] = s == "applied"

    def rowCount(self, parent=QModelIndex()): return len(self._tasks)
    def roleNames(self): return self._ROLES
    def _role_key(self, role):
        m = {self.taskIdRole:"taskId",self.originalNameRole:"originalName",self.suggestedNameRole:"suggestedName",
             self.extensionRole:"extension",self.statusRole:"status",self.statusLabelRole:"statusLabel",
             self.selectedRole:"selected",self.thumbnailKindRole:"thumbnailKind",self.errorMessageRole:"errorMessage",
             self.canApplyRole:"canApply",self.canRetryRole:"canRetry",self.canIgnoreRole:"canIgnore",
             self.canCancelRole:"canCancel",self.canUndoRole:"canUndo",self.isEditingRole:"isEditing",
             self.validationErrorRole:"validationError"}
        return m.get(role,"")
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        k = self._role_key(role)
        return self._tasks[index.row()].get(k) if k else None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid(): return False
        t = self._tasks[index.row()]
        key = {self.selectedRole:"selected",self.isEditingRole:"isEditing",self.validationErrorRole:"validationError"}.get(role)
        if key: t[key] = value; self.dataChanged.emit(index, index, [role]); return True
        return False

    def flags(self, index): return Qt.ItemIsSelectable | Qt.ItemIsEnabled if index.isValid() else Qt.NoItemFlags


class MockBatchController(QObject):
    tasksChanged = Signal(); selectionChanged = Signal()
    progressChanged = Signal(); filterChanged = Signal()
    templateChanged = Signal()
    namingModeChanged = Signal()
    namingLanguageChanged = Signal()
    targetDirectoryChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = MockTaskListModel(self)
        self._search = ""; self._filter = "all"; self._apply_total = 10; self._apply_current = 0
        self._apply_success = 0; self._apply_failed = 0; self._apply_active = False
        self._template_options = [{"id": "default", "name": "General Naming (Default)"}]
        self._selected_template_id = "default"
        self._naming_mode = "template"
        self._naming_language = ""
        self._target_directory = ""

    @Property(QObject, constant=True)
    def tasksModel(self): return self._model

    @Property(int, notify=tasksChanged)
    def totalCount(self): return self._model.rowCount()
    @Property(int, notify=filterChanged)
    def visibleCount(self): return len(self._visible_ids())
    @Property(int, notify=selectionChanged)
    def selectedCount(self): return sum(1 for t in self._model._tasks if t["selected"])
    @Property(int, notify=selectionChanged)
    def hiddenSelectedCount(self):
        v = set(self._visible_ids()); return sum(1 for t in self._model._tasks if t["selected"] and t["taskId"] not in v)
    @Property(str, notify=selectionChanged)
    def selectAllState(self):
        sc = self.selectedCount; vc = self.visibleCount
        return "all" if vc > 0 and sc == vc else ("partial" if sc > 0 else "none")

    @Property(str, notify=filterChanged)
    def searchText(self): return self._search
    @Property(str, notify=filterChanged)
    def statusFilter(self): return self._filter
    @Property(str, notify=targetDirectoryChanged)
    def targetDirectory(self): return self._target_directory
    @Slot(str)
    def setTargetDirectory(self, directory):
        self._target_directory = str(directory or ""); self.targetDirectoryChanged.emit()

    @Property("QVariantList", notify=templateChanged)
    def templateOptions(self): return list(self._template_options)
    @Property(str, notify=templateChanged)
    def selectedTemplateId(self): return self._selected_template_id
    @Slot(str)
    def setSelectedTemplate(self, template_id):
        if template_id in {item["id"] for item in self._template_options}:
            self._selected_template_id = template_id; self.templateChanged.emit()

    @Property(str, notify=namingModeChanged)
    def namingMode(self): return self._naming_mode
    @Slot(str)
    def setNamingMode(self, mode):
        value = str(mode or "")
        if value in {"template", "smart"} and value != self._naming_mode:
            self._naming_mode = value; self.namingModeChanged.emit()

    @Property(str, notify=namingLanguageChanged)
    def namingLanguage(self): return self._naming_language
    @Slot(str)
    def setNamingLanguage(self, language):
        value = str(language or "")
        if value in {"", "zh", "zh-HK", "en", "ja", "es"} and value != self._naming_language:
            self._naming_language = value; self.namingLanguageChanged.emit()

    @Property(bool, notify=progressChanged)
    def applyInProgress(self): return self._apply_active
    @Property(int, notify=progressChanged)
    def applyCurrent(self): return self._apply_current
    @Property(int, notify=progressChanged)
    def applyTotal(self): return self._apply_total
    @Property(int, notify=progressChanged)
    def applySuccess(self): return self._apply_success
    @Property(int, notify=progressChanged)
    def applyFailed(self): return self._apply_failed
    @Property(float, notify=progressChanged)
    def applyProgress(self): return (self._apply_current / self._apply_total) if self._apply_total > 0 else 0.0

    def _visible_ids(self):
        ids = []
        for t in self._model._tasks:
            if self._filter != "all" and t["status"] != self._filter: continue
            if self._search and self._search.lower() not in t["originalName"].lower() and self._search.lower() not in t["suggestedName"].lower(): continue
            ids.append(t["taskId"])
        return ids

    @Slot(str)
    def setSearchText(self, q): self._search = q; self.filterChanged.emit(); self.tasksChanged.emit()
    @Slot(str)
    def setStatusFilter(self, f): self._filter = f; self.filterChanged.emit(); self.tasksChanged.emit()

    @Slot(str, result=bool)
    def isTaskVisible(self, task_id):
        """Return whether a task belongs in the current search/filter result set.

        The QML ListView deliberately keeps the stable source model so selection and
        inline-edit state are not recreated when a filter changes.  Delegates use
        this predicate to collapse non-matching rows from the visual queue.
        """
        return task_id in self._visible_ids()

    @Slot(str)
    def toggleTaskSelected(self, tid):
        for i, t in enumerate(self._model._tasks):
            if t["taskId"] == tid:
                t["selected"] = not t["selected"]
                idx = self._model.index(i, 0); self._model.dataChanged.emit(idx, idx, [])
                break
        self.selectionChanged.emit()

    @Slot(str)
    def setSelectAllState(self, state):
        vis = set(self._visible_ids())
        for i, t in enumerate(self._model._tasks):
            if t["taskId"] in vis:
                t["selected"] = (state == "all")
        self._model.dataChanged.emit(self._model.index(0,0), self._model.index(self._model.rowCount()-1,0), [])
        self.selectionChanged.emit()

    @Slot(str)
    def beginInlineEdit(self, tid):
        for row, task in enumerate(self._model._tasks):
            if task["taskId"] == tid:
                task["isEditing"] = True
                task["validationError"] = ""
                index = self._model.index(row, 0)
                self._model.dataChanged.emit(
                    index, index,
                    [self._model.isEditingRole, self._model.validationErrorRole],
                )
                break
        self.tasksChanged.emit()

    @Slot(str, str)
    def confirmInlineEdit(self, tid, newName):
        import re
        for t in self._model._tasks:
            if t["taskId"] == tid:
                n = newName.strip()
                if not n: t["validationError"] = "batch.validate.empty"
                elif any(c in n for c in '<>:"/\\|?*'): t["validationError"] = "batch.validate.illegalChars"
                elif re.search(r'[. ]$', n): t["validationError"] = "batch.validate.ending"
                elif re.match(r'^(CON|PRN|AUX|NUL|COM\d|LPT\d)$', n, re.IGNORECASE): t["validationError"] = "batch.validate.reserved"
                elif len(n) > 200: t["validationError"] = "batch.validate.tooLong"
                else: t["suggestedName"] = n + t["extension"]; t["isEditing"] = False; t["validationError"] = ""
                break
        self.tasksChanged.emit()

    @Slot(str)
    def cancelInlineEdit(self, tid):
        for row, task in enumerate(self._model._tasks):
            if task["taskId"] == tid:
                task["isEditing"] = False
                task["validationError"] = ""
                index = self._model.index(row, 0)
                self._model.dataChanged.emit(
                    index, index,
                    [self._model.isEditingRole, self._model.validationErrorRole],
                )
                break
        self.tasksChanged.emit()

    @Slot(str)
    def applyTask(self, tid): pass  # M1 mock
    @Slot(str)
    def retryTask(self, tid): pass
    @Slot(str)
    def ignoreTask(self, tid):
        for t in self._model._tasks:
            if t["taskId"] == tid: t["status"] = "ignored"; t["statusLabel"] = LABELS["ignored"]; break
        self._model._update_actions(); self.tasksChanged.emit()

    @Slot(str)
    def cancelTask(self, tid): pass
    @Slot(str)
    def undoTask(self, tid):
        for t in self._model._tasks:
            if t["taskId"] == tid and t["status"] == "applied": t["status"] = "undone"; t["statusLabel"] = LABELS["undone"]; break
        self._model._update_actions(); self.tasksChanged.emit()

    @Slot()
    def applySelected(self):
        self._apply_active = True; self._apply_current = 0; self._apply_success = 0; self._apply_failed = 0
        self._apply_total = max(1, self.selectedCount)
        self.progressChanged.emit()

    @Slot()
    def stopPending(self): self._apply_active = False; self.progressChanged.emit()

    @Slot()
    def clearWorkspace(self): pass  # M1 mock

    def set_empty(self):
        self._model._tasks.clear(); self._model.endResetModel(); self.tasksChanged.emit()

    def set_scenario_progress_50(self):
        self._apply_active = True; self._apply_total = 10; self._apply_current = 5; self._apply_success = 4; self._apply_failed = 1
        self.progressChanged.emit()

    def set_scenario_progress_0(self):
        self._apply_active = True; self._apply_total = 10; self._apply_current = 0; self._apply_success = 0; self._apply_failed = 0
        self.progressChanged.emit()

    def set_scenario_progress_partial(self):
        self._apply_active = True; self._apply_total = 10; self._apply_current = 7; self._apply_success = 5; self._apply_failed = 2
        self.progressChanged.emit()

    def set_scenario_progress_done(self):
        self._apply_active = True; self._apply_total = 10; self._apply_current = 10; self._apply_success = 8; self._apply_failed = 2
        self.progressChanged.emit()

    def set_scenario_n_items(self, n):
        """Change visible list to exactly n items (for visual uniqueness)."""
        self._model.beginResetModel()
        self._model._tasks = self._model._tasks[:n]
        self._model.endResetModel()
        self.tasksChanged.emit()

    def set_scenario_single_state(self, state):
        """Make ALL tasks have the same state + distinct names (for filter visual testing)."""
        import copy
        self._model.beginResetModel()
        tasks = []
        for i in range(8):
            t = {"taskId":f"m1-f{i:03d}","originalName":f"D:/docs/{state}_file_{i}.pdf",
                 "suggestedName":f"2025-{state}_document_{i}.pdf" if state in ("review_pending","undone","applied") else "",
                 "extension":".pdf","status":state,"statusLabel":LABELS[state],
                 "selected":False,"thumbnailKind":"doc","errorMessage":"","isEditing":False,"validationError":""}
            tasks.append(t)
        self._model._tasks = tasks
        self._model._update_actions(); self._model.endResetModel()
        self.tasksChanged.emit()
