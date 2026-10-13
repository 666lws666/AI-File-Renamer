"""Fixed Qwen3.5-4B CPU launch metadata; this module never starts a process."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import ntpath
from pathlib import Path
import re
import subprocess
from types import MappingProxyType
from typing import Mapping

from src.services.local_ai.native.model_stage import BundleEvidence, MemberEvidence


RECIPE_VERSION = "qwen35-cpu-b10885-v1"
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", re.ASCII)
_VISUAL = re.compile(r"visual_0[0-7]\.(?:jpg|png|webp)", re.ASCII)
_DRIVE = re.compile(r"[A-Za-z]:\\", re.ASCII)
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


@dataclass(frozen=True)
class TrustedWindowsPaths:
    system_root: Path = field(repr=False)
    local_app_data: Path = field(repr=False)


@dataclass(frozen=True)
class LocalLaunchSpec:
    executable: Path = field(repr=False)
    cwd: Path = field(repr=False)
    arguments: tuple[str, ...] = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)
    recipe_version: str = RECIPE_VERSION


def _fail(code: str):
    raise ValueError(code)


def _path(value: object, code: str) -> str:
    if type(value) is not str or not _DRIVE.match(value) or len(value) < 3:
        _fail(code)
    if any(c in value for c in ("\x00", ";", "/")) or ntpath.normpath(value) != value:
        _fail(code)
    for part in value[3:].split("\\"):
        if (not part or part in (".", "..") or part.endswith((" ", "."))
                or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF
                       or c in '<>:"|?*' for c in part)
                or _RESERVED.fullmatch(part)):
            _fail(code)
    return value


def _name(value: object) -> str:
    if (type(value) is not str or not _NAME.fullmatch(value)
            or value.endswith(".") or _RESERVED.fullmatch(value)):
        _fail("member_name")
    return value


def _identity(value: object) -> bool:
    return (type(value) is tuple and len(value) == 2
            and all(type(part) is int and 0 <= part < 1 << 64 for part in value))


def _members(evidence: BundleEvidence) -> dict[str, MemberEvidence]:
    if (type(evidence) is not BundleEvidence
            or not _identity(evidence.directory_id)
            or type(evidence.members) is not tuple
            or not 1 <= len(evidence.members) <= 80):
        _fail("bundle_evidence")
    directory = _path(evidence.directory_path, "bundle_path")
    parent = ntpath.dirname(directory)
    if len(parent) > 180 or not re.fullmatch(r"stage_[0-9a-f]{32}", ntpath.basename(directory)):
        _fail("bundle_path")
    _path(evidence.executable_path, "entrypoint_path")
    found: dict[str, MemberEvidence] = {}
    for member in evidence.members:
        if (type(member) is not MemberEvidence or not _identity(member.identity)
                or type(member.size) is not int or not 0 < member.size <= 4 * 1024**3
                or type(member.sha256) is not str or not _SHA256.fullmatch(member.sha256)):
            _fail("member_evidence")
        name = _name(member.name)
        if name.casefold() in found:
            _fail("member_duplicate")
        if _path(member.path, "member_path") != ntpath.join(directory, name):
            _fail("member_path")
        found[name.casefold()] = member
    return found


def _selected(found: dict[str, MemberEvidence], name: str) -> MemberEvidence:
    member = found.get(_name(name).casefold())
    if member is None or member.name != name:
        _fail("member_missing")
    return member


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _check_sizes(executable: str, args: tuple[str, ...], env: Mapping[str, str]) -> None:
    command = subprocess.list2cmdline((executable, *args))
    if _utf16_units(command) + 1 >= 32767:
        _fail("command_line_size")
    if len({key.casefold() for key in env}) != len(env):
        _fail("environment_duplicate")
    block = "\x00".join(f"{key}={value}" for key, value in env.items()) + "\x00\x00"
    if _utf16_units(block) > 32767:
        _fail("environment_size")


def build_launch(evidence: BundleEvidence, *, model_name: str,
                 projector_name: str | None, visual_names: tuple[str, ...],
                 windows_paths: TrustedWindowsPaths) -> LocalLaunchSpec:
    """Validate owned evidence and return the only supported CPU recipe."""
    found = _members(evidence)
    if type(model_name) is not str or projector_name is not None and type(projector_name) is not str:
        _fail("member_name")
    if type(visual_names) is not tuple or len(visual_names) > 8:
        _fail("visual_names")
    for index, name in enumerate(visual_names):
        if type(name) is not str or not _VISUAL.fullmatch(name) or not name.startswith(f"visual_{index:02d}."):
            _fail("visual_names")
        _selected(found, name)
    if ((projector_name is None) == bool(visual_names)
            or projector_name is not None and projector_name.casefold() == model_name.casefold()):
        _fail("projector_selection")
    model = _selected(found, model_name)
    if not model_name.endswith(".gguf"):
        _fail("model_name")
    selected_models = {model_name.casefold()}
    if projector_name is not None:
        selected_models.add(_name(projector_name).casefold())
    if ({name for name in found if name.endswith(".gguf")} != selected_models
            or {name for name in found if name.startswith("visual_")}
            != {name.casefold() for name in visual_names}):
        _fail("member_selection")
    _selected(found, "prompt.txt")
    _selected(found, "schema.json")
    entry_name = "llama-mtmd-cli.exe" if visual_names else "llama-completion.exe"
    entry = _selected(found, entry_name)
    if evidence.executable_path != entry.path:
        _fail("entrypoint_path")
    directory = evidence.directory_path
    common = (
        "--offline", "-m", model.path, "-f", "prompt.txt",
        "--json-schema-file", "schema.json", "-n", "1024", "-c", "8192",
        "-t", "4", "-tb", "4", "--device", "none", "--no-op-offload",
        "--no-kv-offload", "--flash-attn", "off", "--no-warmup", "--seed", "1",
        "--temp", "0", "--log-colors", "off", "--verbosity", "1",
    )
    if visual_names:
        projector = _selected(found, projector_name)
        if not projector_name.endswith(".gguf"):
            _fail("projector_name")
        extra = ("--mmproj", projector.path, "--mmproj-device", "none",
                 "--no-mmproj-offload", "--image", ",".join(visual_names),
                 "--image-max-tokens", "1024")
    else:
        extra = ("--conversation", "--single-turn", "--jinja", "--reasoning", "off",
                 "--no-display-prompt", "--simple-io")
    if type(windows_paths) is not TrustedWindowsPaths:
        _fail("windows_paths")
    if not isinstance(windows_paths.system_root, Path) or not isinstance(windows_paths.local_app_data, Path):
        _fail("windows_paths")
    system_root = _path(str(windows_paths.system_root), "windows_paths")
    local_app_data = _path(str(windows_paths.local_app_data), "windows_paths")
    environment = MappingProxyType({
        "SystemRoot": system_root, "WINDIR": system_root,
        "PATH": directory + ";" + ntpath.join(system_root, "System32"),
        "TEMP": directory, "TMP": directory, "LOCALAPPDATA": local_app_data,
    })
    arguments = common + extra
    _check_sizes(entry.path, arguments, environment)
    return LocalLaunchSpec(Path(entry.path), Path(directory), arguments, environment)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


_LOCAL_APP_DATA = _GUID(0xF1B32785, 0x6FBA, 0x4FCF,
                        (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91))


class _WindowsPathsApi:
    def __init__(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        ole = ctypes.WinDLL("ole32", use_last_error=True)
        self._windows = kernel.GetWindowsDirectoryW
        self._windows.argtypes = (wintypes.LPWSTR, wintypes.UINT)
        self._windows.restype = wintypes.UINT
        self._folder = shell.SHGetKnownFolderPath
        self._folder.argtypes = (ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
                                 ctypes.POINTER(ctypes.c_wchar_p))
        self._folder.restype = ctypes.c_long
        self._attributes = kernel.GetFileAttributesW
        self._attributes.argtypes = (wintypes.LPCWSTR,)
        self._attributes.restype = wintypes.DWORD
        self._free = ole.CoTaskMemFree
        self._free.argtypes = (ctypes.c_void_p,)
        self._free.restype = None

    def windows_directory(self) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        count = self._windows(buffer, len(buffer))
        if not count or count >= len(buffer):
            raise OSError("GetWindowsDirectoryW")
        return buffer.value

    def local_app_data(self) -> tuple[str, ctypes.c_wchar_p]:
        pointer = ctypes.c_wchar_p()
        result = self._folder(ctypes.byref(_LOCAL_APP_DATA), 0, None, ctypes.byref(pointer))
        if result:
            if pointer:
                self.free(pointer)
            raise OSError("SHGetKnownFolderPath")
        return pointer.value, pointer

    def directory_attributes(self, path: str) -> int:
        result = self._attributes(path)
        if result == 0xFFFFFFFF:
            raise OSError("GetFileAttributesW")
        return result

    def free(self, pointer) -> None:
        self._free(ctypes.cast(pointer, ctypes.c_void_p))


def discover_windows_paths() -> TrustedWindowsPaths:
    """Read two OS-owned directories without environment fallback or mutation."""
    try:
        api = _WindowsPathsApi()
        root = api.windows_directory()
        local, buffer = api.local_app_data()
        try:
            for path in (root, local):
                _path(path, "windows_discovery")
                if api.directory_attributes(path) & 0x410 != 0x10:
                    _fail("windows_discovery")
        finally:
            api.free(buffer)
        return TrustedWindowsPaths(Path(root), Path(local))
    except (OSError, AttributeError, TypeError, ValueError):
        raise ValueError("windows_discovery") from None
