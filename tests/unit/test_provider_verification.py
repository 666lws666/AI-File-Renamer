"""M3 Gate: Provider capability verification — corrected facts, v2 schema."""
import json, re
from pathlib import Path
import pytest

JSON_PATH = Path(__file__).parent.parent.parent / "docs" / "implementation" / "reports" / "M3_PROVIDER_CAPABILITY_VERIFICATION.json"

@pytest.fixture(scope="module")
def data():
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))

def test_schema_v2(data):
    assert data["schema_version"] == 2

def test_verification_date(data):
    assert data["verification_date"] == "2026-07-29"

def test_exactly_five(data):
    assert len(data["providers"]) == 5

def test_unique_ids(data):
    ids = [p["provider_id"] for p in data["providers"]]
    assert len(ids) == len(set(ids))

def _provider(data, provider_id):
    return next(p for p in data["providers"] if p["provider_id"] == provider_id)


def test_deepseek_current_capability_evidence_retires_obsolete_prices(data):
    ds = _provider(data, "deepseek")
    pricing = ds["pricing"]
    assert pricing["currency"] is None
    assert pricing["verifiable"] is False
    assert pricing["status"] == "UNKNOWN"
    assert pricing["unit"] is None
    assert pricing["official_url"] == (
        "https://api-docs.deepseek.com/quick_start/pricing/"
    )
    assert pricing["models"] == {}
    assert ds["verification_date"] == "2026-09-10"
    assert ds["model_capability_update"]["model"] == "deepseek-flash"
    assert ds["model_capability_update"]["compatibility_aliases"] == [
        "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"]
    assert ds["capabilities"]["vision"] and ds["capabilities"]["json_mode"]

def test_qwen_regional(data):
    qw = _provider(data, "qwen")
    assert qw["base_url_mode"] == "REGIONAL"
    assert qw["region_required"] is True
    assert qw["workspace_id_required_by_region"] is True
    assert "{WorkspaceId}" in qw["regional_endpoints"]["beijing"]
    assert "{WorkspaceId}" in qw["regional_endpoints"]["singapore"]
    assert "json_mode" in qw["capabilities"]
    assert "json_schema" in qw["capabilities"]
    assert qw["capabilities"]["json_mode"] is True
    # Official Qwen docs verify json_object mode, not strict json_schema output.
    assert qw["capabilities"]["json_schema"] is False
    assert qw["json_schema_status"] == "UNVERIFIED"

def test_kimi_current_base(data):
    km = _provider(data, "kimi")
    assert km["base_url"] == "https://api.moonshot.ai/v1"
    assert km["capabilities"]["json_mode"] is True
    assert km["capabilities"]["json_schema"] is True


def test_mimo_model_specific_json(data):
    mm = _provider(data, "mimo")
    assert mm["capability_scope"] == "MODEL_SPECIFIC"
    assert mm["capabilities"]["json_mode"] is True
    assert mm["capabilities"]["json_schema"] is False
    assert mm["json_mode_models"] == ["mimo-v2.5", "mimo-v2.5-pro"]


def test_unverified_prices_never_contain_numeric_estimates(data):
    for provider_id in ("qwen", "mimo", "zhipu", "kimi"):
        pricing = _provider(data, provider_id)["pricing"]
        assert pricing["verifiable"] is False
        assert pricing["status"] == "UNKNOWN"
        assert pricing["models"] == {}

def test_all_sources_https(data):
    for p in data["providers"]:
        for s in p["official_sources"]:
            assert s.startswith("https://")

def test_no_real_key(data):
    text = json.dumps(data)
    assert not re.search(r'sk-[a-zA-Z0-9]{20,}', text)
    assert not re.search(r'[a-zA-Z0-9]{40,}', text)

def test_all_prices_have_source(data):
    for p in data["providers"]:
        pr = p.get("pricing", {})
        if pr.get("verifiable"):
            assert pr.get("official_url"), f"{p['provider_id']}: priced but no URL"
            assert pr.get("currency")
            assert pr.get("unit")
            assert pr.get("verification_date")
            assert pr.get("status") == "VERIFIED"
            assert pr.get("models")
        else:
            assert pr.get("status") == "UNKNOWN"
            assert pr.get("models") == {}

def test_conclusions_match_overall(data):
    cs = [p["conclusion"] for p in data["providers"]]
    if all(c=="VERIFIED" for c in cs): assert data["overall_gate"]=="PASS"
    else: assert data["overall_gate"] in ("PARTIAL","BLOCKED")

def test_capability_fields(data):
    for p in data["providers"]:
        for f in ["text","vision","multi_image","json_mode","json_schema","streaming","tool_calling"]:
            assert f in p["capabilities"], f"{p['provider_id']}: missing {f}"
            assert isinstance(p["capabilities"][f], bool), f"{p['provider_id']}: {f} not bool"

def test_base_url_modes(data):
    valid = {"FIXED", "REGIONAL", "WORKSPACE", "USER_CONFIGURED"}
    for p in data["providers"]:
        assert p.get("base_url_mode") in valid, f"{p['provider_id']}: invalid base_url_mode"
