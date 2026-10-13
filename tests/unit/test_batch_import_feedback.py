from PySide6.QtTest import QSignalSpy

from src.controllers.batch_workspace_controller import BatchWorkspaceController


def test_import_reports_added_duplicate_unsupported_and_missing(tmp_path):
    ctrl = BatchWorkspaceController(background=False)
    signal = QSignalSpy(ctrl.importCompleted)
    good = tmp_path / "report.txt"
    good.write_text("hello")
    unsupported = tmp_path / "archive.zip"
    unsupported.write_bytes(b"not a supported document")
    ctrl.add_files([str(good), str(good), str(unsupported), str(tmp_path / "missing.txt")])
    assert ctrl.totalCount == 1
    assert signal.count() == 1
    assert signal.at(0) == [1, 1, 1, 1]


def test_all_skipped_still_reports_result(tmp_path):
    ctrl = BatchWorkspaceController(background=False)
    signal = QSignalSpy(ctrl.importCompleted)
    ctrl.add_files([str(tmp_path / "missing.txt")])
    assert signal.count() == 1
    assert signal.at(0) == [0, 0, 0, 1]


def test_drop_multiple_folders_reports_one_combined_result(tmp_path):
    ctrl = BatchWorkspaceController(background=False)
    signal = QSignalSpy(ctrl.importCompleted)
    folders = [tmp_path / "a", tmp_path / "b"]
    for folder in folders:
        folder.mkdir()
        (folder / "file.txt").write_text("hello")
    ctrl.importDropped([str(folder) for folder in folders])
    assert ctrl.totalCount == 2
    assert signal.count() == 1
    assert signal.at(0) == [2, 0, 0, 0]


def test_failed_metadata_read_does_not_lose_other_imports(tmp_path, monkeypatch):
    import src.controllers.batch_workspace_controller as module
    ctrl = BatchWorkspaceController(background=False)
    signal = QSignalSpy(ctrl.importCompleted)
    bad, good = tmp_path / "locked.txt", tmp_path / "good.txt"
    bad.write_text("x")
    good.write_text("x")
    stat = module.os.stat
    def fail_bad(path, *args, **kwargs):
        if str(path) == str(bad):
            raise PermissionError("denied")
        return stat(path, *args, **kwargs)
    monkeypatch.setattr(module.os, "stat", fail_bad)
    ctrl.add_files([str(bad), str(good)])
    assert ctrl.totalCount == 1
    assert signal.at(0) == [1, 0, 0, 1]
