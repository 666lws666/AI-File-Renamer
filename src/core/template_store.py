"""M4 TemplateStore — CRUD, JSON persistence, atomic writes, fail-closed validation."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from .template_model import (
    Template, TemplateField, DateFormat, Separator, OrgMode, OutputLanguage,
    _PLACEHOLDER_RE,
)


# ── Errors ───────────────────────────────────────────────────────────────────

class TemplateNotFoundError(Exception):
    """Raised when a template ID is not found in the store."""
    pass


class TemplateIntegrityError(Exception):
    """Raised when persisted data fails integrity checks (corruption, duplicates, schema)."""
    pass


class TemplateReferenceError(Exception):
    """Raised when delete constraints are violated (referenced template without replacement)."""
    pass


# ── Serialization ────────────────────────────────────────────────────────────

def _template_to_dict(t: Template) -> dict:
    """Serialize a Template to a JSON-safe dict."""
    return {
        "id": t.id,
        "name": t.name,
        "pattern": t.pattern,
        "date_format": t.date_format.value,
        "separator": t.separator.value,
        "org_mode": t.org_mode.value,
        "output_language": t.output_language.value,
        "fields": [
            {
                "id": f.id,
                "dc_name": f.dc_name,
                "display_name": f.display_name,
                "order": f.order,
                "enabled": f.enabled,
            }
            for f in t.fields
        ],
        "version": t.version,
    }


def _template_from_dict(d: dict) -> Template:
    """Deserialize a dict back to a Template, with validation."""
    try:
        fields = [
            TemplateField(
                id=f["id"],
                dc_name=f["dc_name"],
                display_name=f["display_name"],
                order=f["order"],
                enabled=f.get("enabled", True),
            )
            for f in d["fields"]
        ]
        return Template(
            id=d["id"],
            name=d["name"],
            pattern=d.get("pattern", "{dcDate}_{dcTitle}"),
            date_format=DateFormat(d["date_format"]),
            separator=Separator(d["separator"]),
            org_mode=OrgMode(d.get("org_mode", "flat")),
            output_language=OutputLanguage(d.get("output_language", "zh")),
            fields=fields,
            version=d.get("version", 1),
        )
    except (KeyError, ValueError) as e:
        raise TemplateIntegrityError(f"Invalid template data in store: {e}") from e


# ── TemplateStore ────────────────────────────────────────────────────────────

class TemplateStore:
    """Persistent CRUD store for Templates with atomic writes and fail-closed validation."""

    def __init__(self, file_path: str | Path):
        self._file_path = Path(file_path)
        self._lock = threading.Lock()
        self._templates: dict[str, Template] = {}
        self._installed_presets: set[str] = set()
        self._load()

    # ── Public API ───────────────────────────────────────────────────────────

    def create(self, template: Template) -> Template:
        """Create a new template. Raises TemplateIntegrityError on duplicate ID."""
        with self._lock:
            if template.id in self._templates:
                raise TemplateIntegrityError(
                    f"Duplicate template ID: {template.id}"
                )
            candidate = dict(self._templates)
            candidate[template.id] = template
            self._save(candidate)
            self._templates = candidate
            return template

    def get(self, template_id: str) -> Template:
        """Get a template by ID. Raises TemplateNotFoundError if missing."""
        with self._lock:
            if template_id not in self._templates:
                raise TemplateNotFoundError(
                    f"Template not found: {template_id}"
                )
            return self._templates[template_id]

    def list_all(self) -> list[Template]:
        """Return all templates."""
        with self._lock:
            return list(self._templates.values())

    def update(self, template_id: str, **kwargs) -> Template:
        """Update a template's fields and increment version.

        Accepts keyword arguments for any Template field.
        Raises TemplateNotFoundError if the ID is unknown.
        """
        with self._lock:
            if template_id not in self._templates:
                raise TemplateNotFoundError(
                    f"Template not found for update: {template_id}"
                )
            current = self._templates[template_id]

            # Build update dict from current values, overlaid with kwargs
            update_dict = {
                "id": current.id,
                "name": kwargs.get("name", current.name),
                "pattern": kwargs.get("pattern", current.pattern),
                "date_format": kwargs.get("date_format", current.date_format),
                "separator": kwargs.get("separator", current.separator),
                "org_mode": kwargs.get("org_mode", current.org_mode),
                "output_language": kwargs.get("output_language", current.output_language),
                "fields": kwargs.get("fields", list(current.fields)),
                "version": current.version + 1,
            }

            updated = Template(**update_dict)
            candidate = dict(self._templates)
            candidate[template_id] = updated
            self._save(candidate)
            self._templates = candidate
            return updated

    def delete(
        self,
        template_id: str,
        is_referenced: bool = False,
        replacement_template_id: Optional[str] = None,
    ) -> None:
        """Delete a template.

        Args:
            template_id: ID of the template to delete.
            is_referenced: Whether this template is referenced by any task.
            replacement_template_id: Required if is_referenced is True.
                The replacement must exist and must differ from the deleted template.

        Raises:
            TemplateNotFoundError: If template_id or replacement_template_id not found.
            TemplateReferenceError: If referenced but no valid replacement given.
        """
        with self._lock:
            if template_id not in self._templates:
                raise TemplateNotFoundError(
                    f"Template not found for delete: {template_id}"
                )

            if is_referenced:
                if replacement_template_id is None:
                    raise TemplateReferenceError(
                        "Cannot delete referenced template without a replacement_template_id"
                    )
                if replacement_template_id == template_id:
                    raise TemplateReferenceError(
                        "Replacement template cannot be the same as the deleted template"
                    )
                if replacement_template_id not in self._templates:
                    raise TemplateNotFoundError(
                        f"Replacement template not found: {replacement_template_id}"
                    )

            candidate = dict(self._templates)
            del candidate[template_id]
            self._save(candidate)
            self._templates = candidate

    # ── Persistence ──────────────────────────────────────────────────────────

    def install_presets(self, presets: tuple[Template, ...]) -> None:
        """Install unseen IDs once, preserving user changes and deletion history."""
        with self._lock:
            candidate = dict(self._templates)
            installed = set(self._installed_presets)
            for preset in presets:
                if preset.id not in installed:
                    candidate.setdefault(preset.id, preset)
                    installed.add(preset.id)
            if installed == self._installed_presets:
                return
            self._save(candidate, installed_presets=installed)
            self._templates = candidate
            self._installed_presets = installed

    def _save(self, templates: dict[str, Template] | None = None,
              *, installed_presets: set[str] | None = None) -> None:
        """Atomically persist a candidate snapshot without mutating live state."""
        snapshot = self._templates if templates is None else templates
        data = [_template_to_dict(t) for t in snapshot.values()]
        installed = self._installed_presets if installed_presets is None else installed_presets
        if installed:
            data = {"schema_version": 1, "templates": data, "installed_presets": sorted(installed)}
        json_text = json.dumps(data, ensure_ascii=False, indent=2)

        # Atomic write: write to temp file, then replace
        tmp = None
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix="templates_",
                dir=str(self._file_path.parent),
            )
            tmp = Path(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_text)
            os.replace(tmp_path, str(self._file_path))
        except Exception:
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    def _load(self) -> None:
        """Load templates from the JSON file with validation.

        Raises TemplateIntegrityError on corruption, duplicates, or unknown schema.
        """
        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text("[]", encoding="utf-8")
            return

        try:
            raw_text = self._file_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise TemplateIntegrityError(
                f"Corrupted template store file: {e}"
            ) from e

        if isinstance(data, dict):
            if (set(data) != {"schema_version", "templates", "installed_presets"}
                    or type(data["schema_version"]) is not int or data["schema_version"] != 1):
                raise TemplateIntegrityError("Unsupported template store schema")
            installed = data["installed_presets"]
            if (not isinstance(installed, list)
                    or any(not isinstance(item, str) or not item.strip() for item in installed)
                    or len(set(installed)) != len(installed)):
                raise TemplateIntegrityError("Invalid installed preset ledger")
            self._installed_presets = set(installed)
            data = data["templates"]
        if not isinstance(data, list):
            raise TemplateIntegrityError(
                f"Template store file must contain a JSON array, got {type(data).__name__}"
            )

        # Reject unknown top-level keys or objects without required structure
        required_keys = {"id", "name", "pattern", "date_format", "separator",
                         "org_mode", "output_language", "fields", "version"}
        seen_ids: set[str] = set()

        for item in data:
            if not isinstance(item, dict):
                raise TemplateIntegrityError(
                    f"Each template entry must be a JSON object, got {type(item).__name__}"
                )
            # Reject objects with extra unknown keys
            extra_keys = set(item.keys()) - required_keys
            if extra_keys:
                raise TemplateIntegrityError(
                    f"Unknown keys in template entry: {sorted(extra_keys)}"
                )
            # Check required keys exist
            missing_keys = required_keys - set(item.keys())
            if missing_keys:
                raise TemplateIntegrityError(
                    f"Missing required keys in template entry: {sorted(missing_keys)}"
                )
            # Check duplicate IDs
            tid = item["id"]
            if tid in seen_ids:
                raise TemplateIntegrityError(
                    f"Duplicate template ID in store: {tid}"
                )
            seen_ids.add(tid)

        # Deserialize each entry
        for item in data:
            t = _template_from_dict(item)
            self._templates[t.id] = t
