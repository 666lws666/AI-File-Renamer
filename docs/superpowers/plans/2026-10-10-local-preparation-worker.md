# Hard-cancellable local preparation worker

The approved local privacy delivery requires a finite cancellation/deadline
boundary around third-party parsers. The current extraction and media checkpoints
cannot interrupt a native call. The older media track's nested image "child" is
not an operating-system process. This small prerequisite precedes Task B.

## Exact ownership

New product modules under src/services/local_ai: preparation_protocol.py,
preparation_service.py, preparation_worker.py. Narrow existing changes only to
native/process.py (stdout configurable upper bound and stale description) and
src/main.py (early fixed worker entry before Qt import). New focused protocol,
service and real-worker tests plus a test-only worker fixture. Do not modify
content_extractor, three media kernels, model security/launch/staging, Task B,
controllers, QML, packaging, Golden or main checkout in this task.

## Public contract

BoundedLocalPreparationService.prepare(source_path, *, limits, quality_mode,
deadline, cancelled) returns a frozen path-free LocalPreparationResult containing
actual bounded text, prepared visuals, immutable coverage and warning codes. The
source path, text and image bytes have repr suppression. Limits are a validated
frozen whitelist, not arbitrary configuration or serialized callbacks.

- Entire admission-time monotonic deadline is shared with later model work;
  preparation also has a finite own timeout. Queue and cleanup consume the budget.
- One worker at a time, bounded waiting and cancellable admission. A retained
  native owner blocks another launch until confirmed cleanup.
- retry_cleanup(deadline) and close(deadline) never discard a pending owner.
- No model, credentials, Provider, HTTP transport or source copy is constructed.
- Task B explicitly injects this service and may not default to in-process local
  parsing when it is missing.

## Source and result boundary

A fixed request version contains one local source path, enum choices and bounded
limits. Reject URLs, UNC, device and remote-drive paths; do not promise pathname
confidentiality from another process running as the same user. No arbitrary
entrypoint, executable, imports, environment, flags, pickle or request code.

Encode at most 12 KiB strict UTF-8 request JSON as base64url in the private command
argument. The runner's stdin is EOF from the first instruction; do not implement
an incompatible stdin protocol or private temporary result files.

The stdout frame has fixed magic/version/lengths, a strict JSON header <=64 KiB,
text <=32,768 UTF-8 bytes and <=8 prepared image segments totaling <=16 MiB. Reject
duplicate keys, nonfinite numbers, invalid lengths, unknown fields, trailing bytes,
invalid media/signatures/digests and malformed coverage. The parent performs no
second image/PDF/video decode. Return no arbitrary metadata/FileItem/exception.

The runner's existing 16 MiB output configuration bound cannot fit that maximum
payload plus framing. Permit stdout only up to 17 MiB; retain stderr's 16 MiB
configuration bound and both existing defaults. This service requests 17 MiB
stdout and 64 KiB stderr. Overflow or nonzero exit is failure; raw stderr remains
private and is not used as a public error message.

## Worker composition

The child calls reviewed extraction with redacted_diagnostics=True for documents.
Images/video go directly to their prepared visual kernels; no basename metadata
placeholder becomes evidence. PDF extraction and necessary bounded scan rendering
happen in this same child. Quality and page/frame/image-byte limits apply before
generation. Report actual extraction coverage, selected page indices and video
timestamps/omitted limits; never say all pages were understood from a prefix.

Text-only content is preserved within the UTF-8 byte bound. If mixed evidence
requires the existing 64-span limit, Task B supplies truthful coverage instead of
weakening the naming validator. No generic content prompt is synthesized here.

## Trusted entry and process lifetime

Source launch uses the verified active interpreter and a fixed -I -c bootstrap
that inserts only the known application root and imports the fixed worker module;
no inherited PYTHONPATH/proxy/key/model-cache environment is used. Frozen launch
uses the program itself with the sole --local-preparation-worker-v1 entry. Dispatch
before importing main_qml/Qt. console=False means the worker writes the binary
frame through its inherited Windows stdout HANDLE, not print/sys.stdout.buffer.

Reuse run_bounded's creation-time Job, suspend/membership confirmation, finite
output capture and exact owner cleanup. A small .is_set cancellation adapter
latches cancellation and predicate failures; no background bridging thread.
Reserve cleanup time before launch. On uncertain cleanup or interrupted ownership,
retain the actual owner and suppress success. No arbitrary PID reopening/killing.

Job controls lifetime, not network or filesystem permissions. Retain the actual
PyAV nested-I/O guards. Do not claim parser exploit sandboxing or infer model
AppContainer guarantees for this current-user trusted preparation worker.

## Verification and deferred packaged Gate

Use TDD protocol, cancellation/queue, private diagnostics, partial/native cleanup
and exact output-bound tests. Real synthetic Windows children must prove hard
timeout/cancellation of an uncooperative wait and owned descendants, and prove
source-mode image/scan PDF/video processing, not mocked parser coverage.

The production worker has no hang or arbitrary executable switch; the injected
diagnostic seam and hanging fixture belong only to tests. Preserve the existing
source HEAD-blob guard. No full-suite exclusions or Golden update. Root independently
reviews and commits the exact task, then reruns the complete regression.

Frozen GUI worker execution is required later in the packaging Gate, with actual
PIL/PyMuPDF/PyAV and Office dependencies collected. It is explicitly pending until
the new application is built; a source-mode test does not certify frozen behavior.
