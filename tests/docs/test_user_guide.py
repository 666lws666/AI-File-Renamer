"""Offline user-guide contract: current product facts, local assets, valid navigation."""
from __future__ import annotations

import re
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "序匣用户手册.html"
ASSETS = ROOT / "user-guide-assets"
MANIFEST = ASSETS / "manifest.json"

GUIDES = {
    "zh-CN": GUIDE,
    "zh-HK": ASSETS / "manual-zh-HK.html",
    "en-US": ASSETS / "manual-en-US.html",
}

EXPECTED_SCREENSHOTS = {
    "navigation": "01-navigation.png",
    "provider-settings": "02-provider-settings.png",
    "batch-empty": "03-batch-empty.png",
    "batch-review": "04-batch-review.png",
    "inline-edit": "05-inline-edit.png",
    "watch-create": "06-watch-create.png",
    "watch-results": "07-watch-results.png",
    "templates": "08-templates.png",
    "vocabulary": "09-vocabulary.png",
    "system-status": "10-system-status.png",
    "naming-mode": "11-naming-mode.png",
    "filename-language": "12-filename-language.png",
}

REQUIRED_IDS = {
    "overview", "before-start", "provider", "navigation", "quickstart",
    "batch", "states", "watch", "templates", "multimodal", "limits",
    "privacy", "undo", "troubleshooting", "formats", "faq", "version", "local-mode",
}

FORBIDDEN = {
    "git clone", "python -m venv", "多模态分析尚未实现", "开发状态说明",
    "批次费用", "费用预估", "必须同时配置", "0.001 元", "tbd", "todo",
}

LOCALE_CONTRACTS = {
    "zh-CN": (
        "简体中文", "繁體中文（香港）", "English", "按模板命名", "AI 智能命名",
        "批量命名", "监控文件夹", "命名模板", "系统状态", "设置",
        "隐私与数据流", "撤销（Undo）",
    ),
    "zh-HK": (
        "简体中文", "繁體中文（香港）", "English", "按範本命名", "AI 智能命名",
        "批次命名", "監控資料夾", "命名範本", "系統狀態", "設定",
        "私隱與資料流程", "撤銷（Undo）",
    ),
    "en-US": (
        "简体中文", "繁體中文（香港）", "English", "Template mode", "AI Smart mode",
        "Batch Naming", "Watch Folders", "Naming Templates", "System Status", "Settings",
        "Privacy and data flow", "Undo and file safety",
    ),
}


class GuideParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.sources: list[str] = []
        self.image_alts: list[str | None] = []
        self.title_count = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if values.get("href"):
            self.hrefs.append(values["href"])
        if values.get("src"):
            self.sources.append(values["src"])
        if tag == "img":
            self.image_alts.append(values.get("alt"))
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_count += 1


def _load(path: Path = GUIDE) -> tuple[str, GuideParser]:
    assert path.is_file(), f"离线说明书不存在: {path.name}"
    raw = path.read_text(encoding="utf-8")
    parser = GuideParser()
    parser.feed(raw)
    return raw, parser


def test_three_complete_static_locales_have_localized_bodies_and_language_links():
    for locale, path in GUIDES.items():
        raw, parser = _load(path)
        assert f'<html lang="{locale}">' in raw
        assert REQUIRED_IDS <= parser.ids
        assert raw.count('<section class="chapter"') == len(REQUIRED_IDS)
        assert "2026-10-12" in raw
        assert len(raw) >= 20_000, f"{locale} appears to be a title-only translation"
        for phrase in LOCALE_CONTRACTS[locale]:
            assert phrase in raw, (locale, phrase)
        language_links = [
            href for href in parser.hrefs
            if "manual-" in href or "序匣用户手册" in href
        ]
        assert len(language_links) == 2, (locale, language_links)
        assert not any(symbol in raw for symbol in ("🇨🇳", "🇭🇰", "🇺🇸", "🇬🇧"))


