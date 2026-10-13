"""Real authority and concrete transport, with no network or scheduling sleeps."""
import json
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
from io import BytesIO
from threading import Event, Thread
from urllib.error import HTTPError

import pytest

from src.core.processing_authority import (
    CloudDispatchBlocked, LocalReadiness, ProcessingAuthority, ProcessingMode,
    ProcessingStateError, ProcessingSuperseded,
)
from src.core.processing_identity import cloud_engine_fingerprint
from src.providers import openai_compatible as provider
from src.services.retry_policy import ErrorCategory, RetryExecutor, RetryPolicy
from tests.providers.contracts.contract_suite import request, verified_custom_profile


class Response(BytesIO):
    def __init__(self, raw=None, *, status=200, headers=None):
        if raw is None:
            raw = json.dumps({
                "choices": [{"message": {"content": '{"dcTitle":"ok","dcType":"report"}'},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }).encode()
        super().__init__(raw)
        self.status = status
        self.headers = headers or {}


def dispatch(*, task_cancel_event=None):
    assert hasattr(provider, "ProcessingDispatch"), "immutable dispatch contract is missing"
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    authority.bind_cloud_engine("a" * 64)
    context = authority.capture_work(engine_fingerprint="a" * 64,
                                     task_attempt_id="synthetic-batch",
                                     task_cancel_event=task_cancel_event)
    return provider.ProcessingDispatch(authority, context)


def adapter_for(bound, opener, *, retries=2, retry_executor=None, profile=None):
    return provider.OpenAICompatibleAdapter(
        profile=profile or verified_custom_profile(), credential="synthetic-not-a-key",
        processing_dispatch=bound,
        transport=provider.UrllibJsonTransport(opener=opener),
        retry_executor=retry_executor or RetryExecutor(
            RetryPolicy(max_retries=retries, base_delay=0)),
    )


def send(transport, bound):
    return transport.send(url="https://provider.example.test/v1/chat/completions",
                          headers={}, json_body={"model": "synthetic"}, timeout=1,
                          dispatch_context=bound)


def assert_cancelled(result):
    assert not result.success
    assert result.cancelled
    assert result.value is None
    assert result.final_category is ErrorCategory.CANCELLED


@pytest.mark.parametrize("probe", [False, True])
def test_local_during_json_preparation_denies_final_opener(monkeypatch, probe):
    bound = dispatch()
    calls = []
    adapter = adapter_for(bound, lambda *a, **k: calls.append(a))
    dumps = provider.json.dumps

    def prepare(value, **kwargs):
        encoded = dumps(value, **kwargs)
        # This is the final wire body, not the adapter's nested user message.
        if "messages" in value:
            bound.authority.select_local()
        return encoded

    monkeypatch.setattr(provider.json, "dumps", prepare)
    result = adapter.invoke_probe() if probe else adapter.invoke(request())
    assert_cancelled(result)
    assert isinstance(result.final_error, CloudDispatchBlocked)
    assert calls == []
    assert bound.authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("probe", [False, True])
def test_committed_opener_does_not_hold_authority_lock_and_old_success_is_discarded(probe):
    bound = dispatch()
    entered, release, transitioned = Event(), Event(), Event()
    calls, results = [], []

    def opener(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return Response()

    adapter = adapter_for(bound, opener)
    worker = Thread(target=lambda: results.append(
        adapter.invoke_probe() if probe else adapter.invoke(request())), daemon=True)
    worker.start()
    switcher = None
    try:
        assert entered.wait(5)
        assert bound.authority.snapshot().committed_attempts == 1

        def switch():
            bound.authority.select_local()
            transitioned.set()

        switcher = Thread(target=switch, daemon=True)
        switcher.start()
        assert transitioned.wait(5), "LOCAL must complete while opener is blocked"
    finally:
        release.set()
        worker.join(5)
        if switcher is not None:
            switcher.join(5)
    assert not worker.is_alive()
    assert len(calls) == 1
    assert_cancelled(results[0])
    assert results[0].attempts[0].success
    assert results[0].attempts[0].usage == {"prompt_tokens": 3, "completion_tokens": 2}
    assert bound.authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("failure,category", [
    ("429", ErrorCategory.RATE_LIMIT), ("timeout", ErrorCategory.TIMEOUT),
    ("malformed", ErrorCategory.MALFORMED_RESPONSE),
    ("network", ErrorCategory.NETWORK),
])
def test_each_retry_has_a_unique_receipt_consumed_before_next_open(monkeypatch, failure, category):
    bound = dispatch()
    receipts, ids, calls = [], [], []
    commit = bound.authority.commit_cloud_attempt

    def record_commit(context, attempt_id):
        assert bound.authority.snapshot().committed_attempts == 0
        receipt = commit(context, attempt_id)
        receipts.append(receipt)
        ids.append(attempt_id)
        return receipt

    monkeypatch.setattr(bound.authority, "commit_cloud_attempt", record_commit)

    def opener(*args, **kwargs):
        calls.append(args)
        assert bound.authority.snapshot().committed_attempts == 1
        if len(calls) == 1:
            if failure == "429":
                raise HTTPError(args[0].full_url, 429, "synthetic", {"Retry-After": "0"}, BytesIO(b"{}"))
            if failure == "timeout":
                raise TimeoutError("synthetic-not-a-key")
            if failure == "network":
                raise OSError("synthetic-not-a-key")
            return Response(b"not json")
        return Response()

    result = adapter_for(bound, opener).invoke(request())
    assert result.success
    assert result.attempts[0].category is category
    assert len(calls) == len(receipts) == len(set(ids)) == 2
    assert receipts[0] is not receipts[1]
    assert bound.authority.snapshot().committed_attempts == 0
    for receipt in receipts:
        with pytest.raises(ProcessingStateError):
            bound.authority.finish_attempt(receipt)
    assert "synthetic-not-a-key" not in repr(result.attempts)


@pytest.mark.parametrize("failure", ["ordinary", "read", "http_read", "root", "oversize"])
@pytest.mark.parametrize("candidate", [False, True])
def test_receipt_is_finished_for_every_transport_exit(failure, candidate):
    bound = candidate_dispatch() if candidate else dispatch()

    class BadRead(Response):
        def read(self, size=-1):
            raise RuntimeError("synthetic-not-a-key")

    def opener(*args, **kwargs):
        if failure == "ordinary":
            raise RuntimeError("synthetic-not-a-key")
        if failure == "read":
            return BadRead()
        if failure == "http_read":
            raise HTTPError(args[0].full_url, 500, "synthetic", {}, BadRead())
        return Response(b"[]" if failure == "root" else b"x" * 40)

    transport = provider.UrllibJsonTransport(opener=opener, max_response_bytes=32)
    with pytest.raises((RuntimeError, provider.ProviderResponseError)):
        (send_probe if candidate else send)(transport, bound)
    assert bound.authority.snapshot().committed_attempts == 0


def test_duplicate_attempt_id_cannot_reuse_a_commitment(monkeypatch):
    bound = dispatch()
    calls = []

    class FixedId:
        hex = "same-attempt"

    monkeypatch.setattr(provider, "uuid4", FixedId)

    def opener(*args, **kwargs):
        calls.append(args)
        return Response()

    transport = provider.UrllibJsonTransport(opener=opener)
    send(transport, bound)
    with pytest.raises(CloudDispatchBlocked):
        send(transport, bound)
    assert len(calls) == 1
    assert bound.authority.snapshot().committed_attempts == 0


def test_generation_switch_during_injected_backoff_submits_no_retry():
    bound = dispatch()
    calls, waits = [], []

    def waiter(event, delay):
        assert event is bound.context.generation_cancel_event
        waits.append(delay)
        bound.authority.select_local()
        return event.wait(0)

    def opener(*args, **kwargs):
        calls.append(args)
        raise TimeoutError("synthetic")

    retry = RetryExecutor(RetryPolicy(base_delay=30), waiter=waiter)
    result = adapter_for(bound, opener, retry_executor=retry).invoke(request())
    assert_cancelled(result)
    assert len(calls) == len(waits) == 1
    assert bound.authority.snapshot().committed_attempts == 0


def test_task_cancel_and_caller_callback_after_success_discard_value():
    for source in ("task", "caller"):
        task_event = Event()
        bound = dispatch(task_cancel_event=task_event)
        done = Event()

        def opener(*args, **kwargs):
            done.set()
            if source == "task":
                task_event.set()
            return Response()

        result = adapter_for(bound, opener).invoke(
            request(), cancellation_token=lambda: source == "caller" and done.is_set())
        assert_cancelled(result)
        assert result.attempts[0].success
        assert result.attempts[0].usage["prompt_tokens"] == 3


@pytest.mark.parametrize("error_type", [CloudDispatchBlocked, ProcessingSuperseded])
def test_processing_exceptions_survive_sanitization_and_are_cancelled(error_type):
    bound = dispatch()
    error = error_type()

    class GuardedTransport:
        def send(self, *, dispatch_context, **kwargs):
            assert dispatch_context is bound
            raise error

    adapter = provider.OpenAICompatibleAdapter(
        profile=verified_custom_profile(), credential="synthetic-not-a-key",
        transport=GuardedTransport(), processing_dispatch=bound)
    result = adapter.invoke(request())
    assert_cancelled(result)
    assert result.final_error is error
    assert result.total_attempts == 1


def test_guarded_adapter_does_not_fallback_to_legacy_transport():
    bound = dispatch()
    calls = []

    class LegacyTransport:
        def send(self, *, url, headers, json_body, timeout):
            calls.append(json_body)
            return provider.TransportResponse(200)

    adapter = provider.OpenAICompatibleAdapter(
        profile=verified_custom_profile(), credential="synthetic-not-a-key",
        processing_dispatch=bound, transport=LegacyTransport())
    result = adapter.invoke(request())
    assert not result.success
    assert result.total_attempts == 1
    assert calls == []
    assert "synthetic-not-a-key" not in str(result.final_error)


def test_probe_is_fixed_and_does_not_verify_business_profile():
    bound = dispatch()
    bodies = []

    def opener(req, **kwargs):
        bodies.append(json.loads(req.data))
        return Response()

    profile = replace(verified_custom_profile(), needs_connection_verification=True)
    adapter = adapter_for(bound, opener, profile=profile)
    assert adapter.invoke_probe().success
    assert bodies == [{"model": profile.model, "messages": [{"role": "user", "content": "ping"}],
                       "stream": False, "max_tokens": 1}]
    with pytest.raises(provider.ProviderAdapterConfigurationError):
        adapter.invoke(request())
    bound.authority.select_local()
    assert_cancelled(adapter.invoke_probe())
    assert len(bodies) == 1


def test_redirect_is_not_followed_or_retried():
    bound = dispatch()
    calls = []

    def opener(req, **kwargs):
        calls.append(req)
        raise HTTPError(req.full_url, 302, "redirect", {"Location": "https://other.example.test"}, BytesIO(b"{}"))

    result = adapter_for(bound, opener).invoke(request())
    assert not result.success
    assert result.total_attempts == len(calls) == 1
    assert result.final_category is ErrorCategory.INVALID_REQUEST
    real_opener = provider.UrllibJsonTransport()._open.__self__
    redirect = next(handler for handler in real_opener.handlers
                    if isinstance(handler, provider._NoRedirectHandler))
    assert redirect.redirect_request(calls[0], None, 302, "redirect", {}, "https://other.example.test") is None
    assert bound.authority.snapshot().committed_attempts == 0


def test_dispatch_is_immutable_and_repr_omits_context_and_credential():
    bound = dispatch()
    adapter = adapter_for(bound, lambda *a, **k: Response())
    assert repr(bound) == "ProcessingDispatch()"
    assert "synthetic" not in repr(adapter)
    with pytest.raises(FrozenInstanceError):
        bound.context = None


def test_local_selected_during_request_construction_is_still_before_commit(monkeypatch):
    bound = dispatch()
    calls = []
    original_request = provider.Request

    def prepare_request(*args, **kwargs):
        prepared = original_request(*args, **kwargs)
        bound.authority.select_local()
        return prepared

    monkeypatch.setattr(provider, "Request", prepare_request)
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: calls.append(a))
    with pytest.raises(CloudDispatchBlocked):
        send(transport, bound)
    assert calls == []
    assert bound.authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("probe", [False, True])
def test_current_local_work_does_not_grant_cloud_permission(probe):
    bound = dispatch()
    transition = bound.authority.select_local()
    bound.authority.set_local_state(transition.snapshot.generation, LocalReadiness.READY,
                                    engine_fingerprint="b" * 64)
    local_work = bound.authority.capture_work(engine_fingerprint="b" * 64,
                                              task_attempt_id="synthetic-local")
    local_dispatch = provider.ProcessingDispatch(bound.authority, local_work)
    calls = []
    adapter = adapter_for(local_dispatch, lambda *a, **k: calls.append(a))
    result = adapter.invoke_probe() if probe else adapter.invoke(request())
    assert_cancelled(result)
    assert isinstance(result.final_error, CloudDispatchBlocked)
    assert calls == []
    assert bound.authority.snapshot().committed_attempts == 0


def test_success_callback_can_select_local_without_publishing_old_value():
    bound = dispatch()
    finished = Event()

    def opener(*args, **kwargs):
        finished.set()
        return Response()

    def caller_cancelled():
        if finished.is_set():
            bound.authority.select_local()
        return False

    result = adapter_for(bound, opener).invoke(request(), cancellation_token=caller_cancelled)
    assert_cancelled(result)
    assert result.attempts[0].success
    assert result.attempts[0].usage["completion_tokens"] == 2


def test_task_cancelled_during_serialization_denies_opener(monkeypatch):
    task_cancel = Event()
    bound = dispatch(task_cancel_event=task_cancel)
    calls = []
    dumps = provider.json.dumps

    def prepare(value, **kwargs):
        encoded = dumps(value, **kwargs)
        task_cancel.set()
        return encoded

    monkeypatch.setattr(provider.json, "dumps", prepare)
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: calls.append(a))
    with pytest.raises(CloudDispatchBlocked):
        send(transport, bound)
    assert calls == []
    assert bound.authority.snapshot().committed_attempts == 0


def candidate_dispatch(*, profile=None, authority=None, task_cancel_event=None):
    profile = profile or verified_custom_profile()
    authority = authority or ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    return provider.ProcessingDispatch(authority, authority.capture_cloud_probe(
        candidate_fingerprint=cloud_engine_fingerprint(profile), candidate_model=profile.model,
        request_id="candidate-probe", task_cancel_event=task_cancel_event))


def fixed_body(bound):
    return {"model": bound.context.candidate_model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False, "max_tokens": 1}


def send_probe(transport, bound, body=None):
    return transport.send(url="https://provider.example.test/v1/chat/completions",
                          headers={}, json_body=fixed_body(bound) if body is None else body,
                          timeout=1, dispatch_context=bound)


def test_candidate_probe_without_binding_succeeds_and_uses_dedicated_commit(monkeypatch):
    bound = candidate_dispatch()
    before = bound.authority.snapshot()
    calls, receipts = [], []
    original = bound.authority.commit_cloud_probe_attempt

    def commit(context, attempt_id):
        receipt = original(context, attempt_id)
        receipts.append(receipt)
        return receipt

    def reject_business(*args):
        pytest.fail("probe used business commitment")

    monkeypatch.setattr(bound.authority, "commit_cloud_probe_attempt", commit)
    monkeypatch.setattr(bound.authority, "commit_cloud_attempt", reject_business)

    def opener(req, **kwargs):
        calls.append(json.loads(req.data))
        assert bound.authority.snapshot().committed_attempts == 1
        return Response()

    assert adapter_for(bound, opener).invoke_probe().success
    assert calls == [fixed_body(bound)]
    assert bound.authority.snapshot() == before
    assert len(receipts) == 1
    with pytest.raises(ProcessingStateError):
        bound.authority.finish_attempt(receipts[0])


def test_probe_cannot_invoke_verified_business_before_any_preparation(monkeypatch):
    bound = candidate_dispatch()
    calls = []
    adapter = adapter_for(bound, lambda *a, **k: calls.append(a))

    def forbidden(*args):
        pytest.fail("business request preparation reached with probe permission")

    monkeypatch.setattr(adapter, "_validate_invocation", forbidden)
    with pytest.raises(CloudDispatchBlocked):
        adapter.invoke(request())
    assert calls == []


@pytest.mark.parametrize("changed", ["model", "display_name", "capabilities", "verification"])
def test_candidate_identity_mismatch_rejected_before_adapter_preparation(monkeypatch, changed):
    profile = verified_custom_profile()
    bound = candidate_dispatch(profile=profile)
    changes = {"model": dict(model="different"), "display_name": dict(display_name="different"),
               "capabilities": dict(capabilities=replace(profile.capabilities, vision=not profile.capabilities.vision)),
               "verification": dict(needs_connection_verification=True)}
    adapter = adapter_for(bound, lambda *a, **k: pytest.fail("opener reached"),
                          profile=replace(profile, **changes[changed]))
    monkeypatch.setattr(adapter, "_validate_invocation_for_probe",
                        lambda: pytest.fail("mismatch reached probe preparation"))
    with pytest.raises(CloudDispatchBlocked):
        adapter.invoke_probe()


@pytest.mark.parametrize("field,value", [
    ("model", "other-model"), ("model", None), ("model", 1),
    ("messages", []), ("messages", [{"role": "system", "content": "ping"}]),
    ("messages", [{"role": "user", "content": "file contents"}]),
    ("messages", [{"role": "user", "content": "ping", "name": "extra"}]),
    ("messages", [{"role": "user", "content": "ping"}] * 2),
    ("messages", [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:synthetic"}}]}]),
    ("messages", ({"role": "user", "content": "ping"},)),
    ("stream", True), ("stream", 0), ("stream", None),
    ("max_tokens", True), ("max_tokens", 1.0), ("max_tokens", 2), ("max_tokens", "1"),
    ("unknown", "private-content"),
])
def test_probe_altered_body_rejects_before_encoding_request_or_opener(monkeypatch, field, value):
    bound = candidate_dispatch()
    body = fixed_body(bound)
    body[field] = value
    monkeypatch.setattr(provider.json, "dumps", lambda *a, **k: pytest.fail("encoding reached"))
    monkeypatch.setattr(provider, "Request", lambda *a, **k: pytest.fail("request creation reached"))
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: pytest.fail("opener reached"))
    with pytest.raises(CloudDispatchBlocked):
        send_probe(transport, bound, body)
    assert bound.authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("field", ["model", "messages", "stream", "max_tokens"])
def test_probe_missing_field_is_rejected(field):
    bound = candidate_dispatch()
    body = fixed_body(bound)
    del body[field]
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: pytest.fail("opener reached"))
    with pytest.raises(CloudDispatchBlocked):
        send_probe(transport, bound, body)


@pytest.mark.parametrize("kind", ["copy", "deepcopy", "reconstruct", "foreign"])
def test_fabricated_probe_rejected_by_raw_transport_and_adapter(monkeypatch, kind):
    bound = candidate_dispatch()
    context = bound.context
    invalid = {"copy": lambda: copy(context),
               "deepcopy": lambda: deepcopy(context, {id(context.generation_cancel_event): context.generation_cancel_event}),
               "reconstruct": lambda: replace(context),
               "foreign": lambda: candidate_dispatch().context}[kind]()
    forged = provider.ProcessingDispatch(bound.authority, invalid)
    monkeypatch.setattr(provider.json, "dumps", lambda *a, **k: pytest.fail("encoding reached"))
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: pytest.fail("opener reached"))
    with pytest.raises(CloudDispatchBlocked):
        send_probe(transport, forged)
    with pytest.raises(CloudDispatchBlocked):
        adapter_for(forged, lambda *a, **k: pytest.fail("opener reached")).invoke_probe()


