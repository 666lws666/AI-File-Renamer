"""Capability degradation — pure logic, no network, no credentials.

The decision rules are CONSISTENT across every input kind:

1. ``capabilities.text=False`` → every kind degrades with
   ``text_capability_unavailable`` (nothing may PROCEED without text).
2. TEXT proceeds only when ``text=True`` (vision is irrelevant for text).
3. Structured naming output needs ``json_mode=True`` OR ``json_schema=True``
   — when both are False, TEXT/IMAGE/SCANNED_PDF/VIDEO ALL degrade with
   ``structured_output_unavailable``; text never bypasses this check.
4. IMAGE/SCANNED_PDF/VIDEO additionally require ``vision=True`` (each with
   its own stable reason).
5. VIDEO capability is only ever expressed as "local keyframes analyzed as
   images" — the message id's translations must say exactly that.
6. UNKNOWN content kind degrades with ``unsupported_content_kind`` — it is
   never silently treated as text.
7. Decisions carry a stable ``user_message_id`` + ``reason`` ONLY — no
   hardcoded user-facing copy in the domain layer; i18n resolves copy.
8. Never switch providers: no switch_provider field, no reading other
   providers, no implicit switching.
"""
import json
from pathlib import Path

import pytest

from src.core.degradation import (
    TEXT_CAPABILITY_UNAVAILABLE,
    STRUCTURED_OUTPUT_UNAVAILABLE,
    UNSUPPORTED_CONTENT_KIND,
    VISION_UNAVAILABLE_IMAGE,
    VISION_UNAVAILABLE_SCANNED_PDF,
    VISION_UNAVAILABLE_VIDEO,
    ContentKind,
    DegradationAction,
    DegradationDecision,
    DegradationHandler,
)
from src.core.provider_protocol import ProviderCapabilities

ROOT = Path(__file__).parent.parent.parent


def _caps(**kw) -> ProviderCapabilities:
    defaults = {"text": True, "vision": False, "multi_image": False,
                "json_mode": True, "json_schema": False}
    defaults.update(kw)
    return ProviderCapabilities(**defaults)


def _handler() -> DegradationHandler:
    return DegradationHandler()


def _degrade(reason: str) -> DegradationDecision:
    """Factory for the expected degrade decisions (mirrors the handler)."""
    from src.core.degradation import _MESSAGE_ID_KEY
    return DegradationDecision(
        action=DegradationAction.DEGRADE,
        reason=reason,
        user_message_id=_MESSAGE_ID_KEY[reason],
    )


def _proceed() -> DegradationDecision:
    return DegradationDecision(action=DegradationAction.PROCEED)


# ============================================================================
# text=False gates EVERYTHING
# ============================================================================

@pytest.mark.parametrize("kind", [k for k in ContentKind])
def test_text_false_all_kinds_degrade(kind):
    decision = _handler().decide(_caps(text=False), kind)
    assert decision.action == "degrade"
    assert decision.reason == TEXT_CAPABILITY_UNAVAILABLE


# ============================================================================
# TEXT: needs text=True; vision irrelevant; structured check applies
# ============================================================================

def test_text_proceeds_with_text_and_structured():
    decision = _handler().decide(_caps(), ContentKind.TEXT)
    assert decision == _proceed()


def test_text_proceeds_without_vision():
    decision = _handler().decide(
        _caps(text=True, vision=False), ContentKind.TEXT)
    assert decision.action == "proceed"


def test_text_degrades_without_structured_capability():
    """Text must NOT bypass the structured-output check."""
    decision = _handler().decide(
        _caps(text=True, json_mode=False, json_schema=False), ContentKind.TEXT)
    assert decision == _degrade(reason=STRUCTURED_OUTPUT_UNAVAILABLE)


# ============================================================================
# IMAGE / SCANNED_PDF / VIDEO: vision required, each with own reason
# ============================================================================

def test_image_degrades_without_vision():
    decision = _handler().decide(_caps(), ContentKind.IMAGE)
    assert decision == _degrade(reason=VISION_UNAVAILABLE_IMAGE)


def test_image_proceeds_with_vision_and_structured():
    decision = _handler().decide(_caps(vision=True), ContentKind.IMAGE)
    assert decision.action == "proceed"


def test_scanned_pdf_degrades_without_vision():
    decision = _handler().decide(_caps(), ContentKind.SCANNED_PDF)
    assert decision == _degrade(reason=VISION_UNAVAILABLE_SCANNED_PDF)


def test_scanned_pdf_proceeds_with_vision_and_structured():
    decision = _handler().decide(_caps(vision=True), ContentKind.SCANNED_PDF)
    assert decision.action == "proceed"


def test_video_degrades_without_vision():
    decision = _handler().decide(_caps(), ContentKind.VIDEO)
    assert decision == _degrade(reason=VISION_UNAVAILABLE_VIDEO)


