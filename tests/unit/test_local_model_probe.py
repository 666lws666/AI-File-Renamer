"""Safe feasibility checks, not mock semantic acceptance."""
import hashlib
import importlib
import importlib.util
import io
from pathlib import Path
import zipfile
import subprocess

import pytest


@pytest.fixture
def probe():
    assert importlib.util.find_spec('scripts.probe_local_model_native'), 'native probe not implemented'
    return importlib.import_module('scripts.probe_local_model_native')


def test_low_memory_blocks_load(probe):
    with pytest.raises(RuntimeError, match='MEMORY_BLOCKED'):
        probe.check_probe_memory(1024**3)


def test_memory_boundary_is_explicit_test_margin(probe):
    probe.check_probe_memory(5 * 1024**3)
    with pytest.raises(RuntimeError):
        probe.check_probe_memory(5 * 1024**3 - 1)


def test_invalid_memory_is_not_accepted(probe):
    for value in (-1, True, 7.0, None):
        with pytest.raises((ValueError, TypeError)):
            probe.check_probe_memory(value)


def archive(tmp_path, names):
    path = tmp_path / 'runtime.zip'
    with zipfile.ZipFile(path, 'w') as out:
        for name in names:
            out.writestr(name, b'synthetic-binary')
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_archive_hash_mismatch_has_no_output(probe, tmp_path):
    path, _ = archive(tmp_path, ['llama-cli.exe'])
    with pytest.raises(ValueError, match='hash'):
        probe.extract_verified_runtime(path, '0' * 64, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('name', ['../escape.exe', '/absolute.exe', 'C:/bad.exe', 'sub/a.dll', 'bad\\x.dll'])
def test_archive_paths_fail_before_extract(probe, tmp_path, name):
    path, sha = archive(tmp_path, ['llama-cli.exe', name])
    with pytest.raises(ValueError):
        probe.extract_verified_runtime(path, sha, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_verified_archive_extracts_without_execution(probe, tmp_path):
    path, sha = archive(tmp_path, ['llama-cli.exe', 'llama.dll'])
    result = probe.extract_verified_runtime(path, sha, tmp_path / 'out')
    assert result == tmp_path / 'out'
    assert (result / 'llama-cli.exe').read_bytes() == b'synthetic-binary'


def test_existing_runtime_is_not_overwritten(probe, tmp_path):
    path, sha = archive(tmp_path, ['llama-cli.exe'])
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'keep').write_bytes(b'old')
    with pytest.raises(FileExistsError):
        probe.extract_verified_runtime(path, sha, tmp_path / 'out')
    assert (tmp_path / 'out' / 'keep').read_bytes() == b'old'


def test_bad_executable_hash_never_starts_process(probe, tmp_path):
    exe = tmp_path / 'llama-cli.exe'
    exe.write_bytes(b'changed')
    called = []
    with pytest.raises(ValueError, match='hash'):
        probe.run_runtime_smoke(exe, '0' * 64, runner=lambda *a, **kw: called.append(a))
    assert called == []


def test_smoke_is_no_model_version_only_and_sanitized(probe, tmp_path, monkeypatch):
    exe = tmp_path / 'llama-cli.exe'
    exe.write_bytes(b'test')
    monkeypatch.setenv('LLAMA_ARG_MODEL_URL', 'https://must-not-inherit.invalid')
    monkeypatch.setenv('HTTPS_PROXY', 'https://must-not-inherit.invalid')
    def runner(command, **kwargs):
        assert command == [str(exe), '--version']
        assert kwargs['shell'] is False and kwargs['timeout'] == 10
        assert 'LLAMA_ARG_MODEL_URL' not in kwargs['env']
        assert 'HTTPS_PROXY' not in kwargs['env']
        class Result:
            returncode = 0
            stdout = b'version: b10885'
            stderr = b''
        return Result()
    output = probe.run_runtime_smoke(exe, hashlib.sha256(b'test').hexdigest(), runner=runner)
    assert 'b10885' in output


def test_version_timeout_is_not_reported_as_success(probe, tmp_path):
    exe = tmp_path / 'llama-cli.exe'
    exe.write_bytes(b'test')
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    with pytest.raises(subprocess.TimeoutExpired):
        probe.run_runtime_smoke(exe, hashlib.sha256(b'test').hexdigest(), runner=runner)


def test_probe_cli_reports_memory_block_without_inference(probe, tmp_path):
    assert hasattr(probe, 'probe_status'), 'missing explicit non-inference status'
    result = probe.probe_status(available_bytes=1024**3, runtime_version='b10885')
    assert result['state'] == 'MEMORY_BLOCKED'
    assert result['actual_inference_run'] is False
    assert result['semantic_quality_verified'] is False
    assert result['runtime_version'] == 'b10885'


def test_memory_ready_does_not_claim_model_or_privacy_pass(probe):
    assert hasattr(probe, 'probe_status'), 'missing explicit non-inference status'
    result = probe.probe_status(available_bytes=8 * 1024**3, runtime_version='b10885')
    assert result['state'] == 'READY_FOR_INFERENCE_EXPERIMENT'
    assert result['actual_inference_run'] is False
    assert result['outbound_isolation_verified'] is False
