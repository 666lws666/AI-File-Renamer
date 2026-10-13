"""Source collection gate; never substitutes an old EXE for current inputs."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def collected_data():
    source = (ROOT / "packaging/xuxia.spec").read_text(encoding="utf-8")
    namespace = {"SPEC": str(ROOT / "packaging/xuxia.spec")}
    exec(compile(source.split("\na = Analysis(", 1)[0], "xuxia.spec", "exec"), namespace)
    result = []
    for src, dst in namespace['datas']:
        path = Path(src)
        # PyInstaller accepts directory-valued datas (copy_metadata returns one).
        if path.is_dir():
            result.extend((p, (Path(dst) / p.relative_to(path).parent).as_posix())
                          for p in path.rglob('*') if p.is_file())
        else:
            result.append((path, Path(dst).as_posix()))
    return result


def test_bundle_contains_only_pinned_product_local_inputs():
    entries = collected_data()
    actual = {(p.relative_to(ROOT).as_posix(), dst) for p, dst in entries if p.is_relative_to(ROOT / "resources/local-models")}
    expected = {
        ("resources/local-models/qwen35-4b-managed-v1.json", "resources/local-models"),
        ("resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip", "resources/local-models/runtime"),
        *(('resources/local-models/licenses/' + name, 'resources/local-models/licenses') for name in
          ('Qwen3.5-4B-LICENSE.txt', 'llama.cpp-LICENSE.txt', 'SOURCES.md', 'OpenCC-SOURCES.md')),
    }
    assert actual == expected
    assert all(p.is_file() for p, _ in entries)
    assert not any(p.suffix.lower() == '.gguf' for p, _ in entries)


def test_bundled_runtime_pin_and_embedded_openmp_notice():
    import zipfile
    path = ROOT / 'resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip'
    assert path.stat().st_size == 18425079
    assert hashlib.sha256(path.read_bytes()).hexdigest() == 'b96fd3b2dfa7add41b0d80f93599931d839b54b4b804abc4b295bd4039dc96f1'
    with zipfile.ZipFile(path) as archive:
        assert any(Path(name).name == 'LICENSE-LLVM-OpenMP' for name in archive.namelist())


def test_opencc_collected_configs_dictionaries_original_metadata_license():
    entries = collected_data()
    names = {dst + '/' + p.name for p, dst in entries}
    assert {'opencc/config/s2hk.json', 'opencc/config/t2s.json'} <= names
    assert any(name.startswith('opencc/dictionary/') and name.endswith('.txt') for name in names)
    assert any(name.endswith('.dist-info/METADATA') for name in names)
    license_files = [p for p, dst in entries if dst.endswith('.dist-info') and p.name == 'LICENSE.txt']
    assert len(license_files) == 1
    assert 'Apache License' in license_files[0].read_text(encoding='utf-8')
    metadata = [p for p, dst in entries if dst.endswith('.dist-info') and p.name == 'METADATA']
    assert len(metadata) == 1
    assert '\nVersion: 0.1.7\n' in metadata[0].read_text(encoding='utf-8')
    assert 'opencc-python-reimplemented==0.1.7' in (ROOT / 'requirements.txt').read_text(encoding='utf-8')


def test_product_loader_uses_meipass_independently_of_cwd(tmp_path, monkeypatch):
    import shutil
    import sys
    from src.services.local_ai.production_resources import load_production_resources, PRODUCT_CATALOG_ID
    bundle = tmp_path / 'bundle'
    catalog_dir = bundle / 'resources/local-models'
    catalog_dir.mkdir(parents=True)
    shutil.copyfile(ROOT / 'resources/local-models/qwen35-4b-managed-v1.json',
                    catalog_dir / 'qwen35-4b-managed-v1.json')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.chdir(tmp_path)
    product = load_production_resources(user_data_root=tmp_path / 'isolated')
    assert product.catalog.identity == PRODUCT_CATALOG_ID
    assert product.bundled_runtime == catalog_dir / 'runtime/llama-b10885-bin-win-cpu-x64.zip'
    assert not product.resource_root.exists()  # loader remains inert
