"""Locale resource completeness — every key the product UI translates must
exist in all three supported locales (zh_CN / zh_HK / en_US).

The product UI must never render a raw ``prefs.*`` key (i18n returns the key
itself when a translation is missing), so any QML-side ``i18n.tr("...")``
literal must resolve in both resource files.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
QML_DIR = ROOT / "src" / "ui_qml"
LOCALES = ROOT / "src" / "utils" / "i18n" / "locales"

_TR_RE = re.compile(r"i18n\.tr\(\s*\"([^\"]+)\"")
_DYNAMIC_SUFFIXES = {
    "nav.short.": ("batch", "watch", "templates", "status", "preferences"),
    "nav.": ("batch", "watch", "templates", "status", "preferences"),
    "templates.language.": ("zh", "zh-HK", "en", "ja", "es"),
    "templates.field.": ("dcDate", "dcTitle", "dcSubject", "dcType", "dcCreator",
                         "dcIdentifier", "extOrganization", "extProject", "extStatus", "extVersion"),
    "vocab.source.": ("system", "user", "ai"),
    # ManagedWatchResults._NOTICE_CODES + ManagedWatchRuntime.notice branches;
    # the runtime bounds arbitrary failure codes before publishing to this UI.
    "watch.notice.": (
        "invalid_settings", "local_unavailable", "cloud_unavailable", "superseded",
        "global_pending_limit", "watch_pending_limit", "global_size_limit",
        "watch_size_limit", "resource_unavailable", "queue_full", "analysis_failed",
        "queue_unavailable", "self_event_held", "recovery_required",
        "global_concurrency_limit", "watch_concurrency_limit", "failure_backoff", "cooldown",
    ),
    # All nonempty auto_apply_review_reason return values. Empty is not shown.
    "watch.reviewReason.": (
        "metadata_only", "partial_content", "coverage_unavailable", "quality_degraded",
    ),
}


def _all_used_keys() -> set[str]:
    keys: set[str] = set()
    for qml in QML_DIR.glob("*.qml"):
        text = qml.read_text(encoding="utf-8")
        for m in _TR_RE.finditer(text):
            key = m.group(1)
            if text[m.end():].lstrip().startswith("+"):
                assert key in _DYNAMIC_SUFFIXES, f"Unenumerated dynamic translation family: {key}"
                keys.update(key + suffix for suffix in _DYNAMIC_SUFFIXES[key])
            else:
                keys.add(key)
    return keys


def _load(locale_file: str) -> dict[str, str]:
    with open(LOCALES / locale_file, encoding="utf-8") as f:
        return json.load(f)


def test_provider_placeholder_keys_exist():
    """The two keys Codex saw raw in the native Custom form."""
    zh = _load("zh_CN.json")
    en = _load("en_US.json")
    for key in ("prefs.provider.baseUrl.placeholder", "prefs.provider.model.placeholder"):
        assert key in zh, f"zh_CN missing {key}"
        assert key in en, f"en_US missing {key}"
        assert zh[key] != key and en[key] != key, f"{key} must be a real translation"


@pytest.mark.parametrize("locale_file", ["zh_CN.json", "zh_HK.json", "en_US.json"])
def test_every_used_key_exists_in_both_locales(locale_file):
    resource = _load(locale_file)
    missing: list[str] = []
    for key in sorted(_all_used_keys()):
        if key not in resource:
            missing.append(key)
    assert not missing, f"keys used in QML but missing in {locale_file}: {missing}"


@pytest.mark.parametrize("locale_file", ["zh_CN.json", "zh_HK.json", "en_US.json"])
def test_used_keys_are_real_translations(locale_file):
    """A key that resolves to itself is the raw-key leak we must prevent."""
    resource = _load(locale_file)
    leaked: list[str] = []
    for key in sorted(_all_used_keys()):
        if resource[key] == key:
            leaked.append(key)
    assert not leaked, f"keys resolving to themselves in {locale_file}: {leaked}"


def test_no_raw_prefs_key_in_rendered_placeholders():
    """Runtime check: the Custom form placeholders must not show raw keys."""
    from tests.qml.conftest import make_handle

    def _find(handle, object_name):
        from PySide6.QtQuick import QQuickItem
        return handle.root.findChild(QQuickItem, object_name)

    from tests.qml.test_provider_settings import FakeCredentialStore as Store
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    import tempfile

    ctrl = SettingsController(
        live_config=AppConfig(),
        config_file_path=Path(tempfile.mkdtemp()) / "settings.json",
        credential_store=Store(),
    )
    ctrl.openSession()
    h = make_handle(QML_DIR / "ProviderSettingsCard.qml", ctrl=ctrl)
    try:
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        add_btn = _find(h, "addProviderBtn")
        QMetaObject.invokeMethod(add_btn, "click")
        QApplication.processEvents()
        for field_name in ("pfBaseUrlField", "pfModelField"):
            text = _find(h, field_name).property("placeholderText")
            assert text and "prefs." not in text, (
                f"{field_name} placeholder leaked raw key: {text!r}"
            )
        h.assert_zero_warnings()
    finally:
        h.cleanup()