def test_dispatch_accepts_only_explicit_context_union():
    bound = dispatch()
    for invalid in (object(), None, bound.authority.snapshot()):
        with pytest.raises(TypeError):
            provider.ProcessingDispatch(bound.authority, invalid)
    assert bound.is_current()
    candidate = candidate_dispatch()
    assert candidate.is_current()
    candidate.authority.invalidate_work()
    assert not candidate.is_current()


@pytest.mark.parametrize("when", ["serialization", "request", "before", "task"])
def test_probe_cancellation_before_commit_denies_opener(monkeypatch, when):
    event = Event()
    bound = candidate_dispatch(task_cancel_event=event)
    if when == "before":
        bound.authority.select_local()
    if when == "task":
        event.set()
    name = "dumps" if when == "serialization" else "Request"
    target = provider.json if when == "serialization" else provider
    original = getattr(target, name)

    def prepare(*args, **kwargs):
        value = original(*args, **kwargs)
        bound.authority.invalidate_work()
        return value

    if when in {"serialization", "request"}:
        monkeypatch.setattr(target, name, prepare)
    transport = provider.UrllibJsonTransport(opener=lambda *a, **k: pytest.fail("opener reached"))
    with pytest.raises(CloudDispatchBlocked):
        send_probe(transport, bound)
    assert bound.authority.snapshot().committed_attempts == 0


