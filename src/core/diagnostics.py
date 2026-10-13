"""Redacted diagnostics preview and deterministic ZIP export."""
from __future__ import annotations

import json
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SENSITIVE_KEYS = {"api_key", "apikey", "credential", "secret", "token", "password", "file_content", "raw_ai_request", "request_body"}


def _redact_text(value: object) -> str:
    text = str(value)
    if re.search(r"(?i)(file_content|raw_ai_request|request_body)\s*=", text):
        return "<redacted-sensitive-record>"
    text = re.sub(r"(?i)authorization\s*:\s*bearer\s+\S+", "Authorization: <redacted>", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "<redacted>", text)
    # Diagnostics promise never to expose a complete local or UNC path.
    # Redact any absolute Windows drive path and any UNC share, regardless of
    # which drive or profile directory it lives under.
    text = re.sub(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[/\\][^\s,;\]\[\}\{\)\(\"']+", "<redacted-path>", text)
    text = re.sub(r"(?<![\\])\\\\[^\s,;\]\[\}\{\)\(\"']+", "<redacted-path>", text)
    return text[:1000]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(sensitive in normalized for sensitive in _SENSITIVE_KEYS):
                continue
            result[str(key)] = _redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(value)


class DiagnosticsExporter:
    def __init__(self, app_version: str = "unknown", platform_name: str | None = None) -> None:
        self._version = app_version
        self._platform = platform_name or platform.system()

    def preview(self, *, components: list[dict], settings: dict,
                logs: list[str]) -> dict:
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "app_version": self._version,
            "platform": self._platform,
            "components": _redact(components),
            "settings": _redact(settings),
            "logs": _redact(logs),
            "privacy": {
                "credentials_included": False,
                "file_content_included": False,
                "raw_ai_requests_included": False,
                "full_paths_included": False,
            },
        }

    @staticmethod
    def export(path: str | Path, preview: dict) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_redact(preview), ensure_ascii=False, indent=2, sort_keys=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("diagnostics.json", payload)
        return target