"""Bounded, offline contract tests for the managed resource catalog."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.services.local_ai.resource_catalog import catalog_from_manifest, load_resource_catalog
from src.services.local_ai.resource_transport import ResourceError


ROOT = Path(__file__).resolve().parents[2]
REV = "a" * 40
SOURCE_REV = "b" * 40


@pytest.fixture
def valid_manifest():
    entries = [
        ("runtime-cpu", "runtime-b123.zip", "https://github.com/ggml-org/llama.cpp/releases/download/b123/runtime-b123.zip"),
        ("model-q4", "model.gguf", f"https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{REV}/model.gguf"),
        ("vision-f16", "vision.gguf", f"https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/{REV}/vision.gguf"),
    ]
    return {
        "schema_version": 1,
        "purpose": "engineering-feasibility-only-not-product-ready",
        "model_id": "Qwen/Qwen3.5-4B",
        "source_revision": SOURCE_REV,
        "quantization_repository": "unsloth/Qwen3.5-4B-GGUF",
        "quantization_revision": REV,
        "runtime_release": "b123",
        "model_license": "Apache-2.0",
        "runtime_license": "MIT",
        "resources": [
            {"id": identifier, "filename": filename, "url": url, "bytes": 5,
             "sha256": hashlib.sha256(identifier.encode()).hexdigest()}
            for identifier, filename, url in entries
        ],
    }


def test_catalog_is_detached_and_transport_dict_is_fresh(valid_manifest):
    original = valid_manifest["resources"][0]["sha256"]
    catalog = catalog_from_manifest(valid_manifest)
    valid_manifest["resources"][0]["sha256"] = "b" * 64
    first = next(x for x in catalog.resources if x.id == "runtime-cpu")
    exported = first.as_transport_dict()
    exported["sha256"] = "c" * 64
    assert first.sha256 == original
    assert first.as_transport_dict()["sha256"] == original
    assert catalog.total_bytes == 15


def test_catalog_identity_ignores_order_but_tracks_resource_and_revision(valid_manifest):
    first = catalog_from_manifest(valid_manifest)
    reordered = copy.deepcopy(valid_manifest)
    reordered["resources"].reverse()
    reordered = dict(reversed(list(reordered.items())))
    assert catalog_from_manifest(reordered).identity == first.identity
    changed = copy.deepcopy(valid_manifest)
    changed["resources"][0]["sha256"] = "c" * 64
    assert catalog_from_manifest(changed).identity != first.identity
    changed = copy.deepcopy(valid_manifest)
    changed["source_revision"] = "c" * 40
    assert catalog_from_manifest(changed).identity != first.identity


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", "1"), ("schema_version", 2),
    ("model_id", "Other/model"), ("quantization_repository", "Other/GGUF"),
    ("source_revision", "A" * 40), ("quantization_revision", "x" * 40),
    ("runtime_release", "v123"), ("model_license", "MIT"),
    ("runtime_license", "Apache-2.0"), ("purpose", ""),
    ("purpose", "x" * 121), ("purpose", "public\nsecret"),
])
def test_invalid_catalog_metadata_is_rejected(valid_manifest, field, value):
    valid_manifest[field] = value
    with pytest.raises(ResourceError):
        catalog_from_manifest(valid_manifest)


def test_resources_must_be_exactly_three_unique_entries(valid_manifest):
    variants = []
    missing = copy.deepcopy(valid_manifest)
    missing["resources"].pop()
    variants.append(missing)
    duplicate = copy.deepcopy(valid_manifest)
    duplicate["resources"][1]["id"] = "runtime-cpu"
    variants.append(duplicate)
    duplicate_name = copy.deepcopy(valid_manifest)
    duplicate_name["resources"][1]["filename"] = "RUNTIME-B123.ZIP"
    variants.append(duplicate_name)
    unknown = copy.deepcopy(valid_manifest)
    unknown["resources"][0]["extra"] = "not allowed"
    variants.append(unknown)
    for variant in variants:
        with pytest.raises(ResourceError):
            catalog_from_manifest(variant)


@pytest.mark.parametrize("field,value", [
    ("bytes", True), ("bytes", 4 * 1024 ** 3 + 1), ("bytes", 0),
    ("filename", "../escape.zip"), ("filename", "runtime.gguf"),
    ("url", "https://example.org/private"),
])
def test_invalid_resource_is_rejected(valid_manifest, field, value):
    valid_manifest["resources"][0][field] = value
    with pytest.raises(ResourceError):
        catalog_from_manifest(valid_manifest)


def test_revision_and_filename_mismatch_are_rejected(valid_manifest):
    bad = copy.deepcopy(valid_manifest)
    bad["resources"][1]["url"] = bad["resources"][1]["url"].replace(REV, "c" * 40)
    with pytest.raises(ResourceError):
        catalog_from_manifest(bad)
    bad = copy.deepcopy(valid_manifest)
    bad["resources"][2]["filename"] = "different.gguf"
    with pytest.raises(ResourceError):
        catalog_from_manifest(bad)


def test_total_size_bound(valid_manifest):
    for item in valid_manifest["resources"]:
        item["bytes"] = 2 * 1024 ** 3
    with pytest.raises(ResourceError):
        catalog_from_manifest(valid_manifest)


def test_loader_accepts_bounded_json_and_sanitizes_failures(valid_manifest, tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(valid_manifest), encoding="utf-8")
    assert load_resource_catalog(path).total_bytes == 15
    for bad in ("{broken", "x" * (64 * 1024 + 1)):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ResourceError) as caught:
            load_resource_catalog(path)
        assert str(path) not in str(caught.value)
        assert "broken" not in str(caught.value)
    with pytest.raises(ResourceError):
        load_resource_catalog(tmp_path)


def test_loader_sanitizes_recursion_error_from_deeply_nested_json(tmp_path):
    path = tmp_path / "deeply-nested-manifest.json"
    payload = "[" * 20_000 + "0" + "]" * 20_000
    assert len(payload.encode("utf-8")) < 64 * 1024
    # Python 3.14 accepts 2,000 levels; verify the actual decoder-failure branch.
    with pytest.raises(RecursionError):
        json.loads(payload)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ResourceError) as caught:
        load_resource_catalog(path)

    assert str(caught.value) == "invalid resource catalog"
    assert str(path) not in str(caught.value)


def test_real_feasibility_manifest_total_is_pinned():
    path = ROOT / "resources/local-models/qwen35-4b-feasibility.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert sum(item["bytes"] for item in manifest["resources"]) == 3431786583
    assert load_resource_catalog(path).total_bytes == 3431786583