def test_probe_local_between_attempts_blocks_retry_and_discards_committed_success():
    for response_kind in ("timeout", "success"):
        bound = candidate_dispatch()
        calls = []

        def opener(*args, **kwargs):
            calls.append(args)
            assert bound.authority.snapshot().committed_attempts == 1
            bound.authority.select_local()
            if response_kind == "timeout":
                raise TimeoutError("synthetic")
            return Response()

        result = adapter_for(bound, opener).invoke_probe()
        assert_cancelled(result)
        assert len(calls) == 1
        assert bound.authority.snapshot().committed_attempts == 0
        if response_kind == "success":
            assert result.attempts[0].success


def test_candidate_retry_each_commit_is_unique_and_finishes_before_next_attempt(monkeypatch):
    bound = candidate_dispatch()
    receipts, ids, calls = [], [], []
    commit = bound.authority.commit_cloud_probe_attempt

    def record(context, attempt_id):
        assert bound.authority.snapshot().committed_attempts == 0
        receipt = commit(context, attempt_id)
        receipts.append(receipt)
        ids.append(attempt_id)
        return receipt

    monkeypatch.setattr(bound.authority, "commit_cloud_probe_attempt", record)

    def opener(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise TimeoutError("synthetic")
        return Response()

    assert adapter_for(bound, opener).invoke_probe().success
    assert len(calls) == len(receipts) == len(set(ids)) == 2
    for receipt in receipts:
        with pytest.raises(ProcessingStateError):
            bound.authority.finish_attempt(receipt)
    assert bound.authority.snapshot().committed_attempts == 0


def test_candidate_backoff_uses_generation_event_and_local_blocks_next_send():
    bound = candidate_dispatch()
    calls, waits = [], []

    def waiter(event, delay):
        assert event is bound.context.generation_cancel_event
        waits.append(delay)
        bound.authority.select_local()
        return event.wait(0)

    def opener(*args, **kwargs):
        calls.append(args)
        raise TimeoutError("synthetic")

    result = adapter_for(bound, opener,
        retry_executor=RetryExecutor(RetryPolicy(base_delay=30), waiter=waiter)).invoke_probe()
    assert_cancelled(result)
    assert len(calls) == len(waits) == 1


def test_candidate_legacy_transport_signature_never_falls_back():
    bound = candidate_dispatch()
    calls = []

    class LegacyTransport:
        def send(self, *, url, headers, json_body, timeout):
            calls.append(json_body)
            return provider.TransportResponse(200)

    adapter = provider.OpenAICompatibleAdapter(
        profile=verified_custom_profile(), credential="synthetic-not-a-key",
        processing_dispatch=bound, transport=LegacyTransport())
    result = adapter.invoke_probe()
    assert not result.success
    assert result.total_attempts == 1
    assert calls == []


def test_candidate_committed_opener_does_not_block_local_and_stale_value_cannot_publish():
    bound = candidate_dispatch()
    entered, release, transitioned = Event(), Event(), Event()
    results = []

    def opener(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return Response()

    worker = Thread(target=lambda: results.append(adapter_for(bound, opener).invoke_probe()), daemon=True)
    worker.start()
    switcher = None
    try:
        assert entered.wait(5)
        assert bound.authority.snapshot().committed_attempts == 1

        def switch():
            bound.authority.select_local()
            transitioned.set()

        switcher = Thread(target=switch, daemon=True)
        switcher.start()
        assert transitioned.wait(5), "probe send held the authority lock"
    finally:
        release.set()
        worker.join(5)
        if switcher is not None:
            switcher.join(5)
    assert not worker.is_alive()
    assert_cancelled(results[0])
    assert results[0].attempts[0].success
    assert bound.authority.snapshot().committed_attempts == 0


def test_candidate_fixed_body_is_detached_before_request_creation(monkeypatch):
    bound = candidate_dispatch()
    body = fixed_body(bound)
    original = provider.Request
    sent = []

    def prepare(*args, **kwargs):
        body["messages"][0]["content"] = "private-content"
        return original(*args, **kwargs)

    def opener(req, **kwargs):
        sent.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr(provider, "Request", prepare)
    send_probe(provider.UrllibJsonTransport(opener=opener), bound, body)
    assert sent == [fixed_body(bound)]