def test_all_locales_explain_smart_mode_without_weakening_template_defaults_or_safety():
    required = {
        "zh-CN": (
            "默认仍是按模板命名", "精确字段", "上下文", "同一批次", "文件名语言",
            "界面语言", "日文", "西班牙文", "180", "UTF-16", "拒绝", "不会截断",
            "重新生成", "应用", "撤销（Undo）", "先审核", "自动应用",
            "示例为合成演示结果", "模拟测试",
        ),
        "zh-HK": (
            "預設仍是按範本命名", "精確欄位", "上下文", "同一批次", "檔案名稱語言",
            "介面語言", "日文", "西班牙文", "180", "UTF-16", "拒絕", "不會截斷",
            "重新產生", "應用", "撤銷（Undo）", "先審核", "自動應用",
            "範例為合成示範結果", "模擬測試",
        ),
        "en-US": (
            "Template mode remains the default", "exact fields", "context", "same batch",
            "filename language", "interface language", "Japanese", "Spanish", "180", "UTF-16",
            "reject", "does not truncate", "regenerate", "Apply", "Undo",
            "synthetic illustrative results", "mocked tests",
        ),
    }
    for locale, path in GUIDES.items():
        raw, _ = _load(path)
        for phrase in required[locale]:
            assert phrase.casefold() in raw.casefold(), (locale, phrase)


def test_locale_pages_are_offline_and_every_link_or_resource_stays_in_repository():
    for locale, path in GUIDES.items():
        raw, parser = _load(path)
        lowered = raw.casefold()
        assert "http://" not in lowered
        assert "https://" not in lowered
        assert "//cdn" not in lowered
        assert "@import" not in lowered
        assert not re.search(r"[a-z]:[\\/]", raw, re.IGNORECASE)
        assert "\\\\" not in raw
        for href in parser.hrefs:
            if href.startswith("#"):
                assert unquote(href[1:]) in parser.ids, (locale, href)
                continue
            target = (path.parent / unquote(href)).resolve()
            assert target.is_relative_to(ROOT.resolve()), (locale, href)
            assert target.exists(), (locale, href)
        for src in parser.sources:
            assert not src.startswith(("http:", "https:", "//", "data:")), (locale, src)
            target = (path.parent / unquote(src)).resolve()
            assert target.is_relative_to(ROOT.resolve()), (locale, src)
            assert target.exists(), (locale, src)


def test_provider_guidance_avoids_stale_or_unverified_model_availability_claims():
    for locale, path in GUIDES.items():
        raw, _ = _load(path)
        lowered = raw.casefold()
        assert "deepseek-v4-flash" not in lowered
        assert "2026-09-14" not in raw
        assert "deepseek-flash" not in lowered


def test_smart_retry_reimport_and_cache_boundaries_are_exact_in_every_locale():
    required = {
        "zh-CN": (
            "当前 AI 智能命名的批量分析管线不会读取或写入命名建议缓存",
            "首次失败不会产生可编辑建议",
            "先从工作区移除失败任务，再按新模式重新导入",
            "重试始终保留导入时的模式和文件名语言",
        ),
        "zh-HK": (
            "目前 AI 智能命名的批次分析流程不會讀取或寫入命名建議快取",
            "首次失敗不會產生可編輯建議",
            "先從工作區移除失敗任務，再按新模式重新匯入",
            "重新嘗試始終保留匯入時的模式及檔案名稱語言",
        ),
        "en-US": (
            "current AI Smart Batch analysis does not read or write a suggestion cache",
            "A first analysis failure has no suggestion to edit",
            "remove the failed task from the workspace and import it again under the new mode",
            "Retry always preserves the mode and filename language captured at import",
        ),
    }
    for locale, path in GUIDES.items():
        raw, _ = _load(path)
        for phrase in required[locale]:
            assert phrase.casefold() in raw.casefold(), (locale, phrase)