def test_video_proceeds_with_vision_and_structured():
    decision = _handler().decide(_caps(vision=True), ContentKind.VIDEO)
    assert decision.action == "proceed"


# ============================================================================
# Structured output: consistent across ALL four known kinds
# ============================================================================

@pytest.mark.parametrize("kind", [
    ContentKind.TEXT,
    ContentKind.IMAGE,
    ContentKind.SCANNED_PDF,
    ContentKind.VIDEO,
])
def test_all_kinds_degrade_without_json_capabilities(kind):
    caps = _caps(vision=True, json_mode=False, json_schema=False)
    decision = _handler().decide(caps, kind)
    assert decision == _degrade(reason=STRUCTURED_OUTPUT_UNAVAILABLE)


@pytest.mark.parametrize("kind", [
    ContentKind.TEXT,
    ContentKind.IMAGE,
    ContentKind.SCANNED_PDF,
    ContentKind.VIDEO,
])
def test_all_kinds_proceed_with_json_mode(kind):
    decision = _handler().decide(_caps(vision=True, json_mode=True), kind)
    assert decision.action == "proceed"


@pytest.mark.parametrize("kind", [
    ContentKind.TEXT,
    ContentKind.IMAGE,
    ContentKind.SCANNED_PDF,
    ContentKind.VIDEO,
])
def test_all_kinds_proceed_with_json_schema(kind):
    decision = _handler().decide(
        _caps(vision=True, json_mode=False, json_schema=True), kind)
    assert decision.action == "proceed"


# ============================================================================
# UNKNOWN content kind
# ============================================================================

def test_unknown_content_kind_degrades_never_treated_as_text():
    decision = _handler().decide(_caps(), ContentKind.UNKNOWN)
    assert decision == _degrade(reason=UNSUPPORTED_CONTENT_KIND)


def test_unknown_with_full_capabilities_still_unsupported():
    decision = _handler().decide(
        _caps(vision=True, json_mode=True), ContentKind.UNKNOWN)
    assert decision == _degrade(reason=UNSUPPORTED_CONTENT_KIND)


# ============================================================================
# Domain decisions carry ONLY stable ids — never hardcoded user copy
# ============================================================================

def test_all_decisions_carry_user_message_id_not_hardcoded_copy():
    handler = _handler()
    cases = [
        (_caps(text=False), ContentKind.TEXT),
        (_caps(), ContentKind.IMAGE),
        (_caps(), ContentKind.SCANNED_PDF),
        (_caps(), ContentKind.VIDEO),
        (_caps(vision=True, json_mode=False, json_schema=False), ContentKind.TEXT),
        (_caps(vision=True, json_mode=False, json_schema=False), ContentKind.VIDEO),
        (_caps(), ContentKind.UNKNOWN),
        (_caps(), ContentKind.TEXT),
    ]
    for caps, kind in cases:
        decision = handler.decide(caps, kind)
        if decision.degraded:
            assert decision.user_message_id, (
                f"degraded decision must carry a user_message_id ({kind})")
            assert "message" not in decision.__dataclass_fields__, (
                "domain decisions must not carry hardcoded user copy")


def test_proceed_decisions_have_no_reason_or_message_id():
    decision = _handler().decide(_caps(), ContentKind.TEXT)
    assert decision.reason == ""
    assert decision.user_message_id == ""


# ============================================================================
# Locale copy: video keyframes-as-images wording in zh-CN and en-US
# ============================================================================

def _locale(key):
    raw = (ROOT / "src" / "utils" / "i18n" / "locales" / f"{key}.json").read_text(
        encoding="utf-8")
    return json.loads(raw)


def test_video_translations_say_keyframes_analyzed_as_images():
    for locale in ("zh_CN", "en_US"):
        data = _locale(locale)
        text = data["capability.vision_unavailable_video"]
        lowered = text.casefold()
        if locale == "zh_CN":
            assert "关键帧" in text and "图片" in text
        else:
            assert "keyframe" in lowered and "image" in lowered
        # never implies uploading the full video or native video understanding
        assert "上传" not in text and "原生" not in text
        assert "upload" not in lowered and "native" not in lowered


def test_structured_output_translations_exist():
    for locale in ("zh_CN", "en_US"):
        data = _locale(locale)
        assert "capability.structured_output_unavailable" in data
        assert "capability.text_capability_unavailable" in data
        assert "capability.unsupported_content_kind" in data
        assert "capability.vision_unavailable_image" in data
        assert "capability.vision_unavailable_scanned_pdf" in data
        assert "capability.vision_unavailable_video" in data


# ============================================================================
# No provider switching anywhere
# ============================================================================

def test_decision_has_no_provider_switch_surface():
    decision = _handler().decide(_caps(), ContentKind.VIDEO)
    assert not hasattr(decision, "switch_provider")
    assert not hasattr(decision, "provider_id")
    assert "switch" not in decision.reason
