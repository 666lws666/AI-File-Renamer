"""Deterministic policy guards; these fixtures are not real-model quality evidence."""
import importlib

import pytest


def policy(locale="zh-CN", version="smart-v1"):
    # Keep RED an explicit missing-feature assertion rather than a collection error.
    assert importlib.util.find_spec("src.core.smart_naming"), "smart policy is not implemented"
    return importlib.import_module("src.core.smart_naming").SmartNamingPolicy(locale, version)


def part(role, value, evidence=None, evidence_source="text"):
    return {"role": role, "value": value, "evidence": evidence or value,
            "evidence_source": evidence_source}


def fields(*parts, locale="zh-CN", understood=True):
    return {"understood": understood, "language": locale, "parts": list(parts)}


def render(data, text=None, locale="zh-CN", visuals=False, extension=".pdf"):
    if text is None:
        text = " ".join(p["evidence"] for p in data["parts"])
    return policy(locale).render(data, extracted_text=text, has_visuals=visuals, extension=extension)


@pytest.mark.parametrize("parts,expected", [
    ([part("topic", "服务器采购发票"), part("entity", "明远科技"), part("date", "2026-05")], "2026-05_明远科技_服务器采购发票.pdf"),
    ([part("topic", "校园网络维护合同"), part("entity", "海滨大学")], "海滨大学_校园网络维护合同.pdf"),
    ([part("version", "v2"), part("topic", "北岸项目进度报告"), part("context", "验收阶段")], "北岸项目进度报告_验收阶段_v2.pdf"),
    ([part("topic", "生成式人工智能讲座")], "生成式人工智能讲座.pdf"),
])
def test_mixed_document_names_have_fixed_order_but_no_fixed_fields(parts, expected):
    assert render(fields(*parts)) == expected


@pytest.mark.parametrize("locale,topic", [("zh-CN", "校园网络维护合同"), ("zh-HK", "校園網絡維護合同"), ("en-US", "Campus network maintenance contract")])
def test_supported_locale_and_proper_name_preservation(locale, topic):
    assert render(fields(part("entity", "OpenAI"), part("topic", topic), locale=locale), locale=locale) == f"OpenAI_{topic}.pdf"


@pytest.mark.parametrize("date", ["2026", "2026-05", "2026-05-03", "2025~2026", "2026-01~2026-05", "2026-05-01~2026-05-03"])
def test_date_precision_and_ordered_ranges(date):
    assert render(fields(part("topic", "校园网络维护合同"), part("date", date))).startswith(date + "_")


@pytest.mark.parametrize("date", ["20260503", "2026-5", "2026-02-30", "2026-13", "0000", "2026~2025", "2026~2026-05", "2026/05/03"])
def test_bad_dates_fail(date):
    with pytest.raises(ValueError, match=r"^smart.error.(invalidResponse|unsafeName)$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", date)))


@pytest.mark.parametrize("topic", ["报告", "合同", "学习资料", "研究报告", "Report", "Study materials", "文件", "Document"])
def test_generic_topics_rejected_even_with_entity(topic):
    with pytest.raises(ValueError, match="^smart.error.genericName$"):
        render(fields(part("entity", "OpenAI"), part("topic", topic)), locale="zh-CN")


@pytest.mark.parametrize("value", ["../private", "C:\\private", "report.pdf", "a/b", "a:b", "CON", "NUL.txt", "LPT1", "a\nline", "a\x00b", "a\u202eb", "trailing.", "_contract", "a_b", "a?"])
def test_unsafe_parts_fail_without_exposing_source(value):
    with pytest.raises(ValueError, match="^smart.error.unsafeName$"):
        render(fields(part("entity", value), part("topic", "校园网络维护合同")))


def test_fake_evidence_rejected():
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "校园网络维护合同", "不存在的证据")), text="校园网络维护合同")


def test_whitespace_normalization_of_literal_evidence():
    assert render(fields(part("topic", "校园网络维护合同", "校园 网络 维护合同")), text="校园\n网络\t维护合同") == "校园网络维护合同.pdf"


@pytest.mark.parametrize("data,text", [(fields(part("topic", "校园网络维护合同")), ""), (fields(part("topic", "校园网络维护合同"), understood=False), "校园网络维护合同")])
def test_no_actual_content_or_understanding_fails(data, text):
    with pytest.raises(ValueError, match="^smart.error.insufficientContent$"):
        render(data, text=text)


