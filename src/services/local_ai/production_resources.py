"""Inert, program-relative product resources; explicit worker-only parents."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .resource_catalog import ResourceCatalog, catalog_from_manifest, load_resource_catalog
from .resource_store import _local_path, _prepare_directory_parents
from .resource_transport import ResourceError


PRODUCT_CATALOG_ID = "1b3ca415eff1c7c2c91b0f6e743550ac6c2e75a7e4a750bb319c7d330ba6b859"


@dataclass(frozen=True, slots=True)
class ProductionLocalResources:
    catalog: ResourceCatalog
    bundled_runtime: Path
    resource_root: Path
    runtime_root: Path
    state_root: Path


def load_production_resources(*, bundle_root: Path | None = None,
                              user_data_root: Path | None = None) -> ProductionLocalResources:
    if bundle_root is None:
        bundle_root = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else Path(__file__).parents[3]
    try:
        application = _local_path(bundle_root)
        if user_data_root is None:
            user_data_root = _local_path(os.environ.get("LOCALAPPDATA")) / "Xuxia" / "local-ai"
        base = _local_path(user_data_root)
    except (ResourceError, TypeError, ValueError):
        raise ResourceError("INVALID_PRODUCT_ROOT", code="INVALID_PRODUCT_ROOT") from None
    try:
        catalog = load_resource_catalog(application / "resources/local-models/qwen35-4b-managed-v1.json")
        if (catalog.identity != PRODUCT_CATALOG_ID or catalog.runtime_release != "b10885"
                or catalog.purpose != "managed-local-resources-v1"):
            raise ResourceError("INVALID_PRODUCT_CATALOG")
    except ResourceError:
        raise ResourceError("INVALID_PRODUCT_CATALOG", code="INVALID_PRODUCT_CATALOG") from None
    return ProductionLocalResources(catalog,
        application / "resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip",
        base / "resources" / catalog.identity, base / "runtime" / catalog.identity,
        base / "state")


@contextmanager
def prepare_production_parents(config: ProductionLocalResources, *, trusted_anchor: Path,
                               for_readiness: bool = False, cancelled=lambda: False):
    if not isinstance(config, ProductionLocalResources) or type(for_readiness) is not bool:
        raise ResourceError("INVALID_PRODUCT_CONFIG", code="INVALID_PRODUCT_CONFIG")
    try:
        manifest = {field: getattr(config.catalog, field) for field in
                    ("model_id", "source_revision", "quantization_repository",
                     "quantization_revision", "runtime_release", "model_license",
                     "runtime_license", "purpose")}
        manifest.update(schema_version=1, resources=[item.as_transport_dict() for item in config.catalog.resources])
        canonical = catalog_from_manifest(manifest)
        if canonical != config.catalog:
            raise ResourceError("INVALID_PRODUCT_CONFIG")
    except (AttributeError, TypeError, ResourceError):
        raise ResourceError("INVALID_PRODUCT_CONFIG", code="INVALID_PRODUCT_CONFIG") from None
    base = _local_path(config.state_root).parent
    if (config.catalog.identity != PRODUCT_CATALOG_ID
            or config.catalog.purpose != "managed-local-resources-v1"
            or config.catalog.runtime_release != "b10885"
            or config.state_root != base / "state"
            or config.resource_root != base / "resources" / PRODUCT_CATALOG_ID
            or config.runtime_root != base / "runtime" / PRODUCT_CATALOG_ID):
        raise ResourceError("INVALID_PRODUCT_CONFIG", code="INVALID_PRODUCT_CONFIG")
    parents = (config.resource_root.parent,)
    if for_readiness:
        parents += (config.runtime_root.parent, config.state_root.parent)
    with _prepare_directory_parents(trusted_anchor=trusted_anchor, parents=parents,
                                    cancelled=cancelled) as owner:
        yield owner
