"""Attestation holds real managed-store pins without launching inference."""

import hashlib
import io
import json
import os
import socket
import subprocess
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import replace

import pytest

from src.services.local_ai.resource_catalog import catalog_from_manifest
from src.services.local_ai.resource_store import ResourceStore, StoreBusy
from src.services.local_ai.resource_transport import ResourceCancelled, ResourceError


@pytest.fixture(autouse=True)
def forbid_network_and_process(monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(True)
        raise AssertionError("network or process API used by offline attestation")
    for owner, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                        (urllib.request, "urlopen"), (subprocess, "Popen"),
                        (os, "system"), (os, "startfile")):
        monkeypatch.setattr(owner, name, denied)
    yield
    assert not calls


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(tmp_path):
    archive = io.BytesIO()
    contents = {"llama-completion.exe": b"completion", "llama-mtmd-cli.exe": b"mtmd",
                "LICENSE.txt": b"license"}
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in contents.items():
            output.writestr(name, data)
    payloads = {"runtime-cpu": archive.getvalue(), "model-q4": b"small-model",
                "vision-f16": b"small-vision"}
    names = {"runtime-cpu": "runtime.zip", "model-q4": "model.gguf",
             "vision-f16": "vision.gguf"}
    revision = "a" * 40
    resources = []
    for identifier, data in payloads.items():
        name = names[identifier]
        url = (f"https://github.com/ggml-org/llama.cpp/releases/download/b123/{name}"
               if identifier == "runtime-cpu" else
               f"https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{revision}/{name}")
        resources.append({"id": identifier, "filename": name, "url": url,
                          "bytes": len(data), "sha256": digest(data)})
    manifest = {"schema_version": 1, "model_id": "Qwen/Qwen3.5-4B",
                "source_revision": "b" * 40,
                "quantization_repository": "unsloth/Qwen3.5-4B-GGUF",
                "quantization_revision": revision, "runtime_release": "b123",
                "model_license": "Apache-2.0", "runtime_license": "MIT",
                "purpose": "synthetic test", "resources": resources}
    catalog = catalog_from_manifest(manifest)
    resource = tmp_path / "resource"
    runtime = tmp_path / "runtime"
    with ResourceStore(resource, catalog.identity).lease(create=True) as store:
        for item in catalog.resources:
            with store.open_file(item.filename, "wb") as stream:
                stream.write(payloads[item.id])
    return resource, runtime, catalog, contents


def attest(resource, runtime, catalog, **kwargs):
    from src.services.local_ai.inference_resources import attest_resources
    return attest_resources(resource, runtime, catalog,
                            deadline=time.monotonic() + 20, **kwargs)


@pytest.mark.parametrize("vision", [False, True])
def test_attests_selected_members_with_deterministic_identity_and_held_leases(tmp_path, vision):
    resource, runtime, catalog, contents = fixture(tmp_path)
    with attest(resource, runtime, catalog, include_vision=vision) as result:
        assert result.catalog_id == catalog.identity
        assert result.runtime_release == catalog.runtime_release
        assert result.model_name == "model.gguf"
        assert result.projector_name == ("vision.gguf" if vision else None)
        assert [member.name for member in result.members] == [
            "LICENSE.txt", "llama-completion.exe", "llama-mtmd-cli.exe", "model.gguf"
        ] + (["vision.gguf"] if vision else [])
        assert [member.executable for member in result.members] == [False, True, True, False] + ([False] if vision else [])
        assert str(resource) not in repr(result) and str(runtime) not in repr(result)
        expected = {"schema": 1, "catalog_id": catalog.identity,
                    "runtime_release": catalog.runtime_release, "vision": vision,
                    "members": [{"name": member.name, "size": member.size,
                                 "sha256": member.sha256, "executable": member.executable}
                                for member in result.members]}
        assert result.identity == digest(json.dumps(expected, sort_keys=True,
                                                      separators=(",", ":")).encode())
        for root, identity in ((resource, catalog.identity),
                               (runtime, catalog.identity + ":runtime:" + catalog.runtime_release)):
            with pytest.raises(StoreBusy):
                with ResourceStore(root, identity).lease():
                    pass
        with pytest.raises(OSError):
            with result.members[0].source.open("r+b"):
                pass
    with ResourceStore(resource, catalog.identity).lease() as source:
        assert source is not None
    with ResourceStore(runtime, catalog.identity + ":runtime:" + catalog.runtime_release).lease() as target:
        assert target is not None


def test_rejects_invalid_catalog_and_inputs_before_side_effects(tmp_path):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai.inference_resources import attest_resources
    for invalid in (replace(catalog, identity="0" * 64), replace(catalog, purpose="changed")):
        with pytest.raises(ResourceError) as error:
            with attest(resource, runtime, invalid, include_vision=False):
                pass
        assert error.value.code == "INVALID_INFERENCE_RESOURCES"
    for vision, deadline in ((1, time.monotonic() + 10), (False, True),
                             (False, 10**1000), (False, float("inf")),
                             (False, time.monotonic() - 1)):
        with pytest.raises(ResourceError):
            with attest_resources(resource, runtime, catalog, include_vision=vision,
                                  deadline=deadline):
                pass
    assert not runtime.exists()