def test_visual_observation_allowed_but_not_claimed_verified():
    assert render(fields(part("topic", "红色自行车停靠路边", "图像中有一辆红色自行车", "visual")), text="", visuals=True) == "红色自行车停靠路边.pdf"


def test_visual_evidence_coexists_with_text_without_literal_matching():
    assert render(fields(part("topic", "红色自行车停靠路边", "图像中有一辆红色自行车", "visual")),
                  text="A caption unrelated to the bicycle", visuals=True) == "红色自行车停靠路边.pdf"


def test_visual_evidence_requires_prepared_visuals_even_if_quote_matches_text():
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "红色自行车停靠路边", evidence_source="visual")))


def test_text_evidence_still_requires_literal_quote_with_visuals():
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "红色自行车停靠路边")), text="无关正文", visuals=True)


@pytest.mark.parametrize("source", [None, "metadata", "filename"])
def test_evidence_source_is_required_and_restricted(source):
    data = fields(part("topic", "校园网络维护合同"))
    if source is None:
        data["parts"][0].pop("evidence_source")
    else:
        data["parts"][0]["evidence_source"] = source
    with pytest.raises(ValueError, match="^smart.error.invalidResponse$"):
        render(data)


def test_too_long_utf16_stem_is_not_truncated():
    with pytest.raises(ValueError, match="^smart.error.tooLong$"):
        render(fields(part("topic", "校园网络" + "𠮷" * 90)))


@pytest.mark.parametrize("data", [fields(), fields(part("entity", "OpenAI")), fields(part("topic", "校园网络维护合同"), part("topic", "服务器采购发票")), {"understood": True, "language": "zh-CN", "parts": [], "filename": "x.pdf"}])
def test_missing_topic_duplicate_roles_and_extra_keys_fail(data):
    with pytest.raises(ValueError, match="^smart.error.invalidResponse$"):
        render(data, text="校园网络维护合同 OpenAI 服务器采购发票")


@pytest.mark.parametrize("locale,echo,topic", [("zh-CN", "en-US", "Campus network contract"), ("zh-CN", "zh-CN", "校園網絡維護報告"), ("zh-HK", "zh-HK", "校园网络维护报告"), ("en-US", "en-US", "校园网络维护报告")])
def test_locale_echo_and_obvious_topic_script_mismatch(locale, echo, topic):
    with pytest.raises(ValueError, match="^smart.error.languageMismatch$"):
        render(fields(part("topic", topic), locale=echo), locale=locale)


def test_unknown_policy_rejected():
    with pytest.raises(ValueError, match="^smart.error.unsupportedPolicy$"):
        policy(version="smart-v999")


def test_date_cannot_invent_day_from_month_evidence():
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", "2026-05-01", "2026年5月")))


@pytest.mark.parametrize("evidence_source", ["text", "visual"])
def test_year_only_rejected_from_observed_month(evidence_source):
    quote = "第一頁文件顯示'維護時間：2026年8月'"
    data = fields(part("topic", "校園網絡維護合同", "校園網絡維護合同"),
                  part("date", "2026", quote, evidence_source), locale="zh-HK")
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(data, text=quote + " 校園網絡維護合同", locale="zh-HK",
               visuals=evidence_source == "visual")


@pytest.mark.parametrize("value,evidence", [
    ("2026", "2026-08"),
    ("2026", "2026/08/03"),
    ("2026", "2026.8.3"),
    ("2026", "２０２６ 年 ８ 月"),
    ("2026-08", "2026-08-03"),
    ("2026-08", "2026/8/3"),
    ("2026-08", "2026 年 8 月 3 日"),
    ("2026-08", "２０２６年８月３日"),
    ("2026~2027", "2026年8月 至 2027年"),
    ("2026-08~2026-09", "2026年8月 至 2026年9月3日"),
])
def test_date_value_cannot_use_more_precise_atom_prefix(value, evidence):
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", value, evidence)))


@pytest.mark.parametrize("value,evidence", [
    ("2026", "2026年；维护时间：2026年8月"),
    ("2026-08", "2026年8月；维护日期：2026年8月3日"),
    ("2026", "2026-08-03；另有 2026 年"),
    ("2026-08", "2026-08；另有 2026-09-03"),
])
def test_exact_date_atom_remains_usable_beside_more_precise_dates(value, evidence):
    assert render(fields(part("topic", "校园网络维护合同"), part("date", value, evidence))) == value + "_校园网络维护合同.pdf"


