"""Pure product local-naming protocol contracts and frozen probe parity."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts import run_local_inference_probe as probe
from src.core.naming_fields import NamingFields
from src.core.template_model import STANDARD_FIELDS, Template
from src.core.template_renderer import RenderStatus, TemplateRenderer


TEXT = "Date: 2024-05\nVersion: v2\nBudget plan"
TOPICS = {"zh-CN": "预算规划", "zh-HK": "預算規劃", "en-US": "Budget planning"}
FROZEN = {
    "zh-CN": ("9783e7eeebe9ec8af067ee16d4c123308c2a425412d12d3f35d0cc409ef7ce1f",
              "4ba972800e857182be120801ad6107cde2b35a1c247194f5621dbba9e30f0f6e",
              "540eada755d601c2769d21ba9cb84ce1fd99d26bec5af024caf7282b7b02b2e2"),
    "zh-HK": ("33957c30ed380a365a5e70c7e95959066a4dc728b4b7fbbf931c9f214af6b2fe",
              "819a8d75ffdc9e6de0c139916dc50f20b06fd07c0f733ddca7baf7576877a67b",
              "b428b5eaec592cd82f86289fe1f5aeb0c6a139a1e68c96210c298d035246500f"),
    "en-US": ("60f26b03f8e579b54c2dc422ce7c5be65e9055570e2a4729b5d95daf93d4c222",
              "bae2c681f0b7df545a550460910133bd584585475b4ea225420d75318636269c",
              "aeaf1290bdaf34fc1862292efff685796380b46693a171971d2ba3c17147d946"),
}


def _digest(value) -> str:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segment(value: str, evidence: str, source: str = "text") -> dict:
    return {"value": value, "evidence": evidence, "evidence_source": source}


def _raw(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("locale", TOPICS)
def test_frozen_probe_prompt_schema_and_result_before_move(locale):
    bank = probe.text_evidence_spans(TEXT)
    payload = {"understood": True, "language": locale,
               "topic": _segment(TOPICS[locale], "T002"),
               "date": _segment("2024-05", "T000"),
               "version": _segment("v2", "T001")}
    actual = (
        _digest(probe._build_prompt(locale, TEXT, has_text=True, has_visuals=False)),
        _digest(probe.local_schema(locale, has_text=True, has_visuals=False, text_evidence=bank)),
        _digest(probe.decode_response(_raw(payload), locale, has_text=True,
                                      has_visuals=False, text_evidence=bank)),
    )
    assert actual == FROZEN[locale]


def test_product_module_exposes_single_smart_implementation_and_five_locales():
    from src.services.local_ai import naming_protocol as product

    assert product.SUPPORTED_NAMING_LOCALES == ("zh-CN", "zh-HK", "en-US", "ja-JP", "es-ES")
    assert product.build_smart_prompt is product._build_prompt
    assert product.text_evidence_spans is probe.text_evidence_spans
    assert product.decode_response is probe.decode_response


@pytest.mark.parametrize("locale,topic", [("ja-JP", "予算計画"), ("es-ES", "Planificación presupuestaria")])
def test_new_filename_languages_have_smart_schema_prompt_and_strict_decode(locale, topic):
    from src.services.local_ai import naming_protocol as product

    bank = product.text_evidence_spans(TEXT)
    assert product.local_schema(locale, has_text=True, has_visuals=False, text_evidence=bank)
    assert locale in product.build_smart_prompt(locale, TEXT, has_text=True, has_visuals=False)
    payload = {"understood": True, "language": locale,
               "topic": _segment(topic, "T002"), "date": None, "version": None}
    result = product.decode_response(_raw(payload), locale, has_text=True,
                                     has_visuals=False, text_evidence=bank)
    assert result["parts"] == [{"role": "topic", **_segment(topic, "Budget plan")}]


def test_deep_json_is_fixed_value_error_not_recursion_error():
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError, match="response is not one strict JSON object"):
        product.decode_response(("[" * 1500 + "0" + "]" * 1500).encode(),
                                "en-US", has_text=False, has_visuals=True)


@pytest.mark.parametrize("locale", ("zh-CN", "zh-HK", "en-US", "ja-JP", "es-ES"))
def test_visual_date_generation_observes_evidence_before_selecting_precision(locale):
    from src.services.local_ai import naming_protocol as product

    schema = product.local_schema(locale, has_text=False, has_visuals=True)
    date_branches = schema["oneOf"][1]["properties"]["date"]["oneOf"]
    visual_date = next(branch for branch in date_branches if branch["type"] == "object")
    assert list(visual_date["properties"]) == ["evidence_source", "evidence", "value"]
    assert visual_date["required"] == ["evidence_source", "evidence", "value"]
    assert visual_date["properties"]["value"]["pattern"] == product.VISUAL_DATE_PATTERN
    prompt = product.build_smart_prompt(locale, "", has_text=False, has_visuals=True)
    assert "YYYY-MM" in prompt and "YYYY-MM-DD" in prompt


@pytest.mark.parametrize("date_value,accepted", [
    ("2026", False), ("2026-08", True), ("2026-08-01", False),
])
def test_scan_month_evidence_neither_loses_precision_nor_invents_day(date_value, accepted):
    from src.services.local_ai import naming_protocol as product
    from src.core.smart_naming import SmartNamingError, SmartNamingPolicy

    payload = {"understood": True, "language": "zh-HK",
               "topic": _segment("青禾咖啡館咖啡機與鍋爐維護記錄",
                                 "咖啡機維護確認及鍋爐除垢與密封圈更換", "visual"),
               "date": _segment(date_value, "第一頁文件顯示維護時間：2026年8月", "visual"),
               "version": _segment("v1.1", "第二頁文件顯示版本：v1.1", "visual")}
    fields = product.decode_response(_raw(payload), "zh-HK", has_text=False, has_visuals=True)
    if accepted:
        assert SmartNamingPolicy("zh-HK").render(
            fields, extracted_text="", has_visuals=True, extension=".pdf"
        ) == "2026-08_青禾咖啡館咖啡機與鍋爐維護記錄_v1.1.pdf"
    else:
        with pytest.raises(SmartNamingError, match="smart.error.ungrounded"):
            SmartNamingPolicy("zh-HK").render(
                fields, extracted_text="", has_visuals=True, extension=".pdf")


def test_template_uses_only_enabled_pattern_fields_in_template_order():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Only title", pattern="{dcTitle}", fields=STANDARD_FIELDS)
    schema = product.template_schema(template, "en-US", has_text=False, has_visuals=True)
    fields = schema["oneOf"][1]["properties"]["fields"]
    assert list(fields["properties"]) == ["dcTitle"]
    assert fields["required"] == ["dcTitle"]
    assert "dcDate" not in fields["properties"]


def test_nullable_required_field_remains_missing_at_renderer_gate():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Default")
    raw = _raw({"understood": True, "language": "en-US", "fields": {
        "dcDate": None, "dcTitle": _segment("Budget plan", "T000")}})
    fields = product.decode_template_response(raw, template, "en-US", has_text=True,
                                              has_visuals=False, text_evidence={"T000": "Budget plan"})
    assert isinstance(fields, NamingFields)
    assert fields.dcDate is None
    assert TemplateRenderer.render(template, fields, ".pdf").status is RenderStatus.NEEDS_REGENERATION


def test_title_only_template_can_render_without_invented_date():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    fields = product.decode_template_response(
        _raw({"understood": True, "language": "en-US", "fields": {
            "dcTitle": _segment("Budget plan", "T000")}}),
        template, "en-US", has_text=True, has_visuals=False,
        text_evidence={"T000": "Budget plan"})
    result = TemplateRenderer.render(template, fields, ".pdf")
    assert result.status is RenderStatus.READY
    assert result.rendered_name == "Budget_plan.pdf"


@pytest.mark.parametrize("locale", ("zh-CN", "zh-HK", "en-US", "ja-JP", "es-ES"))
def test_template_prompt_is_localized_and_contains_bounded_bank(locale):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    prompt = product.build_template_prompt(template, locale, "Budget plan", has_text=True,
                                           has_visuals=False)
    assert locale in prompt
    assert '"T000":"Budget plan"' in prompt
    assert "dcTitle" in prompt
    assert "dcDate" not in prompt


def test_template_contiguous_prompt_uses_the_same_multiline_bank_as_decoder():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    bank = product.text_evidence_spans(TEXT, text_layout="contiguous")
    assert bank == {"T000": TEXT}
    prompt = product.build_template_prompt(template, "en-US", TEXT, has_text=True,
        has_visuals=False, text_layout="contiguous", text_evidence=bank)
    assert json.dumps(bank, ensure_ascii=False, separators=(",", ":")) in prompt
    assert product.decode_template_response(
        _raw({"understood": True, "language": "en-US", "fields": {
            "dcTitle": _segment("Budget planning", "T000")}}), template, "en-US",
        has_text=True, has_visuals=False, text_evidence=bank).dcTitle == "Budget planning"


def test_template_explicit_lines_matches_default_prompt_byte_for_byte():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    original = product.build_template_prompt(template, "en-US", TEXT,
        has_text=True, has_visuals=False)
    assert product.build_template_prompt(template, "en-US", TEXT,
        has_text=True, has_visuals=False, text_layout="lines") == original


@pytest.mark.parametrize("layout,has_text,has_visuals", [
    ("invalid", True, False), ("contiguous", False, True), ("contiguous", True, True),
])
def test_template_rejects_unsupported_layout_combinations(layout, has_text, has_visuals):
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError):
        product.build_template_prompt(Template(name="Title"), "en-US", TEXT,
            has_text=has_text, has_visuals=has_visuals, text_layout=layout)


@pytest.mark.parametrize("has_text,has_visuals,source,evidence", [
    (True, False, "text", "T000"),
    (False, True, "visual", "Page heading reads Budget plan"),
    (True, True, "visual", "Page heading reads Budget plan"),
])
def test_template_decoder_accepts_available_modalities(has_text, has_visuals, source, evidence):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    fields = product.decode_template_response(
        _raw({"understood": True, "language": "en-US", "fields": {
            "dcTitle": _segment("Budget plan", evidence, source)}}),
        template, "en-US", has_text=has_text, has_visuals=has_visuals,
        text_evidence={"T000": "Budget plan"} if has_text else None)
    assert fields.dcTitle == "Budget plan"


def test_template_false_understanding_is_explicit_refusal():
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError, match="template.error.insufficientContent"):
        product.decode_template_response(_raw({"understood": False, "language": "en-US"}),
                                         Template(name="Title", pattern="{dcTitle}"),
                                         "en-US", has_text=False, has_visuals=True)


@pytest.mark.parametrize("payload", [
    {"understood": True, "language": "zh-CN", "fields": {"dcTitle": None}},
    {"understood": "true", "language": "en-US", "fields": {"dcTitle": None}},
    {"understood": True, "language": "en-US", "fields": {}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": None, "dcDate": None}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": {"value": "x"}}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": _segment("x", "T999")}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": _segment("x", "T000", "visual")}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": _segment(4, "T000")}},
    {"understood": True, "language": "en-US", "fields": {"dcTitle": _segment("x", "T000")}, "extra": 1},
    {"understood": False, "language": "en-US", "fields": {}},
])
def test_template_rejects_wrong_keys_types_language_ids_and_modality(payload):
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError):
        product.decode_template_response(_raw(payload), Template(name="Title", pattern="{dcTitle}"),
                                         "en-US", has_text=True, has_visuals=False,
                                         text_evidence={"T000": "literal"})


@pytest.mark.parametrize("raw", [
    b'{"understood":true,"understood":true,"language":"en-US","fields":{"dcTitle":null}}',
    b'{"understood":true,"language":"en-US","fields":{"dcTitle":null},"n":NaN}',
    b'{"understood":true,"language":"en-US","fields":{"dcTitle":null}} trailing',
    b'\xff',
    b' ' * (262144 + 1),
    ("[" * 1500 + "0" + "]" * 1500).encode(),
], ids=["duplicate", "nonfinite", "trailing", "invalid-utf8", "oversize", "deep"])
def test_template_rejects_non_strict_and_deep_json(raw):
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError):
        product.decode_template_response(raw, Template(name="Title", pattern="{dcTitle}"),
                                         "en-US", has_text=False, has_visuals=True)


@pytest.mark.parametrize("value", ["C:/private", "..\\private", "CON", "CON.txt",
                                   "bad\x01name", "trailing.", "trailing ", "x" * 181])
def test_template_rejects_unsafe_or_oversized_value_without_truncation(value):
    from src.services.local_ai import naming_protocol as product

    with pytest.raises(ValueError):
        product.decode_template_response(
            _raw({"understood": True, "language": "en-US", "fields": {
                "dcTitle": _segment(value, "visible title", "visual")}}),
            Template(name="Title", pattern="{dcTitle}"), "en-US",
            has_text=False, has_visuals=True)


@pytest.mark.parametrize("field,value", [
    ("dcCreator", "Dr. Smith"),
    ("dcIdentifier", "ABC_123"),
])
def test_template_accepts_safe_internal_dot_and_underscore(field, value):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Single field", pattern="{" + field + "}")
    fields = product.decode_template_response(
        _raw({"understood": True, "language": "en-US", "fields": {
            field: _segment(value, "Field visibly reads " + value, "visual")}}),
        template, "en-US", has_text=False, has_visuals=True)
    assert getattr(fields, field) == value


@pytest.mark.parametrize("date,evidence", [
    ("2024-05-01", "Date: 2024-05"),
    ("2024", "Date: 2024-05"),
    ("2024-02-30", "Date: 2024-02-30"),
])
def test_visual_date_rejects_invented_precision_or_invalid_calendar(date, evidence):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Dated", pattern="{dcDate}")
    with pytest.raises(ValueError):
        product.decode_template_response(
            _raw({"understood": True, "language": "en-US", "fields": {
                "dcDate": _segment(date, evidence, "visual")}}),
            template, "en-US", has_text=False, has_visuals=True)


def test_text_date_requires_exact_registered_candidate_and_can_remain_null():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Dated", pattern="{dcDate}")
    bank = {"T000": "Date: 2024-05"}
    valid = {"understood": True, "language": "en-US", "fields": {
        "dcDate": _segment("2024-05", "T000")}}
    assert product.decode_template_response(_raw(valid), template, "en-US",
                                            has_text=True, has_visuals=False,
                                            text_evidence=bank).dcDate == "2024-05"
    valid["fields"]["dcDate"]["value"] = "2024-05-01"
    with pytest.raises(ValueError):
        product.decode_template_response(_raw(valid), template, "en-US",
                                         has_text=True, has_visuals=False,
                                         text_evidence=bank)
    valid["fields"]["dcDate"] = None
    assert product.decode_template_response(_raw(valid), template, "en-US",
                                            has_text=True, has_visuals=False,
                                            text_evidence=bank).dcDate is None


def test_template_prompt_rejects_mismatched_text_bank_and_unavailable_modality():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    with pytest.raises(ValueError):
        product.build_template_prompt(template, "en-US", "Budget plan", has_text=True,
                                      has_visuals=False, text_evidence={"T000": "foreign"})
    with pytest.raises(ValueError):
        product.template_schema(template, "en-US", has_text=False, has_visuals=False)


@pytest.mark.parametrize("source", [[], {}, 1])
def test_smart_and_template_reject_wrong_evidence_source_type_as_value_error(source):
    from src.services.local_ai import naming_protocol as product

    smart = {"understood": True, "language": "en-US", "topic": _segment("Budget plan", "T000", source),
             "date": None, "version": None}
    with pytest.raises(ValueError):
        product.decode_response(_raw(smart), "en-US", has_text=True, has_visuals=False,
                                text_evidence={"T000": "Budget plan"})
    template = Template(name="Title", pattern="{dcTitle}")
    with pytest.raises(ValueError):
        product.decode_template_response(
            _raw({"understood": True, "language": "en-US", "fields": {
                "dcTitle": _segment("Budget plan", "T000", source)}}),
            template, "en-US", has_text=True, has_visuals=False,
            text_evidence={"T000": "Budget plan"})


def test_template_rejects_unpaired_surrogate_as_value_error():
    from src.services.local_ai import naming_protocol as product

    raw = b'{"understood":true,"language":"en-US","fields":{"dcTitle":' \
          b'{"value":"\\ud800","evidence":"heading","evidence_source":"visual"}}}'
    with pytest.raises(ValueError):
        product.decode_template_response(raw, Template(name="Title", pattern="{dcTitle}"),
                                         "en-US", has_text=False, has_visuals=True)


def test_template_date_and_version_use_exact_registered_candidates():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Revision", pattern="{dcDate}_{extVersion}")
    bank = {"T000": "Date: 2024-05", "T001": "Version: v2"}
    payload = {"understood": True, "language": "en-US", "fields": {
        "dcDate": _segment("2024-05", "T000"), "extVersion": _segment("v2", "T001")}}
    assert product.decode_template_response(_raw(payload), template, "en-US", has_text=True,
                                            has_visuals=False, text_evidence=bank) == NamingFields(
                                                dcDate="2024-05", extVersion="v2")
    payload["fields"]["extVersion"]["value"] = "v3"
    with pytest.raises(ValueError):
        product.decode_template_response(_raw(payload), template, "en-US", has_text=True,
                                         has_visuals=False, text_evidence=bank)


def test_template_accepts_visual_month_date_only_when_observation_supports_it():
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Dated", pattern="{dcDate}")
    payload = {"understood": True, "language": "en-US", "fields": {
        "dcDate": _segment("2024-05", "Date: 2024-05", "visual")}}
    assert product.decode_template_response(_raw(payload), template, "en-US",
                                            has_text=False, has_visuals=True).dcDate == "2024-05"


def test_direct_text_bank_cannot_bypass_32k_utf8_input_limit():
    from src.services.local_ai import naming_protocol as product

    bank = {f"T{index:03d}": "x" * 2000 for index in range(17)}
    with pytest.raises(ValueError):
        product.local_schema("en-US", has_text=True, has_visuals=False,
                             text_evidence=bank)


TITLE_PROMPT_RULES = {
    "zh-CN": ("核心对象、主题或用途", "不要求原文有明确的文档标题", "内容可读且依据充分",
              "登记的文本证据 ID", "具体的视觉观察", "内容不可读或依据不足",
              "dcTitle 仍须为 null", "understood=false"),
    "zh-HK": ("核心對象、主題或用途", "不要求原文有明確的文件標題", "內容可讀且依據充分",
              "登記的文字證據 ID", "具體的視覺觀察", "內容不可讀或依據不足",
              "dcTitle 仍須為 null", "understood=false"),
    "en-US": ("actual central object, theme or purpose", "does not require an explicit document heading",
              "readable content provides sufficient evidence", "registered text evidence ID",
              "concrete visual observation", "content is unreadable or insufficient",
              "leave dcTitle null", "understood=false"),
    "ja-JP": ("実際の中心的な対象・主題・目的", "文書に明示的な見出しがなくてもよい",
              "内容が読め、十分な根拠がある場合", "登録済みのテキスト根拠 ID", "具体的な画像観察",
              "内容が読めない、または根拠が不十分", "dcTitle=null", "understood=false"),
    "es-ES": ("objeto central, tema o propósito real", "no requiere un título explícito en el documento",
              "contenido es legible y aporta evidencia suficiente", "ID de evidencia textual registrado",
              "observación visual concreta", "contenido es ilegible o insuficiente",
              "deja dcTitle en null", "understood=false"),
}

NO_TITLE_PROMPT_HASHES = {
    "zh-CN": "5574a4a336039be2d9418555e35abf2e476e891fb387c546cd5defa523a85025",
    "zh-HK": "3a0e941736bd4e1336049ab535897907320b5021b5bc3064f3ba1df96bdb3cfc",
    "en-US": "2212448516dab3f120ebad1903c16972ede11defe0f161423ac14f7e0635b76d",
    "ja-JP": "5d05518d5afb0702762148147d045190032b28fb21c924a7e789224f7259bda9",
    "es-ES": "6d5f42f0f3891a7a617870f96a9315c2ada3e287fd2a07b1a26f4788db6e9dc8",
}


@pytest.mark.parametrize("locale", TITLE_PROMPT_RULES)
def test_requested_title_prompt_defines_content_derived_grounded_title_without_heading(locale):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    # Readable body content without an explicit document title or sample answer.
    text = "Clean the filter and rinse the water tank."
    prompt = product.build_template_prompt(template, locale, text, has_text=True, has_visuals=True)
    for rule in TITLE_PROMPT_RULES[locale]:
        assert rule in prompt
    assert prompt.index(TITLE_PROMPT_RULES[locale][0]) < prompt.index("UNTRUSTED TEXT EVIDENCE BANK")
    assert '"T000":"' + text + '"' in prompt


@pytest.mark.parametrize("locale", NO_TITLE_PROMPT_HASHES)
def test_template_without_requested_title_prompt_is_byte_identical(locale):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Dated", pattern="{dcDate}")
    prompt = product.build_template_prompt(template, locale, "Date: 2024-05", has_text=True, has_visuals=False)
    assert _digest(prompt) == NO_TITLE_PROMPT_HASHES[locale]
    assert "dcTitle" not in prompt


@pytest.mark.parametrize("locale", TITLE_PROMPT_RULES)
def test_content_derived_title_semantics_keep_null_schema_decode_and_regeneration(locale):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title", pattern="{dcTitle}")
    schema = product.template_schema(template, locale, has_text=True, has_visuals=False,
                                     text_evidence={"T000": "Unreadable fragment"})
    branch = schema["oneOf"][1]["properties"]["fields"]["properties"]["dcTitle"]
    assert {"type": "null"} in branch["oneOf"]
    fields = product.decode_template_response(
        _raw({"understood": True, "language": locale, "fields": {"dcTitle": None}}),
        template, locale, has_text=True, has_visuals=False,
        text_evidence={"T000": "Unreadable fragment"})
    assert fields.dcTitle is None
    result = TemplateRenderer.render(template, fields, ".txt")
    assert result.status is RenderStatus.NEEDS_REGENERATION
    assert result.missing_fields == ("dcTitle",)
    with pytest.raises(ValueError, match="template.error.insufficientContent"):
        product.decode_template_response(_raw({"understood": False, "language": locale}),
                                         template, locale, has_text=False, has_visuals=True)


@pytest.mark.parametrize("date_value,accepted", [("2026-10", True), ("2026-10-01", False), ("2026", False)])
def test_actual_english_scan_month_evidence_routes_through_strict_smart_renderer(date_value, accepted):
    from src.services.local_ai import naming_protocol as product
    from src.core.smart_naming import SmartNamingError, SmartNamingPolicy

    payload = {"understood": True, "language": "zh-HK",
               "topic": _segment("咖啡機維護清單", "圖像顯示咖啡機維護清單", "visual"),
               "date": _segment(date_value, "圖像頂部文字顯示「October 2026」", "visual"),
               "version": _segment("2.0", "Checklist version 2.0", "visual")}
    decoded = product.decode_response(_raw(payload), "zh-HK", has_text=False, has_visuals=True)
    if accepted:
        assert SmartNamingPolicy("zh-HK").render(decoded, extracted_text="", has_visuals=True,
                                                extension=".pdf") == "2026-10_咖啡機維護清單_2.0.pdf"
    else:
        with pytest.raises(SmartNamingError, match="smart.error.ungrounded"):
            SmartNamingPolicy("zh-HK").render(decoded, extracted_text="", has_visuals=True, extension=".pdf")


@pytest.mark.parametrize("date_value,accepted", [("2026-10", True), ("2026-10-01", False), ("2026", False)])
def test_template_visual_dcdate_uses_full_english_literal_without_fabricated_day(date_value, accepted):
    from src.services.local_ai import naming_protocol as product
    from src.core.template_model import DateFormat

    template = Template(name="Monthly", pattern="{dcDate}", date_format=DateFormat.YYYY_MM)
    payload = {"understood": True, "language": "zh-HK", "fields": {
        "dcDate": _segment(date_value, "圖像頂部文字顯示「October 2026」", "visual")}}
    if accepted:
        decoded = product.decode_template_response(_raw(payload), template, "zh-HK",
                                                    has_text=False, has_visuals=True)
        assert decoded.dcDate == "2026-10"
        assert TemplateRenderer.render(template, decoded, ".pdf").rendered_name == "2026-10.pdf"
    else:
        with pytest.raises(ValueError, match="ungrounded visual date"):
            product.decode_template_response(_raw(payload), template, "zh-HK", has_text=False, has_visuals=True)


@pytest.mark.parametrize("locale", TITLE_PROMPT_RULES)
@pytest.mark.parametrize("pattern,metadata_needed,date_needed", [
    ("{dcTitle}", False, False),
    ("{dcTitle}_{dcSubject}", False, False),
    ("{dcDate}_{dcTitle}", True, True),
    ("{dcTitle}_{extVersion}", True, False),
])
def test_title_prompt_includes_only_relevant_metadata_and_date_footer(locale, pattern, metadata_needed, date_needed):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Field-selected composition", pattern=pattern)
    bank = product.text_evidence_spans(TEXT)
    prompt = product.build_template_prompt(template, locale, TEXT, has_text=True, has_visuals=False)
    bank_block = "UNTRUSTED TEXT EVIDENCE BANK\n" + json.dumps(bank, ensure_ascii=False, separators=(",", ":"))
    assert bank_block in prompt
    choices_block = "ALLOWED TEXT METADATA CHOICES\n" + json.dumps(
        product.text_metadata_choices(bank), ensure_ascii=False, separators=(",", ":"))
    assert (choices_block in prompt) is metadata_needed
    footer = "Preserve exact source date precision; never add a missing month or day."
    assert (footer in prompt) is date_needed
    assert prompt.endswith(product._TEMPLATE_TITLE_SEMANTICS[locale])


@pytest.mark.parametrize("locale", TITLE_PROMPT_RULES)
@pytest.mark.parametrize("has_text,has_visuals", [(True, False), (False, True), (True, True)])
def test_title_grounding_and_refusal_remains_final_trusted_instruction_after_all_input(locale, has_text, has_visuals):
    from src.services.local_ai import naming_protocol as product

    template = Template(name="Title and date", pattern="{dcDate}_{dcTitle}")
    prompt = product.build_template_prompt(template, locale, TEXT if has_text else "",
                                           has_text=has_text, has_visuals=has_visuals)
    final_rule = prompt.rsplit("\n\n", 1)[-1]
    assert final_rule == product._TEMPLATE_TITLE_SEMANTICS[locale]
    for rule in TITLE_PROMPT_RULES[locale]:
        assert rule in final_rule
    assert prompt.count(product._TEMPLATE_TITLE_SEMANTICS[locale]) == 2
    if has_text:
        assert prompt.rindex(final_rule) > prompt.index("ALLOWED TEXT METADATA CHOICES")
    if has_visuals:
        assert prompt.rindex(final_rule) > prompt.index("Inspect only the actually supplied prepared visual image(s).")
    assert prompt.rindex(final_rule) > prompt.index("Preserve exact source date precision;")


def test_prompt_composition_uses_only_enabled_pattern_requested_fields():
    from src.services.local_ai import naming_protocol as product
    from src.core.template_model import TemplateField

    template = Template(name="Unused disabled metadata", pattern="{dcTitle}", fields=(
        TemplateField("dcTitle", "Title", order=1), TemplateField("dcDate", "Date", order=2, enabled=False),
        TemplateField("extVersion", "Version", order=3, enabled=False)))
    prompt = product.build_template_prompt(template, "en-US", TEXT, has_text=True, has_visuals=False)
    assert 'Requested fields: ["dcTitle"]' in prompt
    assert "ALLOWED TEXT METADATA CHOICES" not in prompt
    assert "Preserve exact source date precision;" not in prompt
    assert prompt.endswith(product._TEMPLATE_TITLE_SEMANTICS["en-US"])


def test_title_only_text_prompt_matches_root_experiment_bytes_without_template_name_coupling():
    from src.services.local_ai import naming_protocol as product

    # Fixed public request text only; no sample answer or QA file dependency.
    text = (
        "雨水花园维护指南\n"
        "本指南介绍一座虚构社区雨水花园的日常维护。雨水花园收集屋顶和步道的雨水，"
        "通过植物和土壤过滤径流。维护人员清理入水口的落叶与垃圾，检查排水沟是否堵塞，"
        "观察积水能否消退，移除杂草并补充覆盖物。干旱时适量浇水，避免过度施肥。"
        "记录植物健康状况和清理工作。本文不涉及真实地点、人员或日期。\n"
    )
    prompt = product.build_template_prompt(Template(name="Unrelated reusable title template", pattern="{dcTitle}"),
        "zh-HK", text, has_text=True, has_visuals=False, text_layout="contiguous")
    assert _digest(prompt) == "b3b1be971f4e6447a0e1997877ebc80b3152516ece39fbb873e7003bcc381fee"