def test_guide_has_complete_current_product_chapters():
    raw, parser = _load()
    assert raw.startswith("<!DOCTYPE html>")
    assert parser.title_count == 1
    assert REQUIRED_IDS <= parser.ids
    assert "序匣 1.0.0" in raw
    for phrase in FORBIDDEN:
        assert phrase.casefold() not in raw.casefold(), phrase


def test_guide_is_fully_offline_and_contains_no_private_machine_data():
    raw, parser = _load()
    lowered = raw.casefold()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "//cdn" not in lowered
    assert "@import" not in lowered
    assert not re.search(r"[a-z]:[\\/]", raw, re.IGNORECASE)
    assert "\\\\" not in raw
    assert "api_key=" not in lowered
    assert "bearer " not in lowered
    assert parser.sources or parser.hrefs


def test_internal_anchors_and_local_resources_resolve_inside_repository():
    _, parser = _load()
    for href in parser.hrefs:
        if href.startswith("#"):
            assert unquote(href[1:]) in parser.ids, href
            continue
        target = (GUIDE.parent / unquote(href)).resolve()
        assert target.is_relative_to(ROOT.resolve()), href
        assert target.exists(), href
    for src in parser.sources:
        assert not src.startswith(("http:", "https:", "//", "data:")), src
        target = (GUIDE.parent / unquote(src)).resolve()
        assert target.is_relative_to(ROOT.resolve()), src
        assert target.exists(), src


def test_every_screenshot_has_meaningful_chinese_alt_text():
    _, parser = _load()
    for alt in parser.image_alts:
        assert alt is not None and len(alt.strip()) >= 6
        assert re.search(r"[\u4e00-\u9fff]", alt)


def test_every_locale_has_meaningful_localized_alt_text_and_captions():
    for locale, path in GUIDES.items():
        raw, parser = _load(path)
        assert parser.image_alts
        assert raw.count("<figcaption>") == len(parser.image_alts)
        for alt in parser.image_alts:
            assert alt is not None and len(alt.strip()) >= 12
            if locale != "en-US":
                assert re.search(r"[\u4e00-\u9fff]", alt)


def test_guide_states_current_provider_multimodal_and_safety_semantics():
    raw, _ = _load()
    required_facts = (
        "当前 Provider", "测试连接", "先审核", "自动应用",
        "ResourcePaused", "系统凭据管理器", "本地提取", "关键帧",
        "不会上传完整视频", "撤销（Undo）", "清空工作区不会撤销",
        "扩展名", "逐文件", "图片", "扫描 PDF",
    )
    for fact in required_facts:
        assert fact in raw, fact


def test_native_screenshot_manifest_is_complete_and_verifiable():
    assert MANIFEST.is_file(), "缺少原生 Windows 截图清单"
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["platform"] == "windows"
    assert payload["cjk"]["passed"] is True
    assert payload["privacy_scan"]["passed"] is True
    cases = payload["cases"]
    expected_cases = {
        f"{locale}:{scene}"
        for locale in GUIDES
        for scene in EXPECTED_SCREENSHOTS
    }
    assert {case["case_id"] for case in cases} == expected_cases
    assert len(cases) == len(expected_cases)
    shas: set[str] = set()
    for case in cases:
        locale, scene = case["case_id"].split(":", 1)
        assert case["locale"] == locale
        assert case["filename"] == f"{locale}/{EXPECTED_SCREENSHOTS[scene]}"
        assert case["synthetic_examples"] is True
        assert case["real_model_quality_verified"] is False
        assert case["width"] >= 900 and case["height"] >= 640
        assert case["warnings"] == []
        assert case["assertions"]
        asset = ASSETS / case["filename"]
        assert asset.is_file()
        actual_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
        assert actual_sha == case["sha256"]
        shas.add(actual_sha)
    assert len(shas) == len(cases), "不同语义截图出现重复像素"


def test_guide_references_every_native_screenshot():
    for locale, guide in GUIDES.items():
        _, parser = _load(guide)
        linked = {Path(unquote(src)).as_posix() for src in parser.sources}
        expected = {
            f"user-guide-assets/{locale}/{name}" if guide == GUIDE else f"{locale}/{name}"
            for name in EXPECTED_SCREENSHOTS.values()
        }
        assert linked == expected


