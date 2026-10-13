"""Shared watch analysis protocol — one extraction/analysis contract for
BOTH the Review First and Auto Apply pipelines (no second engine).

The analysis service is always injected; tests use fakes.  A structured
capability error is returned as a normal result (never a fake success).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisResult:
    """Pure-data result of one watch analysis pass."""

    suggested_name: str      # full target filename, INCLUDING extension
    confidence: float
    content_kind: str = "text"
    quality_mode: str = "balanced"
    error_category: str = ""  # "" = ok; e.g. "capability_unsupported"

    @property
    def ok(self) -> bool:
        return self.error_category == ""


class AnalysisService:
    """Injectable analysis boundary: ``analyze(source_path, template_id,
    quality_mode) -> AnalysisResult``.

    Real implementations may raise; handlers normalize exceptions into
    ``AnalysisResult(error_category=...)``.
    """

    def analyze(
        self,
        source_path: str,
        template_id: str = "",
        quality_mode: str = "balanced",
    ) -> AnalysisResult:
        raise NotImplementedError
