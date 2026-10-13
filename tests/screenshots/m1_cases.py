"""M1 VisualCase Registry — real assertions, zero dict-only passthrough."""
from dataclasses import dataclass, field
from typing import Callable, Any, List

@dataclass
class AssertionRecord:
    name: str
    actual: object
    expected: object
    passed: bool

class AssertionRecorder:
    def __init__(self):
        self.records: List[AssertionRecord] = []
    def equal(self, name, actual, expected):
        p = actual == expected; self.records.append(AssertionRecord(name, actual, expected, p))
        if not p: raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")
    def true(self, name, actual):
        self.equal(name, bool(actual), True)
    def false(self, name, actual):
        self.equal(name, bool(actual), False)
    def gt(self, name, actual, minimum):
        p = actual > minimum; self.records.append(AssertionRecord(name, actual, f">{minimum}", p))
        if not p: raise AssertionError(f"{name}: expected >{minimum}, got {actual}")
    def lt(self, name, actual, maximum):
        p = actual < maximum; self.records.append(AssertionRecord(name, actual, f"<{maximum}", p))
        if not p: raise AssertionError(f"{name}: expected <{maximum}, got {actual}")

@dataclass
class VisualCase:
    case_id: str
    filename: str
    width: int = 1000
    height: int = 700
    locale: str = "en-US"
    setup_fn: Callable = lambda c,i: None
    post_fn: Callable = lambda v,c,i: None
    assert_fn: Callable = lambda v,c,i: AssertionRecorder()

# ── Setup functions ──────────────────────────────────────
def SI(ctrl, i18n): pass
def SE(ctrl, i18n): ctrl.set_empty()
def SA(ctrl, i18n): ctrl.setSelectAllState("all")
def S1(ctrl, i18n): ctrl.toggleTaskSelected(ctrl.tasksModel.data(ctrl.tasksModel.index(0,0),ctrl.tasksModel.taskIdRole))
def SS(ctrl, i18n): ctrl.setSearchText("2025")
def SH(ctrl, i18n): ctrl.setSelectAllState("all"); ctrl.setStatusFilter("failed")
def SF(s): return lambda c,i: (c.set_scenario_single_state(s), c.setStatusFilter(s))
def PF(s): return lambda v,c,i: c.setStatusFilter(s)
def SA0(ctrl, i18n): ctrl.set_scenario_progress_0()
def SA50(ctrl, i18n): ctrl.set_scenario_progress_50()
def SAP(ctrl, i18n): ctrl.set_scenario_progress_partial()
def SAD(ctrl, i18n): ctrl.set_scenario_progress_done()
def SADsel(ctrl, i18n): ctrl.set_scenario_progress_done(); ctrl.setSelectAllState("all")
def SEN(ctrl, i18n):
    tid=ctrl.tasksModel.data(ctrl.tasksModel.index(0,0),ctrl.tasksModel.taskIdRole); ctrl.beginInlineEdit(tid)
def SEE(ctrl, i18n):
    tid=ctrl.tasksModel.data(ctrl.tasksModel.index(0,0),ctrl.tasksModel.taskIdRole)
    ctrl.beginInlineEdit(tid); ctrl.confirmInlineEdit(tid,"a<b>c")
# Native-specific setups
def SEMP(ctrl, i18n): ctrl.set_empty()  # empty shell
def SMIX(ctrl, i18n): pass  # 20-item mixed
def SEE_ZH(ctrl, i18n):
    tid=ctrl.tasksModel.data(ctrl.tasksModel.index(0,0),ctrl.tasksModel.taskIdRole)
    ctrl.beginInlineEdit(tid); ctrl.confirmInlineEdit(tid,"a<b>c")

# ── Real assert functions (recorder-based, actual assertions) ─
def A_SHELL_EMPTY(v, c, i):
    rec = AssertionRecorder()
    rec.equal("visibleCount", c.visibleCount, 0)
    rec.equal("totalCount", c.totalCount, 0)
    return rec

def A_MIXED(v, c, i):
    rec = AssertionRecorder()
    rec.equal("totalCount", c.totalCount, 20)
    rec.gt("visibleCount", c.visibleCount, 0)
    m=c.tasksModel; states=set()
    for j in range(m.rowCount()): states.add(m.data(m.index(j,0),m.statusRole))
    rec.equal("eightStates", len(states), 8)
    return rec

