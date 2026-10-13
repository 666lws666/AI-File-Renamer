"""Offline script normalization; not semantic translation or model-quality evidence."""
import builtins

import pytest


@pytest.mark.parametrize("locale,source,expected", [
    ("zh-HK", "山岚社區雨水花园维护指引_2026-10-12_ModelX_v1.2.txt",
     "山嵐社區雨水花園維護指引_2026-10-12_ModelX_v1.2.txt"),
    ("zh-CN", "山嵐社区雨水花園維護指引_2026-10-12_ModelX_v1.2.txt",
     "山岚社区雨水花园维护指引_2026-10-12_ModelX_v1.2.txt"),
])
def test_packaged_dictionaries_normalize_mixed_script_preserving_ascii(locale, source, expected):
    from src.core.naming_orthography import normalize_managed_name
    assert normalize_managed_name(source, locale, ".txt") == expected


@pytest.mark.parametrize("locale", ["en-US", "ja-JP", "es-ES"])
def test_other_locales_do_not_load_converter_or_change_text(monkeypatch, locale):
    from src.core.naming_orthography import normalize_managed_name
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "opencc":
            pytest.fail("non-Chinese locale loaded a converter")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    source = "大学校園_Study_日本語_Español_v2.1.txt"
    assert normalize_managed_name(source, locale, ".txt") == source


@pytest.mark.parametrize("output", ["../逃逸", "C:\\逃逸", "/逃逸", "坏/目录", "CON", "坏\x00名", "", None,
                                    "坏" * 256, "坏" * 181, "😀" * 91, "坏.pdf"])
def test_conversion_output_is_revalidated_without_sanitizing_or_truncating(monkeypatch, output):
    import opencc
    from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name
    converter = opencc.OpenCC("s2hk")
    monkeypatch.setattr(converter, "convert", lambda value: output)
    monkeypatch.setattr(opencc, "OpenCC", lambda config: converter)
    with pytest.raises(NamingOrthographyError, match="Invalid naming response"):
        normalize_managed_name("原名.txt", "zh-HK", ".txt", smart=True)


@pytest.mark.parametrize("failure", [ImportError, FileNotFoundError, ValueError, RuntimeError])
def test_dependency_or_conversion_failure_refuses_suggestion(monkeypatch, failure):
    import opencc
    from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name
    def fail(*args, **kwargs):
        raise failure("private path or content must not leak")
    monkeypatch.setattr(opencc, "OpenCC", fail)
    with pytest.raises(NamingOrthographyError, match="^Invalid naming response$"):
        normalize_managed_name("维护指引.txt", "zh-HK", ".txt")


def test_missing_import_refuses_selected_script(monkeypatch):
    from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "opencc":
            raise ImportError("private-marker")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(NamingOrthographyError):
        normalize_managed_name("维护指引.txt", "zh-HK", ".txt")


def test_template_directory_structure_is_preserved_and_protected_extension_not_converted():
    from src.core.naming_orthography import normalize_managed_name
    assert normalize_managed_name("社区/维护指引.TXT", "zh-HK", ".TXT") == "社區/維護指引.TXT"


@pytest.mark.parametrize("stem", ["雨" * 180, "😀" * 90])
def test_smart_exact_utf16_boundary_is_not_truncated_or_refused(stem):
    from src.core.naming_orthography import normalize_managed_name
    assert normalize_managed_name(stem + ".txt", "zh-HK", ".txt", smart=True) == stem + ".txt"


@pytest.mark.parametrize("resource", ["config", "dictionary"])
def test_actual_missing_packaged_resources_refuse_conversion(monkeypatch, resource):
    import io
    from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name
    owner = builtins if resource == "config" else io
    real_open = owner.open
    def missing(path, *args, **kwargs):
        if resource in str(path).replace("\\", "/").split("/"):
            raise FileNotFoundError("private-marker")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(owner, "open", missing)
    with pytest.raises(NamingOrthographyError):
        normalize_managed_name("维护指引.txt", "zh-HK", ".txt")


def test_conversion_exception_itself_refuses_suggestion(monkeypatch):
    import opencc
    from src.core.naming_orthography import NamingOrthographyError, normalize_managed_name
    converter = opencc.OpenCC("s2hk")
    def fail(value):
        raise RuntimeError("private-marker")
    monkeypatch.setattr(converter, "convert", fail)
    monkeypatch.setattr(opencc, "OpenCC", lambda config: converter)
    with pytest.raises(NamingOrthographyError):
        normalize_managed_name("维护指引.txt", "zh-HK", ".txt")
