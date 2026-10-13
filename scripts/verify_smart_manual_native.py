"""Offline browser render/interaction checks for the three complete HTML manuals."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/screenshots/qa-current/smart-manual"
PAGES = {"zh-CN": ROOT / "序匣用户手册.html",
         "zh-HK": ROOT / "user-guide-assets/manual-zh-HK.html",
         "en-US": ROOT / "user-guide-assets/manual-en-US.html"}

class LocalOnly(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent):
        super().__init__(parent)
        self.blocked = []
    def interceptRequest(self, info):
        if info.requestUrl().scheme() not in {"file", "qrc", "data", "about"}:
            self.blocked.append(info.requestUrl().scheme())
            info.block(True)

class Page(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.errors = []
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append(message)

def js(page, expression):
    loop = QEventLoop()
    values = []
    def receive(value):
        values.append(value)
        loop.quit()
    page.runJavaScript(expression, receive)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    assert values, "JavaScript evaluation timed out"
    return values[0]

def load(view, path):
    loop, result = QEventLoop(), []
    def done(ok):
        result.append(ok); loop.quit()
    view.loadFinished.connect(done)
    view.load(QUrl.fromLocalFile(str(path)))
    timer = QTimer()
    timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(10000)
    loop.exec(); view.loadFinished.disconnect(done)
    assert result == [True], (path.name, result)
    js(view.page(), "document.querySelectorAll('img').forEach(x => x.loading='eager')")
    QTest.qWait(300)

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    assert app.platformName() == "windows"
    OUT.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile(app)  # off-the-record, no real browser profile
    blocker = LocalOnly(profile)
    profile.setUrlRequestInterceptor(blocker)
    view = QWebEngineView()
    page = Page(profile, view); view.setPage(page)
    rows = []
    for locale, path in PAGES.items():
        for width in (1000, 390):
            view.resize(width, 760); view.show()
            load(view, path)
            assert js(page, "document.documentElement.lang") == locale
            info = json.loads(js(page, """JSON.stringify({
                width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                images: [...document.images].map(i => ({loaded:i.complete && i.naturalWidth>0})),
                chapters: document.querySelectorAll('section.chapter').length
            })"""))
            assert info["scrollWidth"] <= info["width"] + 1, (locale, width, info)
            assert len(info["images"]) == 12 and all(x["loaded"] for x in info["images"])
            assert info["chapters"] == 17
            assert view.grab().save(str(OUT / f"{locale}-{width}-top.png"))
            if width == 1000:
                link = json.loads(js(page, """JSON.stringify((() => {
                    const a=document.querySelector('.language-switch a:not([aria-current="page"])');
                    const r=a.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,href:a.href};
                })())"""))
                QTest.mouseClick(view.focusProxy() or view, Qt.LeftButton, Qt.NoModifier,
                                 QPoint(round(link["x"]), round(link["y"])))
                QTest.qWait(500)
                assert page.url() == QUrl(link["href"]), (page.url().toString(), link)
                load(view, path)
            js(page, "document.documentElement.style.scrollBehavior='auto'; window.scrollTo(0, window.scrollY + document.getElementById('batch').getBoundingClientRect().top)")
            QTest.qWait(500)
            chapter_top = js(page, "document.getElementById('batch').getBoundingClientRect().top")
            assert abs(chapter_top) <= 2, (locale, width, "batch chapter not visible", chapter_top)
            assert view.grab().save(str(OUT / f"{locale}-{width}-smart.png"))
            rows.append({"locale": locale, "width": width, "images_loaded": 12,
                         "chapters": 17, "horizontal_overflow": False,
                         "native_language_click": width == 1000})
    assert not blocker.blocked, blocker.blocked
    assert not page.errors, page.errors
    (OUT / "manifest.json").write_text(json.dumps({"cases": rows, "network_requests": 0,
        "console_errors": page.errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"browser_cases": len(rows), "screenshots": len(rows)*2,
                      "network_requests": 0, "console_errors": 0}))
    view.close()
    page.deleteLater()
    QTest.qWait(100)

if __name__ == "__main__":
    main()
