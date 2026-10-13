from datetime import datetime, timezone

from src.controllers.status_controller import ComponentStatus, StatusController, StatusLevel


def _component(cid, status):
    return ComponentStatus(cid, cid, status, "detail", datetime.now(timezone.utc).isoformat())


def test_all_components_ready_and_cached_with_ttl():
    calls = {"n": 0}
    def probe():
        calls["n"] += 1
        return _component("local", StatusLevel.READY)
    controller = StatusController({"local": probe}, clock=lambda: 10.0, ttl_seconds=60)
    assert controller.check_all().overall is StatusLevel.READY
    assert controller.check_all().overall is StatusLevel.READY
    assert calls["n"] == 1


def test_failed_component_and_split_text_vision_capability():
    controller = StatusController({
        "local": lambda: _component("local", StatusLevel.READY),
        "text_ai": lambda: _component("text_ai", StatusLevel.READY),
        "vision_ai": lambda: _component("vision_ai", StatusLevel.UNAVAILABLE),
    })
    result = controller.check_all(force=True)
    assert result.overall is StatusLevel.ATTENTION
    rows = {row.id: row for row in result.components}
    assert rows["text_ai"].status is StatusLevel.READY
    assert rows["vision_ai"].status is StatusLevel.UNAVAILABLE


def test_all_unavailable_and_probe_exception_are_sanitized():
    def broken():
        raise RuntimeError("secret path C:/Users/person/file.txt")
    controller = StatusController({"provider": broken})
    result = controller.check_all(force=True)
    assert result.overall is StatusLevel.UNAVAILABLE
    assert result.components[0].status is StatusLevel.UNAVAILABLE
    assert "C:/Users" not in result.components[0].detail


def test_qml_properties_expose_component_rows():
    controller = StatusController({"local": lambda: _component("local", StatusLevel.READY)})
    controller.checkAll()
    assert controller.overall == "ready"
    assert controller.components[0]["id"] == "local"