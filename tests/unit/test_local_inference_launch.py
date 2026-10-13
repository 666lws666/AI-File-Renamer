"""Fixed, non-executing Qwen3.5 launch metadata contract."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType
import sys

import pytest

from src.services.local_ai.native.model_stage import BundleEvidence, MemberEvidence
from src.services.local_ai.native.stage import SecurityFacts
from src.services.local_ai import inference_launch as launch


DIRECTORY = r"C:\owned\stage_0123456789abcdef0123456789abcdef"
SECURITY = SecurityFacts("S-1-5-21-1", True, True, ())
WINDOWS = launch.TrustedWindowsPaths(Path(r"C:\Windows"), Path(r"C:\Users\Alice\AppData\Local"))
COMMON = (
    "--offline", "-m", DIRECTORY + r"\model.gguf", "-f", "prompt.txt",
    "--json-schema-file", "schema.json", "-n", "1024", "-c", "8192",
    "-t", "4", "-tb", "4", "--device", "none", "--no-op-offload",
    "--no-kv-offload", "--flash-attn", "off", "--no-warmup", "--seed", "1",
    "--temp", "0", "--log-colors", "off", "--verbosity", "1",
)


def member(name, **changes):
    value = MemberEvidence(name, None, None, DIRECTORY + "\\" + name,
                           (1, 2), 1, "0" * 64, SECURITY)
    return replace(value, **changes)


def evidence(*, visual_names=(), projector=False, executable=None, extra=()):
    entry = executable or ("llama-mtmd-cli.exe" if visual_names else "llama-completion.exe")
    names = [entry, "model.gguf", "prompt.txt", "schema.json"]
    if projector:
        names.append("projector.gguf")
    names.extend(visual_names)
    members = tuple(member(name) for name in names) + tuple(extra)
    return BundleEvidence(DIRECTORY, (1, 1), SECURITY,
                          DIRECTORY + "\\" + entry, members)


def build(bundle, *, visual_names=(), projector_name=None, windows_paths=WINDOWS):
    return launch.build_launch(bundle, model_name="model.gguf",
                               projector_name=projector_name,
                               visual_names=visual_names, windows_paths=windows_paths)


def test_text_recipe_exact_and_private():
    spec = build(evidence())
    assert spec.executable == Path(DIRECTORY + r"\llama-completion.exe")
    assert spec.cwd == Path(DIRECTORY)
    assert spec.arguments == COMMON + (
        "--conversation", "--single-turn", "--jinja", "--reasoning", "off",
        "--no-display-prompt", "--simple-io")
    assert spec.recipe_version == "qwen35-cpu-b10885-v1"
    assert dict(spec.environment) == {
        "SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows",
        "PATH": DIRECTORY + r";C:\Windows\System32", "TEMP": DIRECTORY,
        "TMP": DIRECTORY, "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local"}
    assert isinstance(spec.environment, MappingProxyType)
    with pytest.raises(TypeError):
        spec.environment["PATH"] = "poison"
    with pytest.raises(FrozenInstanceError):
        spec.arguments = ()
    assert DIRECTORY not in repr(spec)
    assert "model.gguf" not in repr(spec)


@pytest.mark.parametrize("names", [
    ("visual_00.jpg",),
    ("visual_00.jpg", "visual_01.png", "visual_02.webp", "visual_03.jpg",
     "visual_04.png", "visual_05.webp", "visual_06.jpg", "visual_07.webp"),
])
def test_visual_recipe_exact(names):
    spec = build(evidence(visual_names=names, projector=True),
                 visual_names=names, projector_name="projector.gguf")
    assert spec.executable == Path(DIRECTORY + r"\llama-mtmd-cli.exe")
    assert spec.arguments == COMMON + (
        "--mmproj", DIRECTORY + r"\projector.gguf", "--mmproj-device", "none",
        "--no-mmproj-offload", "--image", ",".join(names),
        "--image-max-tokens", "1024")


@pytest.mark.parametrize("bundle,projector,names", [
    (evidence(extra=(member("MODEL.GGUF"),)), None, ()),
    (evidence(extra=(member("junk,flag"),)), None, ()),
    (evidence(extra=(member("junk.exe", path=r"D:\elsewhere\junk.exe"),)), None, ()),
    (evidence(extra=(member("junk.exe", size=True),)), None, ()),
    (evidence(executable="llama-mtmd-cli.exe"), None, ()),
    (evidence(), "projector.gguf", ()),
    (evidence(visual_names=("visual_00.jpg",), projector=True), "projector.gguf", ("visual_01.jpg",)),
    (evidence(visual_names=("visual_00.jpg",), projector=True), "projector.gguf", ("visual_00.gif",)),
    (evidence(visual_names=("visual_00.jpg",), projector=True), "projector.gguf", ("visual_00.jpg", "visual_00.jpg")),
    (evidence(visual_names=("visual_00.jpg",), projector=True), None, ("visual_00.jpg",)),
    (evidence(visual_names=("visual_00.jpg",)), "model.gguf", ("visual_00.jpg",)),
    (evidence(extra=(member("other.gguf"),)), None, ()),
    (evidence(extra=(member("projector.gguf"),)), None, ()),
    (evidence(extra=(member("visual_00.jpg"),)), None, ()),
    (replace(evidence(), members=tuple(m for m in evidence().members if m.name != "prompt.txt")), None, ()),
    (replace(evidence(), members=tuple(m for m in evidence().members if m.name != "schema.json")), None, ()),
])
def test_rejects_malformed_evidence_and_selection(bundle, projector, names):
    with pytest.raises(ValueError):
        build(bundle, projector_name=projector, visual_names=names)


@pytest.mark.parametrize("changed", [
    {"members": ()},
    {"directory_path": r"\\server\share\stage"},
    {"directory_path": "C:\\owned\\stage;bad"},
    {"directory_id": (True, 1)},
    {"executable_path": DIRECTORY + r"\other.exe"},
])
def test_rejects_bad_bundle(changed):
    with pytest.raises(ValueError):
        build(replace(evidence(), **changed))


@pytest.mark.parametrize("name", ["../model.gguf", "model,other.gguf", "bad\x00.gguf", "C:\\model.gguf", "CON"])
def test_rejects_bad_model_basename(name):
    with pytest.raises(ValueError):
        launch.build_launch(evidence(), model_name=name, projector_name=None,
                            visual_names=(), windows_paths=WINDOWS)


@pytest.mark.parametrize("model,projector", [(None, None), (1, None), ("model.gguf", 1)])
def test_rejects_wrong_selection_types_with_fixed_error(model, projector):
    with pytest.raises(ValueError):
        launch.build_launch(evidence(), model_name=model, projector_name=projector,
                            visual_names=(), windows_paths=WINDOWS)


def test_rejects_wrong_visual_projector_type_with_fixed_error():
    with pytest.raises(ValueError):
        launch.build_launch(evidence(visual_names=("visual_00.jpg",)),
                            model_name="model.gguf", projector_name=1,
                            visual_names=("visual_00.jpg",), windows_paths=WINDOWS)


@pytest.mark.parametrize("root,local", [
    (r"\\server\share", r"C:\Users\Alice\AppData\Local"),
    (r"C:\Windows;poison", r"C:\Users\Alice\AppData\Local"),
    (r"C:\Windows", r"\\?\C:\Users\Alice\AppData\Local"),
    (r"C:\Windows", "C:\\Users\\Alice\\AppData\\Local\x00"),
])
def test_rejects_bad_environment_paths(root, local):
    with pytest.raises(ValueError):
        build(evidence(), windows_paths=launch.TrustedWindowsPaths(Path(root), Path(local)))


def test_surrogate_path_has_fixed_error():
    bad = launch.TrustedWindowsPaths(WINDOWS.system_root,
                                     Path("C:\\Users\\Alice\\AppData\\Local\ud800"))
    with pytest.raises(ValueError, match="^windows_paths$"):
        build(evidence(), windows_paths=bad)


def test_rejects_stage_parent_size_and_command_line_size():
    long_parent = "C:\\" + "a" * 181
    long_dir = long_parent + r"\stage_0123456789abcdef0123456789abcdef"
    bad = replace(evidence(), directory_path=long_dir,
                  executable_path=long_dir + r"\llama-completion.exe",
                  members=tuple(replace(m, path=long_dir + "\\" + m.name)
                                for m in evidence().members))
    with pytest.raises(ValueError):
        build(bad)
    huge = "C:\\" + "a" * 33000
    with pytest.raises(ValueError):
        build(evidence(), windows_paths=launch.TrustedWindowsPaths(Path(huge), WINDOWS.local_app_data))


def test_rejects_command_and_environment_utf16_bounds():
    with pytest.raises(ValueError, match="command_line_size"):
        launch._check_sizes(r"C:\x.exe", ("😎" * 17000,), {"A": "B"})
    with pytest.raises(ValueError, match="environment_size"):
        launch._check_sizes(r"C:\x.exe", (), {"A": "😎" * 17000})
    with pytest.raises(ValueError, match="environment_duplicate"):
        launch._check_sizes(r"C:\x.exe", (), {"PATH": "x", "Path": "y"})


def test_host_environment_poison_does_not_enter_spec(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\hostile")
    monkeypatch.setenv("HF_HOME", r"C:\private\model-cache")
    monkeypatch.setenv("HTTPS_PROXY", "http://secret.example")
    spec = build(evidence())
    assert set(spec.environment) == {"SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA"}
    assert "hostile" not in repr(dict(spec.environment))
    assert "HF_HOME" not in spec.environment
    assert "HTTPS_PROXY" not in spec.environment


def test_discovery_success_uses_and_frees_native_buffer(monkeypatch):
    calls = []

    class Fake:
        def windows_directory(self):
            return r"C:\Windows"

        def local_app_data(self):
            return r"C:\Users\Alice\AppData\Local", 123

        def directory_attributes(self, path):
            calls.append(("attributes", path))
            return 0x10

        def free(self, pointer):
            calls.append(("free", pointer))

    monkeypatch.setattr(launch, "_WindowsPathsApi", Fake)
    assert launch.discover_windows_paths() == WINDOWS
    assert calls == [("attributes", r"C:\Windows"),
                     ("attributes", r"C:\Users\Alice\AppData\Local"),
                     ("free", 123)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only directory discovery")
def test_actual_windows_discovery_is_read_only():
    paths = launch.discover_windows_paths()
    assert paths.system_root.is_dir()
    assert paths.local_app_data.is_dir()


def test_discovery_frees_known_folder_buffer_and_rejects_reparse(monkeypatch):
    calls = []

    class Fake:
        def windows_directory(self):
            return r"C:\Windows"

        def local_app_data(self):
            return r"C:\Users\Alice\AppData\Local", 123

        def directory_attributes(self, path):
            calls.append(("attributes", path))
            return 0x10 if "AppData" not in path else 0x410

        def free(self, pointer):
            calls.append(("free", pointer))

    monkeypatch.setattr(launch, "_WindowsPathsApi", Fake)
    with pytest.raises(ValueError):
        launch.discover_windows_paths()
    assert ("free", 123) in calls
    assert calls[-1] == ("free", 123)


def test_discovery_no_environment_fallback_and_api_error(monkeypatch):
    class Fake:
        def windows_directory(self):
            raise OSError("API failed")

    monkeypatch.setattr(launch, "_WindowsPathsApi", Fake)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    with pytest.raises(ValueError, match="windows_discovery"):
        launch.discover_windows_paths()