def test_detects_changed_model_after_inventory_and_releases_both_leases(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    def changed(*args, **kwargs):
        inventory = prepare_runtime_inventory(*args, **kwargs)
        (resource / "model.gguf").write_bytes(b"tampered")
        return inventory
    monkeypatch.setattr(module, "prepare_runtime_inventory", changed)
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False):
            pass
    assert error.value.code == "RESOURCE_VERIFICATION_FAILED"
    for root, identity in ((resource, catalog.identity),
                           (runtime, catalog.identity + ":runtime:" + catalog.runtime_release)):
        with ResourceStore(root, identity).lease() as store:
            assert store is not None


def test_consumer_base_exception_unwinds_all_leases(tmp_path):
    resource, runtime, catalog, _ = fixture(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        with attest(resource, runtime, catalog, include_vision=True):
            raise KeyboardInterrupt()
    for root, identity in ((resource, catalog.identity),
                           (runtime, catalog.identity + ":runtime:" + catalog.runtime_release)):
        with ResourceStore(root, identity).lease() as store:
            assert store is not None


@pytest.mark.parametrize("field,value", [("catalog_id", "wrong"),
                                          ("runtime_release", "b999"),
                                          ("root", "wrong")])
def test_rejects_mismatched_inventory(tmp_path, monkeypatch, field, value):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    if field == "root":
        value = tmp_path / value
    monkeypatch.setattr(module, "prepare_runtime_inventory",
                        lambda *args, **kwargs: replace(inventory, **{field: value}))
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False):
            pass
    assert error.value.code == "INVALID_RUNTIME_INVENTORY"


def test_missing_source_store_after_inventory_is_not_adopted(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    monkeypatch.setattr(module, "prepare_runtime_inventory", lambda *args, **kwargs: inventory)
    missing = tmp_path / "missing"
    with pytest.raises(ResourceError) as error:
        with attest(missing, runtime, catalog, include_vision=False):
            pass
    assert error.value.code == "RESOURCE_MISSING"
    assert not missing.exists()


def test_busy_second_lease_remains_distinct(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    monkeypatch.setattr(module, "prepare_runtime_inventory", lambda *args, **kwargs: inventory)
    with ResourceStore(runtime, catalog.identity + ":runtime:" + catalog.runtime_release).lease():
        with pytest.raises(StoreBusy):
            with attest(resource, runtime, catalog, include_vision=False):
                pass
    with ResourceStore(resource, catalog.identity).lease() as source:
        assert source is not None


def test_corrupt_runtime_after_inventory_fails_pinned_hash(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    def changed(*args, **kwargs):
        inventory = prepare_runtime_inventory(*args, **kwargs)
        (runtime / "LICENSE.txt").write_bytes(b"corrupt")
        return inventory
    monkeypatch.setattr(module, "prepare_runtime_inventory", changed)
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False):
            pass
    assert error.value.code == "RESOURCE_VERIFICATION_FAILED"


def test_cancel_during_pinned_hash_unwinds_leases(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    original = ResourceStore.open_file
    state = {"cancel": False}
    class Watched:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, size=-1):
            data = self.stream.read(size)
            state["cancel"] = True
            return data
    def open_file(self, name, mode="rb"):
        stream = original(self, name, mode)
        return Watched(stream) if name == "model.gguf" and mode == "rb" else stream
    monkeypatch.setattr(ResourceStore, "open_file", open_file)
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False,
                    cancelled=lambda: state["cancel"]):
            pass
    assert error.value.code == "CANCELLED"
    with ResourceStore(runtime, catalog.identity + ":runtime:" + catalog.runtime_release).lease() as store:
        assert store is not None


@pytest.mark.parametrize("callback_error", [ValueError("private callback detail"),
                                            ResourceError("private callback detail", code="RESOURCE_TIMEOUT")])
def test_cancel_callback_exception_is_fixed_cancelled_even_during_inventory(tmp_path, callback_error):
    resource, runtime, catalog, _ = fixture(tmp_path)
    def broken():
        raise callback_error
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False, cancelled=broken):
            pass
    assert error.value.code == "CANCELLED"
    assert "private callback detail" not in str(error.value)
    assert not runtime.exists()