def A_IDLE(v, c, i):
    rec = AssertionRecorder(); rec.equal("totalCount", c.totalCount, 20); return rec

def A_FILTER(s):
    def fn(v, c, i):
        rec = AssertionRecorder()
        rec.equal("statusFilter", c.statusFilter, s)
        rec.equal("visibleCount_gt_0", c.visibleCount > 0, True)
        m=c.tasksModel
        for j in range(m.rowCount()):
            actual_s = m.data(m.index(j,0),m.statusRole)
            rec.equal(f"task_{j}_status", actual_s, s)
        return rec
    return fn

def A_SEL_ALL(v, c, i):
    rec = AssertionRecorder(); rec.gt("selectedCount", c.selectedCount, 0)
    rec.equal("selectAllState", c.selectAllState, "all"); return rec
def A_SEL_ONE(v, c, i):
    rec = AssertionRecorder(); rec.equal("selectedCount", c.selectedCount, 1); return rec
def A_SEL_HIDDEN(v, c, i):
    rec = AssertionRecorder(); rec.gt("hiddenSelectedCount", c.hiddenSelectedCount, 0); return rec
def A_SEARCH(v, c, i):
    rec = AssertionRecorder(); rec.equal("searchText", c.searchText, "2025")
    rec.gt("visibleCount", c.visibleCount, 0); return rec

def A_APPLY(v, c, i):
    rec = AssertionRecorder()
    rec.true("applyInProgress", c.applyInProgress)
    rec.gt("applyTotal", c.applyTotal, 0)
    return rec

def A_EDIT_ERR(v, c, i):
    rec = AssertionRecorder()
    m=c.tasksModel
    rec.true("isEditing", m.data(m.index(0,0),m.isEditingRole))
    ve=m.data(m.index(0,0),m.validationErrorRole)
    rec.true("validationError_nonempty", ve != "")
    return rec

def A_EDIT_NORM(v, c, i):
    rec = AssertionRecorder()
    m=c.tasksModel
    rec.true("isEditing", m.data(m.index(0,0),m.isEditingRole))
    ve=m.data(m.index(0,0),m.validationErrorRole)
    rec.true("validationError_empty", ve == "")
    return rec

