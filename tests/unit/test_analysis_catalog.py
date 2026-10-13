"""Pure immutable input publication; synthetic metadata only."""
from dataclasses import FrozenInstanceError, replace
import importlib
from threading import Event, Thread

import pytest

from src.core.template_model import Template, TemplateField
from src.models.app_config import AppConfig


def catalog_api():
    spec = importlib.util.find_spec("src.core.analysis_catalog")
    assert spec is not None, "immutable catalog missing"
    return importlib.import_module("src.core.analysis_catalog")


def selected():
    return Template(id="one", name="Synthetic", pattern="{dcTitle}",
                    fields=(TemplateField("dcTitle", "Title"),))


def test_builder_whitelists_and_defensively_snapshots_actual_templates():
    api = catalog_api()
    class Trap:
        def __deepcopy__(self, memo):
            pytest.fail("extra object copied")
    config = AppConfig(api_key="secret-marker", arbitrary=Trap(), default_template_id="one",
        active_provider_id="active", provider_profiles=[dict(id="active", model="synthetic",
        base_url="https://example.invalid", needs_connection_verification=False,
        api_key="secret-marker", extra=Trap(), capabilities=dict(text=True, extra=Trap()))])
    template = selected()
    templates = [template]
    result = api.build_analysis_catalog(config, templates)
    config.max_content_chars = 42
    config.provider_profiles[0]["model"] = "changed"
    templates.clear()
    assert result.settings.max_content_chars == 4000
    assert result.active_profile.model == "synthetic"
    assert result.template("one") == template and result.template("one") is not template
    assert result.template("") is result.templates[0]
    assert type(result.templates) is tuple
    assert "secret-marker" not in repr(result)
    assert not hasattr(result, "config") and not hasattr(result.active_profile, "extra")
    with pytest.raises(FrozenInstanceError):
        result.default_template_id = "other"


@pytest.mark.parametrize("profile", [dict(enabled=False), dict(needs_connection_verification=True)])
def test_disabled_or_unverified_profile_is_not_usable(profile):
    api = catalog_api()
    raw = dict(id="active", model="synthetic", needs_connection_verification=False)
    raw.update(profile)
    result = api.build_analysis_catalog(AppConfig(active_provider_id="active", provider_profiles=[raw]), [selected()])
    assert result.active_profile is None


def test_catalog_rejects_invalid_duplicate_and_unknown_templates():
    api = catalog_api()
    for templates in ([selected(), selected()], [object()]):
        with pytest.raises(ValueError, match="^Invalid analysis catalog$"):
            api.build_analysis_catalog(AppConfig(), templates)
    result = api.build_analysis_catalog(AppConfig(), [selected()])
    with pytest.raises(ValueError, match="^Unknown analysis template$"):
        result.template("secret-marker")


def test_source_reentrant_guard_publishes_whole_reference_and_blocks_readers():
    api = catalog_api()
    old = api.build_analysis_catalog(AppConfig(), [selected()])
    new = api.build_analysis_catalog(AppConfig(max_content_chars=42), [replace(selected(), name="New")])
    source = api.AnalysisCatalogSource(old)
    entered, finished = Event(), Event()
    values = []
    def read():
        entered.set()
        values.append(source.get())
        finished.set()
    with source.guard():
        assert source.get() is old
        thread = Thread(target=read)
        thread.start()
        assert entered.wait(2) and not finished.wait(.05)
        source.install(new)
        assert source.get() is new
    thread.join(2)
    assert finished.is_set() and values == [new]
