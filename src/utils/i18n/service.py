"""I18n — QML-safe Slot API + compatible Python tr(key, locale, **kwargs).

Locale aliases: the boundary accepts BOTH hyphenated (``zh-CN``, the
canonical form) and underscored (``zh_CN`` — what AppConfig persists) for
every entry point (set_locale / setLocale / explicit tr locale).  The
internal locale and ``available_locales`` stay canonical (hyphenated).
"""
import json, os, re
from PySide6.QtCore import QObject, Signal, Property, Slot
from .locale_metadata import FALLBACK_LOCALE, LOCALE_META

class I18n(QObject):
    locale_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._cache: dict[str, dict[str, str]] = {}
        self._res_dir = os.path.join(os.path.dirname(__file__), "locales")
        self._locale: str = FALLBACK_LOCALE

    # ── QML interface ─────────────────────────────────
    @Property(str, notify=locale_changed)
    def locale(self) -> str: return self._locale

    @Property("QStringList", constant=True)
    def available_locales(self) -> list:
        return [loc for loc, st in LOCALE_META.items() if st == "supported" and self._load_resource(loc)]

    # Two overloads so QML can call BOTH i18n.tr("key") and
    # i18n.tr("key", i18n.locale) — the two-arg form makes the binding
    # depend on i18n.locale, so the current page re-translates instantly
    # when the user switches language.
    @Slot(str, result=str)
    @Slot(str, str, result=str)
    def tr(self, key: str, locale: str = "", **kwargs) -> str:
        loc = locale if locale else self._locale
        return self._translate(key, loc, **kwargs)

    @Slot(str, "QVariantMap", result=str)
    def trArgs(self, key: str, args: dict) -> str:
        return self._translate(key, self._locale, **args)

    @Slot(str)
    def setLocale(self, loc: str): self.set_locale(loc)

    # ── Python public API ─────────────────────────────
    def set_locale(self, locale: str):
        resolved = self._resolve_locale(locale)
        if resolved != self._locale:
            self._locale = resolved; self.locale_changed.emit(resolved)

    # ── Internal ──────────────────────────────────────
    def _translate(self, key: str, locale: str, **kwargs) -> str:
        resolved = self._resolve_locale(locale)
        data = self._load_resource(resolved)
        value = data.get(key)
        if value is None and resolved != FALLBACK_LOCALE:
            value = self._load_resource(FALLBACK_LOCALE).get(key)
        if value is None: value = key
        if locale == "en-XA":
            # Expand only translatable literals. Format placeholders are an
            # API contract and dynamic values supplied by callers must remain
            # byte-for-byte unchanged.
            parts = re.split(r"(\{[^{}]+\})", value)
            for index in range(0, len(parts), 2):
                for vowel in "aeiouAEIOU":
                    parts[index] = parts[index].replace(vowel, vowel * 2)
            value = "[" + "".join(parts) + " ~~~]"
        for k, v in kwargs.items(): value = value.replace("{" + k + "}", str(v))
        return value

    def _load_resource(self, locale: str) -> dict:
        if locale in self._cache: return self._cache[locale]
        path = os.path.join(self._res_dir, locale.replace("-", "_") + ".json")
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): data = {}
        self._cache[locale] = data
        return data

    def _resolve_locale(self, requested: str) -> str:
        # Accept zh_CN / en_US (AppConfig spelling) as aliases of the
        # canonical zh-CN / en-US; the canonical form is kept internally.
        requested = str(requested).replace("_", "-")
        if LOCALE_META.get(requested) == "supported" and self._load_resource(requested):
            return requested
        data = self._load_resource(FALLBACK_LOCALE)
        return FALLBACK_LOCALE if data else FALLBACK_LOCALE
