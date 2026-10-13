"""Capability degradation — pure logic, no network, no credentials.

Consistent decision rules for EVERY input kind against the CURRENT
provider's capabilities:

1. ``text=False`` → every content kind degrades with
   ``text_capability_unavailable``; nothing may PROCEED without text.
2. TEXT proceeds when ``text=True`` (vision is irrelevant for text).
3. Structured naming output needs ``json_mode=True`` OR ``json_schema=True``
   — when both are False, TEXT/IMAGE/SCANNED_PDF/VIDEO ALL degrade with
   ``structured_output_unavailable``; text never bypasses the check.
4. IMAGE/SCANNED_PDF/VIDEO additionally require ``vision=True`` (each with
   its own stable reason).
5. VIDEO capability is only ever expressed as LOCAL KEYFRAMES analyzed as
   images — never as uploading the full video or native video understanding.
6. UNKNOWN content kind degrades with ``unsupported_content_kind`` — never
   silently treated as text.
7. Decisions carry a stable ``user_message_id`` + ``reason`` ONLY.  No
   hardcoded user-facing copy lives in the domain layer — i18n resolves it.
8. No provider switching: the decision is about the current provider only;
   there is no switch field and no other provider is ever read.

Pure data in, pure data out.  No file content, paths, keys, prompts, or
network ever enter a decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ── Stable reason codes + i18n message ids (never raw copy) ──────────────────

TEXT_CAPABILITY_UNAVAILABLE = "text_capability_unavailable"
STRUCTURED_OUTPUT_UNAVAILABLE = "structured_output_unavailable"
VISION_UNAVAILABLE_IMAGE = "vision_unavailable_image"
VISION_UNAVAILABLE_SCANNED_PDF = "vision_unavailable_scanned_pdf"
VISION_UNAVAILABLE_VIDEO = "vision_unavailable_video"
UNSUPPORTED_CONTENT_KIND = "unsupported_content_kind"

# user_message_id → i18n key (id lives here; the localized text lives in
# src/utils/i18n/locales/*.json under the same capability.* namespace)
_MESSAGE_ID_KEY = {
    TEXT_CAPABILITY_UNAVAILABLE: "capability.text_capability_unavailable",
    STRUCTURED_OUTPUT_UNAVAILABLE: "capability.structured_output_unavailable",
    VISION_UNAVAILABLE_IMAGE: "capability.vision_unavailable_image",
    VISION_UNAVAILABLE_SCANNED_PDF: "capability.vision_unavailable_scanned_pdf",
    VISION_UNAVAILABLE_VIDEO: "capability.vision_unavailable_video",
    UNSUPPORTED_CONTENT_KIND: "capability.unsupported_content_kind",
}


# ── Content kinds the naming pipeline may encounter ──────────────────────────

class ContentKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    SCANNED_PDF = "scanned_pdf"
    VIDEO = "video"
    UNKNOWN = "unknown"


# ── Decision ─────────────────────────────────────────────────────────────────

class DegradationAction(str, Enum):
    PROCEED = "proceed"
    DEGRADE = "degrade"


@dataclass(frozen=True)
class DegradationDecision:
    """Pure-data outcome of a capability check.

    ``reason`` is the stable machine code; ``user_message_id`` is the i18n
    key the UI resolves to localized copy.  The domain layer NEVER holds
    user-facing text.
    """

    action: DegradationAction
    reason: str = ""
    user_message_id: str = ""

    @property
    def degraded(self) -> bool:
        return self.action is DegradationAction.DEGRADE


def _proceed() -> DegradationDecision:
    return DegradationDecision(action=DegradationAction.PROCEED)


def _degrade(reason: str) -> DegradationDecision:
    return DegradationDecision(
        action=DegradationAction.DEGRADE,
        reason=reason,
        user_message_id=_MESSAGE_ID_KEY[reason],
    )


# ── Handler ──────────────────────────────────────────────────────────────────

class DegradationHandler:
    """Pure capability decision logic for one provider profile."""

    def decide(self, capabilities, content_kind: ContentKind) -> DegradationDecision:
        """Decide what happens for one content kind under one capability set.

        ``capabilities`` duck-types ``ProviderCapabilities`` (text, vision,
        multi_image, json_mode, json_schema).  Never touches network,
        credentials, file contents, or other providers.
        """
        kind = content_kind if isinstance(content_kind, ContentKind) else ContentKind(str(content_kind))

        # Rule 1: no text capability → nothing can proceed
        if not getattr(capabilities, "text", False):
            return _degrade(TEXT_CAPABILITY_UNAVAILABLE)

        # Rule 6: UNKNOWN is never silently treated as text
        if kind is ContentKind.UNKNOWN:
            return _degrade(UNSUPPORTED_CONTENT_KIND)

        # Rule 4: visual kinds require vision (each with its own reason)
        if kind is ContentKind.IMAGE and not getattr(capabilities, "vision", False):
            return _degrade(VISION_UNAVAILABLE_IMAGE)
        if kind is ContentKind.SCANNED_PDF and not getattr(capabilities, "vision", False):
            return _degrade(VISION_UNAVAILABLE_SCANNED_PDF)
        if kind is ContentKind.VIDEO and not getattr(capabilities, "vision", False):
            return _degrade(VISION_UNAVAILABLE_VIDEO)

        # Rule 3: structured naming output needs json_mode OR json_schema —
        # consistent for TEXT/IMAGE/SCANNED_PDF/VIDEO alike
        if not (
            getattr(capabilities, "json_mode", False)
            or getattr(capabilities, "json_schema", False)
        ):
            return _degrade(STRUCTURED_OUTPUT_UNAVAILABLE)

        return _proceed()
