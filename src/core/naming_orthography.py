"""Offline orthography of validated, newly generated managed names only.

OpenCC's packaged dictionaries resolve script variants, not semantic meaning.
Do not pass source evidence, saved suggestions or history through this module.
"""
from __future__ import annotations

import unicodedata

from src.core.filename_validator import validate_filename


class NamingOrthographyError(ValueError):
    def __init__(self):
        super().__init__("Invalid naming response")


def normalize_managed_name(name: str, locale: str, extension: str, *, smart=False) -> str:
    """Convert only Chinese name components, preserving ASCII and the extension.

    The caller must first validate schema, grounding and understanding. Every
    converted component is validated again; failure never falls back to raw text.
    Converters are per-call: no persisted names, field cache or shared mutable
    converter state can outlive the captured request's locale.
    """
    if locale not in {"zh-CN", "zh-HK"}:
        return name
    try:
        from opencc import OpenCC

        converter = OpenCC("s2hk" if locale == "zh-HK" else "t2s")
        # Pinned implementation loads local config and dictionaries eagerly.
        # An empty/malformed resource set must not silently claim conversion.
        if not converter._dict_chain_data or not converter.dict_cache or any(
                not entry[2] for entry in converter.dict_cache.values()):
            raise NamingOrthographyError()
        components = name.split("/")
        if extension and not components[-1].endswith(extension):
            raise NamingOrthographyError()
        stems = components[:-1] + [components[-1][:-len(extension)] if extension else components[-1]]
        converted = []
        for stem in stems:
            value = converter.convert(stem)
            if (type(value) is not str
                    or "".join(ch for ch in stem if ch.isascii()) != "".join(ch for ch in value if ch.isascii())
                    or any(unicodedata.category(ch).startswith("C") for ch in value)):
                raise NamingOrthographyError()
            converted.append(value)
        if smart and (len(converted) != 1 or len(converted[0].encode("utf-16-le")) // 2 > 180):
            raise NamingOrthographyError()
        converted[-1] += extension
        if (any(not validate_filename(part).is_valid for part in converted[:-1])
                or not validate_filename(converted[-1], extension).is_valid):
            raise NamingOrthographyError()
        return "/".join(converted)
    except Exception:
        raise NamingOrthographyError() from None
