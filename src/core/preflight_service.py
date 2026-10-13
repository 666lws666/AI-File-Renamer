"""M2 PreflightService — check only, fail-closed path containment, no disk mutation."""
import os
from pathlib import Path
from src.core.rename_plan import RenamePlan, PreflightResult
from src.core.filename_validator import validate_filename


def _is_inside(path: str, root: str) -> bool:
    """True if normalized realpath of `path` is inside normalized realpath of `root`."""
    try:
        rp = os.path.realpath(path)
        rr = os.path.realpath(root)
    except (ValueError, OSError):
        return False
    # Use commonpath for containment; ValueErr if unrelated drives
    try:
        common = os.path.commonpath([rp, rr])
    except ValueError:
        return False
    # Normalize case on Windows
    common_n = os.path.normcase(common)
    rr_n = os.path.normcase(rr)
    return common_n == rr_n


class WatchPreflightService:
    """Preflight roots derived from the current persisted Watch configs.

    The provider is evaluated for every check, so watches added or edited after
    application startup are covered without trusting roots carried by a plan.
    """

    def __init__(self, configs_provider):
        self._configs_provider = configs_provider

    def check(self, plan: RenamePlan) -> PreflightResult:
        roots = []
        try:
            configs = tuple(self._configs_provider())
        except Exception:
            configs = ()
        for config in configs:
            source = str(getattr(config, "source_dir", "") or "")
            target = str(getattr(config, "target_dir", "") or source)
            if source:
                roots.append(source)
            if target:
                roots.append(target)
        return PreflightService(allowed_roots=roots).check(plan)


class PreflightService:
    def __init__(self, allowed_roots: list[str] | None = None):
        # Preserve original lexical spelling; comparison never resolves links.
        roots, seen = [], set()
        try:
            for root in tuple(allowed_roots or ()):
                if type(root) is not str or not root.strip() or '\x00' in root or len(root) > 4096:
                    raise ValueError()
                key = os.path.normcase(os.path.normpath(root))
                if key not in seen:
                    roots.append(root); seen.add(key)
            if len(roots) > 2000: raise ValueError()
        except (ValueError, TypeError):
            roots = []
        self._allowed_roots = tuple(roots)

    def check(self, plan: RenamePlan) -> PreflightResult:
        errors = []
        warnings = []

        if not self._allowed_roots:
            return PreflightResult(False, errors=["No allowed roots configured — fail-closed"])

        # Source must exist
        if not os.path.isfile(plan.source_path):
            return PreflightResult(False, errors=["Source file does not exist"])

        # Source must be inside an allowed root
        source_ok = any(_is_inside(plan.source_path, r) for r in self._allowed_roots)
        if not source_ok:
            errors.append("Source path is outside allowed root directories")

        # Target parent must be inside an allowed root
        target_parent = os.path.dirname(os.path.join(plan.target_parent, plan.target_name))
        # Walk up to find existing ancestor for realpath resolution
        check_parent = target_parent
        while check_parent and not os.path.exists(check_parent):
            check_parent = os.path.dirname(check_parent)
        target_parent_real = os.path.realpath(check_parent) if check_parent else os.path.realpath(plan.target_parent)
        target_ok = any(_is_inside(target_parent_real, r) for r in self._allowed_roots)
        if not target_ok:
            errors.append("Target path escapes allowed root directories")
            return PreflightResult(False, errors=errors)

        # Fingerprint check
        stat = os.stat(plan.source_path)
        if stat.st_size != plan.source_fingerprint.size_bytes or stat.st_mtime_ns != plan.source_fingerprint.mtime_ns:
            errors.append("Source file has changed since scan")

        # Filename + extension validation
        val = validate_filename(plan.target_name, plan.extension)
        if not val.is_valid:
            errors.extend(e.detail for e in val.errors)

        # Resolve target
        resolved_target = os.path.realpath(os.path.join(plan.target_parent, plan.target_name))
        resolved_source = os.path.realpath(plan.source_path)

        # Target must still be inside allowed root after resolution
        target_final_ok = any(_is_inside(resolved_target, r) for r in self._allowed_roots)
        if not target_final_ok:
            errors.append("Resolved target path escapes allowed root directories")

        # Parent directory check
        parent = os.path.dirname(resolved_target)
        if os.path.exists(parent) and not os.path.isdir(parent):
            errors.append("Target parent is not a directory")

        # Conflict check
        if os.path.exists(resolved_target):
            warnings.append("Target path already exists — auto-counter will be applied")

        return PreflightResult(
            can_execute=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            resolved_source=resolved_source,
            resolved_target=resolved_target,
            allowed_roots=self._allowed_roots,
        )
