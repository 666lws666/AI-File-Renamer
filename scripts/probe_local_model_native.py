"""Bounded diagnostic checks. This is not a production local-mode launcher."""
from __future__ import annotations

import hashlib
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

PROBE_FREE_MEMORY_BYTES = 5 * 1024**3  # test safety margin, not product minimum


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_probe_memory(available_bytes):
    if type(available_bytes) is not int or available_bytes < 0:
        raise ValueError('Invalid available memory measurement')
    if available_bytes < PROBE_FREE_MEMORY_BYTES:
        raise RuntimeError('MEMORY_BLOCKED: native inference has not run')


def extract_verified_runtime(archive, expected_sha256, destination):
    archive, destination = Path(archive), Path(destination)
    if sha256(archive) != expected_sha256:
        raise ValueError('Runtime archive hash mismatch')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Existing runtime is never overwritten')
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if not members or len(members) > 512 or sum(x.file_size for x in members) > 512 * 1024**2:
            raise ValueError('Runtime archive bounds exceeded')
        seen = set()
        for member in members:
            name = member.filename
            if (not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', name)
                    or name.endswith(('.', ' ')) or name.casefold() in seen
                    or member.is_dir() or stat.S_ISLNK(member.external_attr >> 16)
                    or member.file_size > 256 * 1024**2):
                raise ValueError('Unsafe runtime archive member')
            seen.add(name.casefold())
        if 'llama-cli.exe' not in seen:
            raise ValueError('Required native runtime executable is absent')
        if bundle.testzip() is not None:
            raise ValueError('Runtime archive CRC failure')
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='runtime-verified-', dir=destination.parent))
        # A failed extraction leaves only an ignored diagnostic staging folder;
        # it never publishes or recursively deletes caller-owned directories.
        for member in members:
            with bundle.open(member) as source, (stage / member.filename).open('xb') as target:
                shutil.copyfileobj(source, target, 1024**2)
        stage.rename(destination)
    return destination


def run_runtime_smoke(executable, expected_sha256, *, runner=subprocess.run):
    executable = Path(executable)
    if sha256(executable) != expected_sha256:
        raise ValueError('Runtime executable hash mismatch')
    # No inherited model URL, proxy, RPC or user configuration. --version does
    # not load weights or make an inference; this does not prove sandboxing.
    environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    environment['PATH'] = os.pathsep.join((str(executable.parent), str(Path(system_root) / 'System32')))
    result = runner([str(executable), '--version'], shell=False, timeout=10,
                    capture_output=True, env=environment, cwd=executable.parent,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode != 0:
        raise RuntimeError('Native runtime version probe failed')
    output = result.stdout + result.stderr
    if len(output) > 65536:
        raise RuntimeError('Native version output exceeds diagnostic limit')
    return output.decode('utf-8', errors='replace').strip()


def probe_status(*, available_bytes: int, runtime_version: str = '') -> dict:
    try:
        check_probe_memory(available_bytes)
        state = 'READY_FOR_INFERENCE_EXPERIMENT'
    except RuntimeError:
        state = 'MEMORY_BLOCKED'
    return {'state': state, 'available_memory_bytes': available_bytes,
            'test_safety_margin_bytes': PROBE_FREE_MEMORY_BYTES,
            'runtime_version': runtime_version, 'actual_inference_run': False,
            'semantic_quality_verified': False, 'outbound_isolation_verified': False}


def windows_available_memory() -> int:
    if os.name != 'nt':
        raise RuntimeError('Native Windows measurement required')
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (key, ctypes.c_uint64) for key in ('total', 'available', 'page_total',
                'page_available', 'virtual_total', 'virtual_available', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError('Cannot measure native available memory')
    return int(status.available)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-smoke', action='store_true', help='Verify pinned archive and run --version only; never loads model')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'tests/screenshots/qa-current/local-privacy'
    version = ''
    if args.runtime_smoke:
        manifest = json.loads((root / 'resources/local-models/qwen35-4b-feasibility.json').read_text('utf-8'))
        resource = next(x for x in manifest['resources'] if x['id'] == 'runtime-cpu')
        archive = output / 'resources' / resource['filename']
        if not archive.is_file() or archive.stat().st_size != resource['bytes'] or sha256(archive) != resource['sha256']:
            raise ValueError('Verified pinned runtime archive is unavailable')
        destination = output / 'runtime-b10885'
        if not destination.exists():
            extract_verified_runtime(archive, resource['sha256'], destination)
        # Recheck every extracted member, including DLL dependencies, before
        # the no-model version probe. Never execute an arbitrary PATH runtime.
        with zipfile.ZipFile(archive) as bundle:
            expected_names = {item.filename for item in bundle.infolist()}
            if {item.name for item in destination.iterdir()} != expected_names:
                raise ValueError('Runtime directory differs from verified archive')
            for member in bundle.infolist():
                target = destination / member.filename
                if target.is_symlink() or not target.is_file() or sha256(target) != hashlib.sha256(bundle.read(member)).hexdigest():
                    raise ValueError('Extracted runtime hash mismatch')
            exe_hash = hashlib.sha256(bundle.read('llama-cli.exe')).hexdigest()
        version = run_runtime_smoke(destination / 'llama-cli.exe', exe_hash)
    result = probe_status(available_bytes=windows_available_memory(), runtime_version=version)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'native-preflight.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 3 if result['state'] == 'MEMORY_BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
