# Cloud processing dispatch integration plan

> **For agentic workers:** Use subagent-driven-development for implementation and
> independent task review. The Product Owner has authorized execution continuously.

**Goal:** Every cloud naming attempt and fixed connection probe obeys the shared
processing authority at the last concrete HTTP submission boundary.

**Architecture:** Carry one immutable dispatch context into the adapter and each
transport attempt. The concrete urllib transport obtains and consumes a one-use
commitment after body serialization and immediately before its private opener.
Retry waiting observes generation cancellation and cannot republish old results.

**Tech stack:** Existing urllib transport, ProcessingAuthority, RetryExecutor,
threading Events and deterministic fake-opener tests. No HTTP client dependency.

## Global constraints

- Selecting LOCAL before commitment means zero opener calls. A precommitted
  attempt may still transmit/finish; the authority mutex must never span the opener.
- No queue/semaphore/wait/serialization/caller callback between commitment and
  opener. Keep redirects disabled. Each retry needs its own commitment.
- Generation/task cancellation denies later attempts and suppresses old success.
- No automatic local-to-cloud fallback, real API, key, Credential Manager,
  private fixture, model launch, QML, Golden update, main-checkout write or push.
- Errors and provenance contain fixed safe codes, not request content or keys.
- Preserve unguarded constructor signatures for existing unit-only uses. The
  later production composition must always inject the shared dispatch contract;
  absence of production wiring is not a completed feature.

## Task 1: Concrete transport and retry integration

Files:
- Modify `src/providers/openai_compatible.py`.
- Modify `src/services/retry_policy.py`.
- Create `tests/providers/contracts/test_processing_dispatch.py`.
- Extend `tests/unit/services/test_retry_policy.py` only for actual wait behavior.

Interfaces:

```python
@dataclass(frozen=True)
class ProcessingDispatch:
    authority: ProcessingAuthority = field(repr=False)
    context: WorkContext = field(repr=False)

# JsonTransport and UrllibJsonTransport.send gain keyword-only
# dispatch_context: ProcessingDispatch | None = None.
# OpenAICompatibleAdapter.__init__ gains keyword-only
# processing_dispatch: ProcessingDispatch | None = None.
# One adapter remains bound to one immutable context; never mutate it per call.
```

An injected guarded transport accepts the dispatch argument and implements the
same preparation/commit/opener order. A guarded adapter must not silently drop
the keyword or retry through an old unguarded transport. Unguarded legacy tests
retain their existing send signature when no dispatch is supplied. Production
injection will be done by the shared analysis/runtime task, not hidden here.

- [ ] Write a failing real-authority/fake-opener test where JSON preparation
  selects LOCAL before the transport commit; assert opener_count == 0 and
  snapshot.committed_attempts == 0.
- [ ] Write the inverse controlled race: a fake opener blocks on an Event after
  commitment; selecting LOCAL completes before release; one opener may finish,
  but adapter result is cancelled/stale and no retry is submitted.
- [ ] Implement commitment inside `UrllibJsonTransport.send`, after Request
  construction. Use a unique attempt ID per concrete call. Finish the exact
  receipt in finally on HTTP/read/parser/timeout/ordinary exception paths. No
  authority lock remains held while any network callback executes.
- [ ] Preserve ProcessingSuperseded/CloudDispatchBlocked through adapter exception
  sanitization and classify them as non-retryable CANCELLED before generic errors.
- [ ] Combine dispatch currentness with existing cancellation outside the authority
  lock. Check cancellation after a successful operation and retain factual usage
  records while discarding its value. A completed response is not permission to
  publish in a superseded generation.
- [ ] Make backoff cancellation-aware. When a generation Event is provided, wait
  through Event.wait with bounded slices for a separate caller cancellation
  callback. Retain deterministic injected wait/sleeper support; no scheduling
  sleeps in race tests. A blocked opener cannot be killed by this abstraction.
- [ ] Exercise retry after 429/timeout, generation switch during backoff, malformed
  response, opener failure, duplicate receipt protection and token-free repr/errors.
- [ ] Exercise fixed invoke_probe through the same gate: it never authorizes a
  business call or carries document/image/path fields. LOCAL blocks that probe;
  independently consented public model downloads are outside this transport.
- [ ] Verify redirects remain disabled; one commitment cannot cover another
  redirect, additional queued send or reused retry attempt.

Behavioral test core:

```python
authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
authority.bind_cloud_engine("a" * 64)
work = authority.capture_work(engine_fingerprint="a" * 64, task_attempt_id="batch-1")
dispatch = ProcessingDispatch(authority, work)
# Real Request creation occurs in UrllibJsonTransport; only _open is injected.
# Controlled preparation then select_local -> no opener.
# Controlled entered opener then select_local -> exactly one old call; no result.
```

Test command (project Windows interpreter):

```text
python -m pytest tests/providers/contracts/test_processing_dispatch.py tests/unit/services/test_retry_policy.py tests/providers/contracts -q
```

Record actual RED/GREEN and file list in
`.superpowers/sdd/processing-transport-report.md`. Parent owns index/commit and
independent review. Do not change connection-test classification or provider
presets unless this exact dispatch boundary exposes a necessary incompatibility.