LOCAL_CONTRACTS = {
    "choices": {
        "zh-CN": ("两个独立选择", "云端 AI", "本地隐私", "标题栏下方", "批量命名和监控文件夹共用", "设置的保存或取消不会撤销"),
        "zh-HK": ("兩個獨立選擇", "雲端 AI", "本機私隱", "標題列下方", "批次命名與監控資料夾共用", "設定的儲存或取消不會撤銷"),
        "en-US": ("two independent choices", "Cloud AI", "Local privacy", "below the title bar", "shared by Batch and Watch", "Settings Save or Cancel does not undo"),
    },
    "admission": {
        "zh-CN": ("立即阻止之后的新云端请求", "已经发送的云端请求无法召回", "不会自动回退到云端", "只有明确选择云端 AI"),
        "zh-HK": ("立即阻止之後的新雲端請求", "已送出的雲端請求無法收回", "不會自動退回雲端", "只有明確選擇雲端 AI"),
        "en-US": ("immediately blocks future cloud requests", "already-sent cloud requests cannot be recalled", "never automatically falls back to cloud", "only an explicit Cloud AI choice"),
    },
    "consent": {
        "zh-CN": ("检查资源", "下载并启用", "同意，下载公开资源", "导入离线文件夹", "固定文件集合", "不是任意模型", "不会改动原文件夹"),
        "zh-HK": ("檢查資源", "下載並啟用", "同意，下載公開資源", "匯入離線資料夾", "固定檔案集合", "不是任意模型", "不會改動原資料夾"),
        "en-US": ("Check resources", "Download and enable", "I agree — download public resources", "Import offline folder", "fixed file set", "not arbitrary models", "does not alter the original folder"),
    },
    "readiness": {
        "zh-CN": ("AVAILABLE", "READY", "已验证，但尚未启用", "准备已有资源", "真实自检", "取消请求不代表工作立即结束"),
        "zh-HK": ("AVAILABLE", "READY", "已驗證，但尚未啟用", "準備已有資源", "實際自我檢查", "取消請求不代表工作立即結束"),
        "en-US": ("AVAILABLE", "READY", "verified, not enabled", "Prepare existing resources", "real self-check", "a cancellation request does not mean work has ended immediately"),
    },
    "resources": {
        locale: ("Qwen/Qwen3.5-4B", "Q4_K_M", "llama.cpp b10885", "3431786583", "3413361504", "46749981", "18425079", "Xuxia/local-ai", "github.com", "huggingface.co")
        for locale in GUIDES
    },
    "hardware": {
        "zh-CN": ("硬件准入检查不是性能保证", "不承诺统一的最低内存", "已接收字节不等于已验证或保证保留", "不是精确的所需空闲空间"),
        "zh-HK": ("硬件准入檢查不是效能保證", "不承諾統一的最低記憶體", "已接收位元組不等於已驗證或保證保留", "不是精確的所需可用空間"),
        "en-US": ("hardware admission is not a performance guarantee", "no universal minimum RAM", "received bytes are not verified or guaranteed retained bytes", "not an exact free-space requirement"),
    },
    "recovery": {
        "zh-CN": ("重试当前所有者清理", "未知的旧所有者", "保留证据并寻求支持", "隔离当前损坏项", "不会删除文档、未知文件或日志记录"),
        "zh-HK": ("重試目前擁有者清理", "未知的舊擁有者", "保留證據並尋求支援", "隔離目前損壞項", "不會刪除文件、未知檔案或日誌記錄"),
        "en-US": ("Retry current-owner cleanup", "unknown previous owner", "preserve evidence and seek support", "Quarantine current damaged item", "does not delete documents, unknown files, or journals"),
    },
    "privacy": {
        "zh-CN": ("本地隐私模式下，序匣不上传文件内容或命名请求", "其他应用或操作系统同步", "不发送文档、名称、路径、命名提示或密钥", "本地与云端缓存分区", "不是任意 localhost"),
        "zh-HK": ("本機私隱模式下，序匣不上載檔案內容或命名請求", "其他應用程式或作業系統同步", "不傳送文件、名稱、路徑、命名提示或金鑰", "本機與雲端快取分區", "不是任意 localhost"),
        "en-US": ("in Local privacy, Xuxia does not upload file content or naming requests", "other applications or operating-system sync", "does not send documents, names, paths, naming prompts or keys", "local and cloud caches are partitioned", "not arbitrary localhost"),
    },
    "coverage": {
        "zh-CN": ("完整 PDF、完整视频或源路径不会进入模型请求", "空白、不可读或覆盖不完整", "不保证理解整段视频", "部分或未知覆盖", "只处理新生成的中文名称", "此前云端界面的流程示意"),
        "zh-HK": ("完整 PDF、完整影片或來源路徑不會進入模型請求", "空白、不可讀或覆蓋不完整", "不保證理解整段影片", "部分或未知覆蓋", "只處理新產生的中文名稱", "較早雲端介面的流程示意"),
        "en-US": ("complete PDFs, complete videos, or source paths do not enter model requests", "blank, unreadable, or incomplete coverage", "does not guarantee understanding of the entire video", "partial or unknown coverage", "only newly generated Chinese names", "earlier cloud-interface workflow illustrations"),
    },
    "same-volume": {
        "zh-CN": ("应用和撤销目前仅支持同卷", "跨卷移动会安全失败并保留源文件", "不会改成复制后删除"),
        "zh-HK": ("應用及撤銷目前只支援同一磁碟區", "跨磁碟區移動會安全失敗並保留來源檔案", "不會改為複製後刪除"),
        "en-US": ("Apply and Undo currently support same-volume operations only", "cross-volume moves fail safely and leave the source file", "no copy-then-delete fallback"),
    },
}


