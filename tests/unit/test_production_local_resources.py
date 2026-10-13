"""Production metadata and native parent capability; tiny fixtures only."""
import importlib
import json
import hashlib
import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from src.services.local_ai.resource_transport import ResourceError


def product():
    name = "src.services.local_ai.production_resources"
    assert importlib.util.find_spec(name) is not None, "product loader is not implemented"
    return importlib.import_module(name)


def test_loader_is_inert_and_pinned(tmp_path, monkeypatch):
    from src.services.local_ai.resource_manager import ResourceManager
    module = product()
    def forbidden(*args, **kwargs):
        pytest.fail("constructor side effect")
    monkeypatch.setattr(ResourceManager, "download", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    config = module.load_production_resources(user_data_root=tmp_path / "absent")
    assert config.catalog.identity == module.PRODUCT_CATALOG_ID
    assert config.catalog.purpose == "managed-local-resources-v1"
    assert config.catalog.total_bytes == 3431786583
    assert config.resource_root.name == config.runtime_root.name == config.catalog.identity
    assert not config.state_root.exists()


def test_loader_independent_of_cwd_and_default_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = product().load_production_resources()
    assert config.state_root == tmp_path / "Xuxia" / "local-ai" / "state"
    assert config.bundled_runtime.name == "llama-b10885-bin-win-cpu-x64.zip"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("root", ["relative", "D:relative", "\\\\server\\share", "D:\\bad.\\child"])
def test_loader_rejects_nonlocal_or_ambiguous_root(root):
    with pytest.raises(ResourceError):
        product().load_production_resources(user_data_root=Path(root))


def test_missing_localappdata_rejected(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(ResourceError):
        product().load_production_resources()


@pytest.mark.parametrize("change", ["purpose", "runtime_release", "sha256"])
def test_substituted_catalog_rejected_before_creation(tmp_path, change):
    module = product()
    original = Path(__file__).parents[2] / "resources/local-models/qwen35-4b-feasibility.json"
    data = json.loads(original.read_text(encoding="utf-8"))
    data["purpose"] = "managed-local-resources-v1"
    if change == "sha256":
        data["resources"][0]["sha256"] = "a" * 64
    else:
        data[change] = "engineering-feasibility-only-not-product-ready" if change == "purpose" else "b1"
    target = tmp_path / "resources/local-models/qwen35-4b-managed-v1.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ResourceError, match="INVALID_PRODUCT_CATALOG"):
        module.load_production_resources(bundle_root=tmp_path, user_data_root=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("readiness", [False, True])
def test_parent_context_creates_only_role_parents(tmp_path, readiness):
    module = product()
    config = module.load_production_resources(user_data_root=tmp_path / "Xuxia/local-ai")
    with module.prepare_production_parents(config, trusted_anchor=tmp_path, for_readiness=readiness) as owned:
        owned.assert_safe()
        assert config.resource_root.parent.is_dir()
        assert config.runtime_root.parent.exists() is readiness
        assert not any(path.exists() for path in (config.resource_root, config.runtime_root, config.state_root))
        with pytest.raises(OSError):
            (tmp_path / "Xuxia").rename(tmp_path / "substituted")
    assert not list(tmp_path.rglob("*.tmp"))
    (tmp_path / "Xuxia").rename(tmp_path / "released")


def test_wrong_config_and_outside_anchor_have_zero_effect(tmp_path):
    module = product()
    config = module.load_production_resources(user_data_root=tmp_path / "base")
    wrong = replace(config, state_root=tmp_path / "other/state")
    for candidate, anchor in ((wrong, tmp_path), (config, tmp_path / "missing")):
        with pytest.raises(ResourceError):
            with module.prepare_production_parents(candidate, trusted_anchor=anchor):
                pytest.fail("invalid capability accepted")
    assert list(tmp_path.iterdir()) == []


def test_forged_catalog_identity_is_not_parent_authority(tmp_path):
    module = product()
    config = module.load_production_resources(user_data_root=tmp_path / "base")
    changed = replace(config.catalog.resources[0], sha256="a" * 64)
    forged = replace(config, catalog=replace(config.catalog, resources=(changed, *config.catalog.resources[1:])))
    with pytest.raises(ResourceError):
        with module.prepare_production_parents(forged, trusted_anchor=tmp_path):
            pass
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("outcome", ["ready", "error", "cancel"])
def test_worker_readiness_lifetime_and_retained_journal(tmp_path, outcome):
    from contextlib import ExitStack
    from src.services.local_ai.inference_journal import LocalInferenceJournal
    from src.services.local_ai.resource_store import ResourceStore, StoreBusy, MARKER
    from src.services.local_ai.resource_transport import ResourceCancelled
    module = product()
    config = module.load_production_resources(user_data_root=tmp_path / "base")
    journal = LocalInferenceJournal(config.state_root)
    with ExitStack() as service:
        class FakeService:
            def check_ready(self):
                parents.assert_safe()
                assert not parents.idle
                service.enter_context(journal.lease())
                assert {p.name for p in config.state_root.iterdir()} == {MARKER, "inference-run.json"}
                with pytest.raises(OSError):
                    config.state_root.parent.rename(tmp_path / "moved")
                if outcome == "error":
                    raise ValueError("synthetic self-check failed")
                if outcome == "cancel":
                    raise ResourceCancelled("CANCELLED")
                return "READY"
        try:
            with module.prepare_production_parents(config, trusted_anchor=tmp_path, for_readiness=True) as parents:
                assert FakeService().check_ready() == "READY"
        except (ValueError, ResourceCancelled):
            assert outcome != "ready"
        assert parents.idle and not parents.retained
        with pytest.raises(StoreBusy):
            with ResourceStore(config.state_root, "xuxia-local-inference-journal-v1").lease():
                pass
        assert journal.record.phase == "clean"
    assert journal.inspect_recovery_state().value == "clean"


def test_legacy_runtime_requires_parent_wrapped_tiny_archive_proceeds(tmp_path):
    from src.services.local_ai.resource_store import ResourceStore, MARKER
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    module = product()
    config = module.load_production_resources(user_data_root=tmp_path / "base")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("llama-completion.exe", b"synthetic-not-executable")
        zipped.writestr("llama-mtmd-cli.exe", b"synthetic-not-executable")
        zipped.writestr("LICENSE.txt", b"fixture")
    body = archive.getvalue()
    runtime = replace(config.catalog.resources[0], bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    tiny = replace(config.catalog, resources=(runtime, *config.catalog.resources[1:]))
    with pytest.raises(ResourceError, match="INVALID_RUNTIME_ROOT"):
        prepare_runtime_inventory(config.resource_root, config.runtime_root, tiny)
    assert not config.state_root.parent.exists()
    with module.prepare_production_parents(config, trusted_anchor=tmp_path, for_readiness=True):
        with ResourceStore(config.resource_root, tiny.identity).lease(create=True) as store:
            with store.open_file(runtime.filename, "wb") as stream:
                stream.write(body)
        result = prepare_runtime_inventory(config.resource_root, config.runtime_root, tiny)
        assert (result.root / "llama-completion.exe").read_bytes() == b"synthetic-not-executable"
        marker = json.loads((result.root / MARKER).read_text())
        assert marker["catalog_id"] == tiny.identity + ":runtime:" + tiny.runtime_release
        assert not config.state_root.exists()
    assert not list(tmp_path.rglob("*.tmp"))