# ── Canonical registry ────────────────────────────────────
CANONICAL_CASES = [
    VisualCase("shell_zh_1k","e_zh_1k",1000,700,"zh-CN",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("shell_zh_900","e_zh_900",900,640,"zh-CN",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("empty_zh_1k","e_zh_1k",1000,700,"zh-CN",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("empty_zh_900","e_zh_900",900,640,"zh-CN",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("empty_en_1k","e_en_1k",1000,700,"en-US",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("empty_en_900","e_en_900",900,640,"en-US",SE, assert_fn=A_SHELL_EMPTY),
    VisualCase("filter_analyzing","f_analyzing",1000,700,"en-US",SF("analyzing"), post_fn=PF("analyzing"), assert_fn=A_FILTER("analyzing")),
    VisualCase("filter_applied","f_applied",1000,700,"en-US",SF("applied"), post_fn=PF("applied"), assert_fn=A_FILTER("applied")),
    VisualCase("filter_failed","f_failed",1000,700,"en-US",SF("failed"), post_fn=PF("failed"), assert_fn=A_FILTER("failed")),
    VisualCase("filter_ignored","f_ignored",1000,700,"en-US",SF("ignored"), post_fn=PF("ignored"), assert_fn=A_FILTER("ignored")),
    VisualCase("filter_review_pending","f_review_pending",1000,700,"en-US",SF("review_pending"), post_fn=PF("review_pending"), assert_fn=A_FILTER("review_pending")),
    VisualCase("filter_undone","f_undone",1000,700,"en-US",SF("undone"), post_fn=PF("undone"), assert_fn=A_FILTER("undone")),
    VisualCase("filter_zh_analyzing","fzh_analyzing",1000,700,"zh-CN",SF("analyzing"), post_fn=PF("analyzing"), assert_fn=A_FILTER("analyzing")),
    VisualCase("filter_zh_pending","fzh_pending",1000,700,"zh-CN",SF("pending"), post_fn=PF("pending"), assert_fn=A_FILTER("pending")),
    VisualCase("filter_zh_review_pending","fzh_review_pending",1000,700,"zh-CN",SF("review_pending"), post_fn=PF("review_pending"), assert_fn=A_FILTER("review_pending")),
    VisualCase("filter_zh_undone","fzh_undone",1000,700,"zh-CN",SF("undone"), post_fn=PF("undone"), assert_fn=A_FILTER("undone")),
    VisualCase("sel_all","sel_a",1000,700,"en-US",SA, assert_fn=A_SEL_ALL),
    VisualCase("sel_hidden","sel_h",1000,700,"en-US",SH, post_fn=PF("failed"), assert_fn=A_SEL_HIDDEN),
    VisualCase("sel_one","sel_1",1000,700,"en-US",S1, assert_fn=A_SEL_ONE),
    VisualCase("sel_zh","sel_zh",1000,700,"zh-CN",SA, assert_fn=A_SEL_ALL),
    VisualCase("sel_900","sel_900",900,640,"en-US",SA, assert_fn=A_SEL_ALL),
    VisualCase("sel_h_900","sel_h_900",900,640,"en-US",SH, post_fn=PF("failed"), assert_fn=A_SEL_HIDDEN),
    VisualCase("m9_sel_zh","m9_sel_zh",900,640,"zh-CN",SA, assert_fn=A_SEL_ALL),
    VisualCase("m9_srh_zh","m9_srh_zh",900,640,"zh-CN",SS, assert_fn=A_SEARCH),
    VisualCase("search","srch",1000,700,"en-US",SS, assert_fn=A_SEARCH),
    VisualCase("search_900","srch_900",900,640,"en-US",SS, assert_fn=A_SEARCH),
    VisualCase("apply_0","a0",1000,700,"en-US",SA0, assert_fn=A_APPLY),
    VisualCase("apply_50","a50",1000,700,"en-US",SA50, assert_fn=A_APPLY),
    VisualCase("apply_partial","ap",1000,700,"en-US",SAP, assert_fn=A_APPLY),
    VisualCase("apply_done","ad",1000,700,"en-US",SAD, assert_fn=A_APPLY),
    VisualCase("apply_0_zh","a0_zh",1000,700,"zh-CN",SA0, assert_fn=A_APPLY),
    VisualCase("apply_50_zh","a50_zh",1000,700,"zh-CN",SA50, assert_fn=A_APPLY),
    VisualCase("apply_partial_zh","x5_ap_zh",1000,700,"zh-CN",SAP, assert_fn=A_APPLY),
    VisualCase("apply_done_zh","x4_ad_zh",1000,700,"zh-CN",SAD, assert_fn=A_APPLY),
    VisualCase("apply_50_900","a50_900",900,640,"en-US",SA50, assert_fn=A_APPLY),
    VisualCase("apply_partial_900","ap_900",900,640,"en-US",SAP, assert_fn=A_APPLY),
    VisualCase("apply_done_900","x1_ad_900",900,640,"en-US",SAD, assert_fn=A_APPLY),
    VisualCase("apply_0_900","x2_a0_900",900,640,"en-US",SA0, assert_fn=A_APPLY),
    VisualCase("apply_done_sel_zh_900","x7_ad_sel_zh_900",900,640,"zh-CN",SADsel, assert_fn=A_APPLY),
    VisualCase("inline_error","ee",1000,700,"en-US",SEE, assert_fn=A_EDIT_ERR),
]

assert len(CANONICAL_CASES) == 40
for c in CANONICAL_CASES:
    assert c.setup_fn is not None
    assert c.assert_fn is not None

# Native three cases — semantically distinct
NATIVE_CASES = [
    VisualCase("native_shell_empty","shell_zh_1000x700",1000,700,"zh-CN",SEMP, assert_fn=A_SHELL_EMPTY),
    VisualCase("native_mixed_20","mixed_zh_1000x700",1000,700,"zh-CN",SMIX, assert_fn=A_MIXED),
    VisualCase("native_inline_error","inline_error_zh_1000x700",1000,700,"zh-CN",SEE_ZH, assert_fn=A_EDIT_ERR),
]