def test_exhausted_deadline_after_inventory_is_timeout(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    clock = [time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    def delayed(*args, **kwargs):
        clock[0] += 11
        return inventory
    monkeypatch.setattr(module, "prepare_runtime_inventory", delayed)
    from src.services.local_ai.inference_resources import attest_resources
    with pytest.raises(ResourceError) as error:
        with attest_resources(resource, runtime, catalog, include_vision=False,
                              deadline=clock[0] + 10):
            pass
    assert error.value.code == "RESOURCE_TIMEOUT"
    assert not isinstance(error.value, ResourceCancelled)


def test_exhausted_deadline_during_pinned_hash_is_timeout(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    clock = [time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "prepare_runtime_inventory", lambda *args, **kwargs: inventory)
    original_open = ResourceStore.open_file
    class ExpiringStream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, size=-1):
            data = self.stream.read(size)
            clock[0] += 11
            return data
    def open_file(self, name, mode="rb"):
        stream = original_open(self, name, mode)
        return ExpiringStream(stream) if name == "LICENSE.txt" and mode == "rb" else stream
    monkeypatch.setattr(ResourceStore, "open_file", open_file)
    from src.services.local_ai.inference_resources import attest_resources
    with pytest.raises(ResourceError) as error:
        with attest_resources(resource, runtime, catalog, include_vision=False,
                              deadline=clock[0] + 10):
            pass
    assert error.value.code == "RESOURCE_TIMEOUT"
    assert not isinstance(error.value, ResourceCancelled)


def test_exhausted_deadline_at_final_pre_yield_check_is_timeout(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    clock = [time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "prepare_runtime_inventory", lambda *args, **kwargs: inventory)
    original_assert_safe = ResourceStore.assert_safe
    checks = [0]
    def assert_safe(self):
        original_assert_safe(self)
        if self.root == resource:
            checks[0] += 1
            if checks[0] == 2:
                clock[0] += 11
    monkeypatch.setattr(ResourceStore, "assert_safe", assert_safe)
    from src.services.local_ai.inference_resources import attest_resources
    yielded = False
    with pytest.raises(ResourceError) as error:
        with attest_resources(resource, runtime, catalog, include_vision=False,
                              deadline=clock[0] + 10):
            yielded = True
    assert checks[0] == 2
    assert not yielded
    assert error.value.code == "RESOURCE_TIMEOUT"
    assert not isinstance(error.value, ResourceCancelled)


def test_consumer_resource_error_is_not_rewritten(tmp_path):
    resource, runtime, catalog, _ = fixture(tmp_path)
    consumer = ResourceError("CONSUMER_FAILURE", code="CONSUMER_FAILURE")
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False):
            raise consumer
    assert error.value is consumer


def test_rejects_catalog_resource_alias_inconsistent_with_rebuilt_manifest(tmp_path):
    resource, runtime, catalog, _ = fixture(tmp_path)
    class Alias:
        def __init__(self, spec):
            self.spec = spec
            self.id = "other"
        def as_transport_dict(self):
            return self.spec.as_transport_dict()
    bad = replace(catalog, resources=(Alias(catalog.resources[0]), *catalog.resources[1:]))
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, bad, include_vision=False):
            pass
    assert error.value.code == "INVALID_INFERENCE_RESOURCES"
    assert not runtime.exists()


@pytest.mark.parametrize("change", [
    {"name": "CON"}, {"name": "model.gguf"}, {"size": 0},
    {"sha256": "G" * 64}, {"executable": True},
])
def test_rejects_invalid_runtime_member_metadata(tmp_path, monkeypatch, change):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    inventory = prepare_runtime_inventory(resource, runtime, catalog)
    member = inventory.members[0]
    if "name" in change:
        change["path"] = runtime / change["name"]
    bad = replace(inventory, members=(replace(member, **change), *inventory.members[1:]))
    monkeypatch.setattr(module, "prepare_runtime_inventory", lambda *args, **kwargs: bad)
    with pytest.raises(ResourceError) as error:
        with attest(resource, runtime, catalog, include_vision=False):
            pass
    assert error.value.code == "INVALID_RUNTIME_INVENTORY"


def test_original_deadline_stops_inventory_before_lease_after_clock_advance(tmp_path, monkeypatch):
    resource, runtime, catalog, _ = fixture(tmp_path)
    from src.services.local_ai import inference_resources as module
    from src.services.local_ai.runtime_inventory import prepare_runtime_inventory
    from src.services.local_ai.inference_resources import attest_resources
    clock = [time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    leases = []
    original_lease = ResourceStore.lease
    @contextmanager
    def watched_lease(self, *args, **kwargs):
        leases.append(self.root)
        with original_lease(self, *args, **kwargs) as store:
            yield store
    monkeypatch.setattr(ResourceStore, "lease", watched_lease)
    def delayed(*args, **kwargs):
        clock[0] += 11
        return prepare_runtime_inventory(*args, **kwargs)
    monkeypatch.setattr(module, "prepare_runtime_inventory", delayed)
    with pytest.raises(ResourceError) as error:
        with attest_resources(resource, runtime, catalog, include_vision=False,
                              deadline=clock[0] + 10):
            pass
    assert error.value.code == "RESOURCE_TIMEOUT"
    assert leases == []
