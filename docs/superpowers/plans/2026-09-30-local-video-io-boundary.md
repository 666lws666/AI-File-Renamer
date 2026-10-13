# Local Video I/O Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Explicitly prevent additional file/network opens by the local video
decoder while preserving normal self-contained video input and frame selection.

**Architecture:** Supply the existing Python file-like input as before; deny
additional native protocols and reject every nested `io_open` callback. This is
an application input boundary, not a claim to sandbox arbitrary native exploits.

**Tech Stack:** Existing PyAV 18.0.0/FFmpeg and synthetic local pytest fixtures.

## Evidence and constraints

Root ran real PyAV on synthetic HLS text and a random-port loopback HTTP404
listener. The current product auto-detect path rejected this input without a
request. A forced-HLS diagnostic made one loopback request; either a rejecting
`io_open` or `protocol_whitelist=""` prevented it. Both guards together still
decoded a real frame of the existing synthetic MP4 (640x360). Thus there is no
proven current product leak from this fixture; this task makes the required local
I/O policy explicit instead of relying on this version's format auto-detection.
Ignored evidence: `decoder-io-576a85f1c22842acbd218cb8005fb1ef/result.json`.

Primary references checked 2026-09-30:

- [PyAV open API](https://pyav.basswood.io/docs/stable/api/_globals.html) documents
  custom I/O for additional streams. Installed18.0.0 `container/core.py` sets the
  native `io_open` callback whenever supplied.
- [FFmpeg protocol options](https://ffmpeg.org/ffmpeg-protocols.html#Protocol-Options)
  documents the protocol allowlist. Empty-list behavior above was also measured
  with the installed version, not assumed from a future documentation version.

- No remote media is supported here: user-selected video files and bounded bytes
  are the complete input. No source URL, reference movie, playlist, secondary
  local-file include, pipe or device access is allowed.
- Preserve 4/6/8-frame rules, timestamps, image quality, size/decode/deadline/
  cancellation bounds and existing child isolation. No prompt/model changes.
- No actual external API/credential/private input/system-security changes, QML,
  Golden updates, main checkout, merge or push. A synthetic loopback404 listener
  is permitted only in the focused proof and must always close in finally.

## Task 1: Explicit nested I/O denial

Files: modify `src/services/media/keyframe_extractor.py`; extend
`tests/unit/media/test_keyframe_extractor.py`; create
`tests/unit/media/test_video_io_boundary.py`. Check exact existing test path
before implementation; if its filename differs, use the existing corresponding
file and report that concrete path rather than creating a duplicate suite.

- [ ] RED: spy the real extractor's av.open call and assert it supplies both
  guards below; directly test fixed rejection without echoing URL/options.
- [ ] Implement only this boundary:

```python
def _deny_nested_io(url, flags, options):
    raise OSError("nested_video_io_denied")

# In the existing _extract open step:
container = av.open(source, mode="r", options={"protocol_whitelist": ""},
                    io_open=_deny_nested_io)
```

`source` remains the already-opened Python file/BytesIO; do not switch to a path
string or URL. Keep fixed MediaProcessingError normalization. Do not log callback
arguments or add a user-controlled protocol setting. Adapt test-fake signatures
only to accept/assert new kwargs; do not relax outcomes or frame assertions.

- [ ] Cover local file and bytes real MP4 extraction, 4/6/8 ordering, caller
  cancellation and timeout suites; no image/Golden difference is expected.
- [ ] A bounded real-backend synthetic HLS test demonstrates the supplied guard
  settings reject a nested loopback request. Include a narrowly scoped unguarded
  forced-HLS positive control to prove the listener is reachable; label it as a
  library diagnostic, not a reproduction of the product's auto-detect behavior.
  Callback rejection of a synthetic secondary file URL must return no content and
  must not open that file. Errors/log captures may not contain the synthetic
  private URL marker. Do not install global sockets/hooks or change the firewall.
- [ ] Run relevant media/deadline/native-media-contract tests with project Python,
  report raw RED/GREEN to `.superpowers/sdd/local-video-io-boundary-report.md`,
  diff check and scoped commit. Root separately reviews actual keyframe contact
  evidence if a rendered output changes; no autonomous Golden update.
