"""Pure immutable analysis inputs and their shared admission/publication fence.

Build on Qt with actual templates. Later composition must hold source.guard()
across invalidation, install and engine binding, releasing before notifications.
Lock order: catalog source, then processing authority. Never perform I/O here.
"""
from dataclasses import dataclass, fields
from threading import RLock

from src.core.processing_analysis import AnalysisSettings, snapshot_template
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities
from src.core.template_model import Template


def _profile_snapshot(raw):
    if raw is None:
        return None
    if type(raw) not in (dict, ProviderProfile):
        raise ValueError("Invalid analysis catalog")
    defaults = ProviderProfile()
    values = {f.name: (raw.get(f.name, getattr(defaults, f.name)) if type(raw) is dict
                      else getattr(raw, f.name)) for f in fields(ProviderProfile)}
    capabilities = values.pop("capabilities")
    if type(capabilities) not in (dict, ProviderCapabilities):
        raise ValueError("Invalid analysis catalog")
    cap_values = {f.name: (capabilities.get(f.name, False) if type(capabilities) is dict
                          else getattr(capabilities, f.name)) for f in fields(ProviderCapabilities)}
    if any(type(value) is not bool for value in cap_values.values()):
        raise ValueError("Invalid analysis catalog")
    for name, value in values.items():
        expected = bool if name in {"enabled", "needs_connection_verification"} else int if name == "timeout_seconds" else str
        if type(value) is not expected:
            raise ValueError("Invalid analysis catalog")
    profile = ProviderProfile(**values, capabilities=ProviderCapabilities(**cap_values))
    if not profile.enabled or profile.needs_connection_verification or not profile.id or not profile.model:
        return None
    return profile


@dataclass(frozen=True, slots=True)
class AnalysisCatalog:
    settings: AnalysisSettings
    active_profile: ProviderProfile | None
    default_template_id: str
    templates: tuple[Template, ...]

    def __post_init__(self):
        try:
            if type(self.settings) is not AnalysisSettings or type(self.default_template_id) is not str or type(self.templates) is not tuple:
                raise ValueError
            snapshots = tuple(snapshot_template(template) for template in self.templates)
            if len(snapshots) > 1000 or any(not t.id for t in snapshots) or len({t.id for t in snapshots}) != len(snapshots):
                raise ValueError
            object.__setattr__(self, "settings", AnalysisSettings.capture(self.settings))
            object.__setattr__(self, "active_profile", _profile_snapshot(self.active_profile))
            object.__setattr__(self, "templates", snapshots)
        except Exception:
            raise ValueError("Invalid analysis catalog") from None

    def template(self, template_id=""):
        selected = template_id or self.default_template_id
        if not selected and self.templates:
            return self.templates[0]
        for template in self.templates:
            if template.id == selected:
                return template
        raise ValueError("Unknown analysis template")


def build_analysis_catalog(config, templates):
    """Explicit Qt-side builder; no config, credential or extras retained."""
    try:
        active = None
        for raw in config.provider_profiles:
            if type(raw) is not dict:
                raise ValueError
            if raw.get("id") == config.active_provider_id:
                if active is not None:
                    raise ValueError
                active = raw
        return AnalysisCatalog(AnalysisSettings.capture(config), _profile_snapshot(active),
                               config.default_template_id, tuple(templates))
    except Exception:
        raise ValueError("Invalid analysis catalog") from None


class AnalysisCatalogSource:
    """One complete reference; bounded pure operations, reentrant shared guard."""
    def __init__(self, catalog):
        self._lock = RLock()
        self.install(catalog)

    def guard(self):
        return self._lock

    def get(self):
        with self.guard():
            return self._catalog

    def install(self, catalog):
        if type(catalog) is not AnalysisCatalog:
            raise ValueError("Invalid analysis catalog")
        with self.guard():
            self._catalog = catalog