@pytest.mark.parametrize("locale", GUIDES)
def test_every_locale_has_a_navigable_local_mode_chapter(locale):
    raw, parser = _load(GUIDES[locale])
    assert "local-mode" in parser.ids
    assert '#local-mode' in parser.hrefs
    assert re.search(r'<section class="chapter" id="local-mode">.*?</section>', raw, re.S)


@pytest.mark.parametrize("locale", GUIDES)
@pytest.mark.parametrize("contract", LOCAL_CONTRACTS)
def test_managed_local_product_contract_is_translated_in_every_locale(locale, contract):
    raw, _ = _load(GUIDES[locale])
    if contract != "same-volume":
        section = re.search(r'<section class="chapter" id="local-mode">(.*?)</section>', raw, re.S)
        assert section is not None
        raw = section.group(1)
    for phrase in LOCAL_CONTRACTS[contract][locale]:
        assert phrase.casefold() in raw.casefold(), (locale, contract, phrase)


@pytest.mark.parametrize("locale,visible_ready", [
    ("zh-CN", "本地隐私已启用，服务自检通过"),
    ("zh-HK", "本機私隱已啟用，服務自檢通過"),
    ("en-US", "Local privacy enabled — service self-check passed"),
])
def test_local_workflow_names_the_visible_ready_label_not_only_an_internal_enum(locale, visible_ready):
    raw, _ = _load(GUIDES[locale])
    assert visible_ready in raw


def test_print_layout_allows_long_chapters_to_flow_without_splitting_callouts():
    css = (ASSETS / "guide.css").read_text(encoding="utf-8")
    print_css = css.split("@media print", 1)[1]
    assert ".chapter { break-inside: auto;" in print_css
    assert ".shot { break-inside: avoid;" in print_css
    assert ".callout { break-inside: avoid;" in print_css


def test_keyboard_focus_and_language_switch_are_visible_in_screen_but_not_print():
    css = (ASSETS / "guide.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert ".language-switch" in css
    print_css = css.split("@media print", 1)[1]
    assert ".language-switch" in print_css