@pytest.mark.parametrize("value,evidence", [
    ("2026-08", "时间：2026 年 8 月"),
    ("2026-08", "时间：2026年 8 月"),
    ("2026-08", "时间：2026\t年\n8\t月"),
    ("2026-08", "时间：２０２６\u3000年\u3000８\u3000月"),
    ("2026-08-03", "时间：2026 年 8 月 3 日"),
    ("2026-08-03", "时间：２０２６\u3000年\u3000８\u3000月\u3000３\u3000日"),
    ("2026-08~2026-09", "时间：2026 年 8 月至2026 年 9 月"),
    ("2026-08-03~2026-08-05", "时间：2026 年 8 月 3 日至2026 年 8 月 5 日"),
])
def test_literal_chinese_date_spacing_preserves_precision(value, evidence):
    topic = "校园网络维护合同"
    source = evidence + "\n" + topic
    assert render(fields(part("topic", topic), part("date", value, evidence)), text=source) == value + "_" + topic + ".pdf"


@pytest.mark.parametrize("value,evidence", [
    ("2026-08-01", "时间：2026 年 8 月"),
    ("2026-08", "时间：2026 年"),
    ("2026-08", "时间：2025 年 8 月"),
    ("2026-08", "时间：2026 年 9 月"),
    ("2026-08", "2026 年完成检查；8 月另作安排"),
    ("2026-08-03", "2026 年 8 月开展检查；3 个缺陷"),
    ("2026-08~2026-09", "时间：2026 年 8 月"),
])
def test_chinese_date_spacing_cannot_join_prose_or_invent_precision(value, evidence):
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", value, evidence)))


def test_spaced_date_evidence_still_must_occur_in_source():
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", "2026-08", "2026 年 8 月")),
               text="2025 年 8 月 校园网络维护合同")


@pytest.mark.parametrize("value", ["2026-02-30", "2026-13", "2026-09~2026-08", "2026~2026-08"])
def test_spaced_evidence_does_not_bypass_date_or_range_validation(value):
    with pytest.raises(ValueError, match="^smart.error.invalidResponse$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", value, "2026 年 2 月 30 日至2026 年 13 月")))


def test_schema_supported_by_current_adapter_and_carries_policy_instructions():
    from src.providers.openai_compatible import _validate_schema_definition, _validate_schema_value
    schema = policy().response_schema()
    _validate_schema_definition(schema)
    _validate_schema_value(fields(part("topic", "校园网络维护合同")), schema)
    assert schema["additionalProperties"] is False
    for instruction in ("smart-v1", "untrusted", "evidence", "omit", "zh-CN"):
        assert instruction in schema["description"]


def test_date_grammar_rejects_fullwidth_digits():
    with pytest.raises(ValueError, match="^smart.error.invalidResponse$"):
        render(fields(part("topic", "校园网络维护合同"), part("date", "２０２６-０５")))


def test_common_chinese_characters_do_not_imply_traditional_script():
    assert render(fields(part("topic", "人工智能研究材料"))) == "人工智能研究材料.pdf"


def test_context_order_and_version_decimal_are_preserved():
    assert render(fields(part("context", "采购阶段"), part("topic", "校园网络维护合同"), part("version", "v2.1"), part("context", "评审记录"))) == "校园网络维护合同_采购阶段_评审记录_v2.1.pdf"


@pytest.mark.parametrize("extension", [".txt.exe/evil", "../txt", ".a:b", "txt"])
def test_locally_supplied_extension_is_validated(extension):
    with pytest.raises(ValueError, match="^smart.error.unsafeName$"):
        render(fields(part("topic", "校园网络维护合同")), extension=extension)


ENGLISH_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def test_actual_scan_english_month_observation_preserves_month_precision():
    data = fields(part("topic", "咖啡機維護清單", "圖像顯示咖啡機維護清單", "visual"),
                  part("date", "2026-10", "圖像頂部文字顯示「October 2026」", "visual"),
                  locale="zh-HK")
    assert render(data, text="", locale="zh-HK", visuals=True) == "2026-10_咖啡機維護清單.pdf"


