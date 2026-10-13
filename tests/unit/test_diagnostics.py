import json
import zipfile

from src.core.diagnostics import DiagnosticsExporter


def test_preview_and_export_include_safe_metadata_only(tmp_path):
    exporter = DiagnosticsExporter(app_version="0.1.0", platform_name="Windows")
    preview = exporter.preview(
        components=[{"id": "local", "status": "ready"}],
        settings={"provider": "qwen", "api_key": "sk-secret", "source_dir": "C:/Users/alice/private"},
        logs=["Bearer token-value", "processed C:/Users/alice/report.pdf", "request_body=secret text"],
    )
    blob = json.dumps(preview, ensure_ascii=False).lower()
    assert "0.1.0" in blob and "windows" in blob and "local" in blob
    for forbidden in ("sk-secret", "token-value", "c:/users", "secret text", "api_key", "request_body"):
        assert forbidden not in blob

    target = tmp_path / "diagnostics.zip"
    exporter.export(target, preview)
    with zipfile.ZipFile(target) as package:
        assert package.namelist() == ["diagnostics.json"]
        exported = package.read("diagnostics.json").decode("utf-8").lower()
    assert "sk-secret" not in exported


def test_diagnostics_redacts_non_system_drive_and_unc_paths():
    preview = DiagnosticsExporter().preview(
        components=[],
        settings={
            "organization_root": r"D:\Private\Acquisition\Target",
            "source_dir": r"\\server\finance\deal.pdf",
        },
        logs=[r"processed E:\cases\client.pdf", r"opened \\server\secret\memo.pdf"],
    )
    text = json.dumps(preview, ensure_ascii=False).lower()
    for forbidden in ("d:\\private", "e:\\cases", "\\\\server", "deal.pdf", "client.pdf"):
        assert forbidden not in text


def test_exporter_never_includes_file_content_or_raw_requests():
    exporter = DiagnosticsExporter()
    preview = exporter.preview(
        components=[], settings={},
        logs=["FILE_CONTENT=confidential", "RAW_AI_REQUEST={private prompt}"],
    )
    text = json.dumps(preview).lower()
    assert "confidential" not in text
    assert "private prompt" not in text