@pytest.mark.parametrize("month,number", [(name, index) for index, name in enumerate(ENGLISH_MONTHS, 1)])
@pytest.mark.parametrize("case", [str.lower, str.upper, lambda value: value])
def test_all_full_english_month_names_are_literal_case_insensitive_dates(month, number, case):
    value = f"2026-{number:02d}"
    data = fields(part("topic", "Coffee machine maintenance"),
                  part("date", value, f"Date: {case(month)} 2026"), locale="en-US")
    assert render(data, locale="en-US") == value + "_Coffee machine maintenance.pdf"


@pytest.mark.parametrize("value,evidence", [
    ("2026-10-13", "October 13, 2026"),
    ("2026-10-13", "October 13 2026"),
    ("2026-10-13", "13 October 2026"),
    ("2024-02-29", "29 February 2024"),
    ("2026-10-03", "October 03, 2026"),
    ("2026-10-03", "03 October 2026"),
    ("2026-10~2026-11", "October 2026 to November 2026"),
    ("2026-10-03~2026-10-13", "October 3, 2026 to 13 October 2026"),
    ("2026-10~2026-11", "October 2026 至 2026 年 11 月"),
    ("2026-10-03~2026-10-13", "3 October 2026 至 2026-10-13"),
])
def test_literal_english_days_ranges_and_mixed_formats_preserve_exact_precision(value, evidence):
    data = fields(part("topic", "Coffee machine maintenance"), part("date", value, evidence), locale="en-US")
    assert render(data, locale="en-US") == value + "_Coffee machine maintenance.pdf"


@pytest.mark.parametrize("value,evidence", [
    ("2026", "October 2026"),
    ("2026", "October 13, 2026"),
    ("2026", "13 October 2026"),
    ("2026-10", "October 13, 2026"),
    ("2026-10", "13 October 2026"),
    ("2026-10-01", "October 2026"),
    ("2026-11", "October 2026"),
    ("2026-10-12", "October 13, 2026"),
    ("2026", "February 30, 2026"),
    ("2026", "29 February 2026"),
    ("2026-02", "February 30, 2026"),
    ("2026", "October 00, 2026"),
    ("2026", "32 October 2026"),
    ("2026", "113 October 2026"),
    ("2026", "October 013, 2026"),
    ("2026", "October 13 2026"),
    ("2026-10-13", "October 13,2026"),
    ("2026-10", "SuperOctober 2026"),
    ("2026-10", "éOctober 2026"),
    ("2026-10", "October 2026é"),
    ("2026-10", "Octoberish 2026"),
    ("2026-10", "October_2026"),
    ("2026-10", "October 20260"),
    ("2026-10", "October 026"),
    ("2026-10", "Oct 2026"),
    ("2026-10", "October maintenance; budget year 2026"),
    ("2026-10", "2026 October 2027 年 10 月"),
    ("2026-10", "October 2026-11-03"),
    ("2026-10~2026-11", "October 2026"),
    ("2026-10~2026-11", "October 2026 to November 3, 2026"),
    ("2026~2027", "October 2026 to 2027年"),
])
def test_english_literal_evidence_cannot_invent_or_lose_precision_or_use_invalid_forms(value, evidence):
    data = fields(part("topic", "Coffee machine maintenance"), part("date", value, evidence), locale="en-US")
    with pytest.raises(ValueError, match="^smart.error.ungrounded$"):
        render(data, locale="en-US")


@pytest.mark.parametrize("value,evidence", [
    ("2026", "2026; October 2026"),
    ("2026-10", "October 2026; October 13, 2026"),
    ("2026-10", "October 13, 2026; 2026-10"),
    ("2026", "2026年；February 30, 2026"),
    ("2026", "SuperOctober 2026"),
    ("2026", "Octoberish 2026"),
    ("2026-11-03", "October 2026-11-03"),
    ("2026-11", "October 2026年11月"),
])
def test_independent_exact_atoms_remain_usable_beside_english_date_literals(value, evidence):
    data = fields(part("topic", "Coffee machine maintenance"), part("date", value, evidence), locale="en-US")
    assert render(data, locale="en-US") == value + "_Coffee machine maintenance.pdf"


@pytest.mark.parametrize("value", ["2026-02-30", "2026-13", "2026-11~2026-10", "2026~2026-10"])
def test_english_evidence_does_not_bypass_existing_calendar_or_range_validator(value):
    data = fields(part("topic", "Coffee machine maintenance"),
                  part("date", value, "October 2026 to November 2026"), locale="en-US")
    with pytest.raises(ValueError, match="^smart.error.invalidResponse$"):
        render(data, locale="en-US")
