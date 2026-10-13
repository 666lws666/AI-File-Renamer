"""Synthetic, deterministic authority tests; no network, files or runtime."""
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
import gc
import threading
import weakref

import pytest

from src.core.processing_authority import (
    CloudDispatchBlocked, LocalProcessingUnavailable, LocalReadiness,
    ProcessingAuthority, ProcessingMode, ProcessingStateError,
    ProcessingSuperseded,
)


A = "a" * 64
B = "b" * 64


def test_permanent_close_revokes_all_admission_but_finishes_committed_receipts():
    authority = cloud()
    work = capture(authority)
    probe = authority.capture_cloud_probe(candidate_fingerprint=B,
        candidate_model="model", request_id="probe")
    receipt = authority.commit_cloud_attempt(work, "committed")
    pending = authority.request_cloud_choice()
    authority.close_admission()
    generation = authority.snapshot().generation
    authority.close_admission()
    assert authority.snapshot().generation == generation
    assert not authority.complete_choice(pending, persisted=True)
    assert not authority.is_current(work)
    assert not authority.is_current_cloud_probe(probe)
    with pytest.raises(ProcessingSuperseded):
        capture(authority)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(work, "late")
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(probe, "late")
    with pytest.raises(ProcessingSuperseded):
        authority.capture_cloud_probe(candidate_fingerprint=B,
            candidate_model="model", request_id="late-probe")
    authority.finish_attempt(receipt)
    assert authority.snapshot().committed_attempts == 0


def test_unbind_cloud_engine_clears_only_binding_and_revokes_old_work():
    authority = cloud()
    work = capture(authority)
    receipt = authority.commit_cloud_attempt(work, "committed")
    before = authority.snapshot()
    after = authority.unbind_cloud_engine()
    assert after.engine_fingerprint is None
    assert (after.mode, after.revision, after.local_readiness) == (
        before.mode, before.revision, before.local_readiness)
    assert after.generation > before.generation
    assert not authority.is_current(work)
    with pytest.raises(CloudDispatchBlocked):
        capture(authority)
    authority.finish_attempt(receipt)


def test_close_ready_local_is_not_reopened_by_choice_or_readiness_updates():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
        engine_fingerprint=A)
    authority.close_admission()
    assert not authority.set_local_state(authority.snapshot().generation,
        LocalReadiness.READY, engine_fingerprint=A)
    with pytest.raises(ProcessingSuperseded):
        capture(authority)
    with pytest.raises(ProcessingSuperseded):
        authority.request_cloud_choice()


def test_current_choice_probe_authenticates_identity_without_consuming_retry():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    intent = authority.request_cloud_choice()
    assert authority.is_current_choice(intent)
    assert not authority.is_current_choice(copy(intent))
    assert not authority.is_current_choice(None)
    assert authority.complete_choice(intent, persisted=False)
    assert authority.is_current_choice(intent)
    assert authority.complete_choice(intent, persisted=True)
    assert not authority.is_current_choice(intent)
    stale = authority.request_cloud_choice()
    latest = authority.select_local().intent
    assert not authority.is_current_choice(stale)
    assert authority.is_current_choice(latest)


def cloud():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    authority.bind_cloud_engine(A)
    return authority


def capture(authority, **kwargs):
    return authority.capture_work(engine_fingerprint=A, task_attempt_id="task-1", **kwargs)


def test_legacy_cloud_is_preserved_but_engine_must_be_bound():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    assert authority.snapshot().mode is ProcessingMode.CLOUD
    assert authority.snapshot().revision == 0
    with pytest.raises(CloudDispatchBlocked):
        capture(authority)
    authority.bind_cloud_engine(A)
    assert authority.is_current(capture(authority))


def test_fresh_sessions_and_local_startup_never_restores_readiness():
    first = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL, initial_revision=7)
    second = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    snapshot = first.snapshot()
    assert snapshot.session_id != second.snapshot().session_id
    assert snapshot.revision == 7
    assert snapshot.local_readiness is LocalReadiness.NOT_READY
    assert snapshot.persistence_status == "saved"
    with pytest.raises(LocalProcessingUnavailable):
        capture(first)


def test_commit_then_local_retains_only_old_outstanding_attempt():
    authority = cloud()
    context = capture(authority)
    receipt = authority.commit_cloud_attempt(context, "attempt-1")
    transition = authority.select_local()
    assert transition.committed_attempts == 1
    assert context.generation_cancel_event.is_set()
    assert not authority.is_current(context)
    with pytest.raises(ProcessingSuperseded):
        authority.assert_current(context)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-2")
    authority.finish_attempt(receipt)
    assert authority.snapshot().committed_attempts == 0


def test_local_before_commit_blocks():
    authority = cloud()
    context = capture(authority)
    authority.select_local()
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")
    assert authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("committed_first", [False, True])
def test_blocked_worker_never_blocks_local_selection(committed_first):
    authority = cloud()
    context = capture(authority)
    reached = threading.Event()
    release = threading.Event()
    selected = threading.Event()
    outcomes = []

    def worker():
        receipt = None
        try:
            if committed_first:
                receipt = authority.commit_cloud_attempt(context, "attempt-1")
            reached.set()
            assert release.wait(5)
            if not committed_first:
                receipt = authority.commit_cloud_attempt(context, "attempt-1")
            outcomes.append("committed")
        except CloudDispatchBlocked:
            outcomes.append("blocked")
        finally:
            if receipt is not None:
                authority.finish_attempt(receipt)

    def selector():
        outcomes.append(authority.select_local().committed_attempts)
        selected.set()

    worker_thread = threading.Thread(target=worker)
    selector_thread = threading.Thread(target=selector)
    worker_thread.start()
    try:
        assert reached.wait(5)
        selector_thread.start()
        assert selected.wait(5), "local selection waited for external worker"
        assert not release.is_set()
    finally:
        release.set()
        worker_thread.join(5)
        if selector_thread.ident is not None:
            selector_thread.join(5)
    assert not worker_thread.is_alive()
    assert not selector_thread.is_alive()
    assert outcomes == ([1, "committed"] if committed_first else [0, "blocked"])
    assert authority.snapshot().committed_attempts == 0


def test_latest_successful_cloud_choice_only_opens_and_old_work_never_revives():
    authority = cloud()
    old = capture(authority)
    local = authority.select_local()
    cloud_intent = authority.request_cloud_choice()
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert cloud_intent.revision == local.intent.revision + 1
    assert authority.complete_choice(cloud_intent, persisted=True)
    assert authority.snapshot().mode is ProcessingMode.CLOUD
    assert authority.snapshot().persistence_status == "saved"
    assert authority.is_current(capture(authority))
    assert not authority.is_current(old)
    assert not authority.complete_choice(local.intent, persisted=True)
    assert not authority.complete_choice(cloud_intent, persisted=True)


@pytest.mark.parametrize("purpose", ["business", "probe"])
def test_repeat_cloud_choice_blocks_pending_failure_and_retry_never_revives_old_context(purpose):
    authority = cloud()
    take = capture if purpose == "business" else probe
    current = authority.is_current if purpose == "business" else authority.is_current_cloud_probe
    commit = (authority.commit_cloud_attempt if purpose == "business"
              else authority.commit_cloud_probe_attempt)
    context = take(authority)
    receipt = commit(context, "already-committed")
    generation = authority.snapshot().generation
    intent = authority.request_cloud_choice()
    assert not current(context)
    assert context.generation_cancel_event.is_set()
    assert authority.snapshot().generation == generation + 1
    assert authority.snapshot().persistence_status == "pending"
    with pytest.raises(CloudDispatchBlocked):
        take(authority)
    with pytest.raises(CloudDispatchBlocked):
        commit(context, "pending")
    assert authority.complete_choice(intent, persisted=False)
    assert authority.snapshot().mode is ProcessingMode.CLOUD
    assert authority.snapshot().persistence_status == "error"
    assert authority.is_current_choice(intent)
    with pytest.raises(CloudDispatchBlocked):
        take(authority)
    with pytest.raises(CloudDispatchBlocked):
        commit(context, "failed")
    assert not current(context)
    authority.finish_attempt(receipt)
    assert authority.snapshot().committed_attempts == 0
    assert authority.complete_choice(intent, persisted=True)
    assert authority.snapshot().generation == generation + 1
    assert authority.snapshot().revision == intent.revision
    assert not current(context)
    with pytest.raises(CloudDispatchBlocked):
        commit(context, "revived")
    fresh = take(authority)
    assert current(fresh)
    authority.finish_attempt(commit(fresh, "fresh"))
    assert not authority.complete_choice(intent, persisted=False)
    assert current(fresh)


@pytest.mark.parametrize("purpose", ["business", "probe"])
def test_repeat_cloud_new_capture_requires_exact_latest_success(purpose):
    authority = cloud()
    take = capture if purpose == "business" else probe
    old = authority.request_cloud_choice()
    latest = authority.request_cloud_choice()
    assert not authority.complete_choice(copy(latest), persisted=True)
    assert not authority.complete_choice(old, persisted=True)
    with pytest.raises(CloudDispatchBlocked):
        take(authority)
    assert authority.complete_choice(latest, persisted=True)
    fresh = take(authority)
    assert fresh.generation == authority.snapshot().generation


def test_failed_cloud_save_and_stale_success_cannot_open_local():
    authority = cloud()
    authority.select_local()
    failed = authority.request_cloud_choice()
    assert authority.complete_choice(failed, persisted=False)
    assert authority.snapshot().persistence_status == "error"
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    local = authority.select_local()
    assert not authority.complete_choice(failed, persisted=True)
    assert authority.snapshot().revision == local.intent.revision
    assert authority.snapshot().mode is ProcessingMode.LOCAL


@pytest.mark.parametrize("mode", [ProcessingMode.LOCAL, ProcessingMode.CLOUD])
def test_failed_latest_choice_can_retry_persistence_without_new_intent(mode):
    authority = cloud()
    local = authority.select_local()
    intent = local.intent if mode is ProcessingMode.LOCAL else authority.request_cloud_choice()
    generation = authority.snapshot().generation
    authority.set_local_state(generation, LocalReadiness.FAILED)
    assert authority.complete_choice(intent, persisted=False)
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert authority.complete_choice(intent, persisted=True)
    saved = authority.snapshot()
    assert saved.mode is mode
    assert saved.revision == intent.revision
    assert saved.persistence_status == "saved"
    assert saved.local_readiness is LocalReadiness.FAILED
    assert not authority.complete_choice(intent, persisted=False)
    assert not authority.complete_choice(intent, persisted=True)
    assert authority.snapshot() == saved


@pytest.mark.parametrize("state", list(LocalReadiness))
@pytest.mark.parametrize("saved", [True, False])
def test_local_persistence_never_changes_readiness(state, saved):
    authority = cloud()
    local = authority.select_local()
    assert authority.set_local_state(local.snapshot.generation, state,
        engine_fingerprint=A if state is LocalReadiness.READY else None)
    assert authority.complete_choice(local.intent, persisted=saved)
    snapshot = authority.snapshot()
    assert snapshot.mode is ProcessingMode.LOCAL
    assert snapshot.local_readiness is state
    assert snapshot.persistence_status == ("saved" if saved else "error")


@pytest.mark.parametrize("state", [LocalReadiness.FAILED, LocalReadiness.CANCELLED])
def test_repeated_local_and_resource_failure_never_reopen(state):
    authority = cloud()
    local = authority.select_local()
    authority.set_local_state(local.snapshot.generation, state)
    again = authority.select_local()
    assert again.snapshot.generation > local.snapshot.generation
    assert again.snapshot.revision > local.snapshot.revision
    assert again.snapshot.local_readiness is state
    assert again.snapshot.mode is ProcessingMode.LOCAL
    with pytest.raises(LocalProcessingUnavailable):
        capture(authority)


def test_startup_error_requires_explicit_successfully_saved_cloud_choice():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD, startup_error=True)
    authority.bind_cloud_engine(A)
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert authority.snapshot().error_code == "PROCESSING_STARTUP_ERROR"
    failed = authority.request_cloud_choice()
    authority.complete_choice(failed, persisted=False)
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    intent = authority.request_cloud_choice()
    authority.complete_choice(intent, persisted=True)
    assert authority.snapshot().mode is ProcessingMode.CLOUD
    assert authority.snapshot().error_code is None
    assert authority.is_current(capture(authority))


def test_local_ready_changes_engine_generation_and_stale_ready_is_rejected():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    generation = authority.snapshot().generation
    assert authority.set_local_state(generation, LocalReadiness.READY, engine_fingerprint=A)
    context = capture(authority)
    assert context.generation > generation
    assert not authority.set_local_state(generation, LocalReadiness.READY, engine_fingerprint=B)
    assert authority.set_local_state(context.generation, LocalReadiness.READY, engine_fingerprint=B)
    assert not authority.is_current(context)
    assert context.generation_cancel_event.is_set()
    with pytest.raises(LocalProcessingUnavailable):
        capture(authority)
    assert authority.is_current(authority.capture_work(engine_fingerprint=B, task_attempt_id="task-2"))


@pytest.mark.parametrize("state", [LocalReadiness.NOT_READY, LocalReadiness.PREPARING,
                                  LocalReadiness.FAILED, LocalReadiness.CANCELLED])
def test_leaving_local_ready_fences_inflight_work(state):
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
                              engine_fingerprint=A)
    context = capture(authority)
    assert authority.set_local_state(context.generation, state)
    assert not authority.is_current(context)
    assert context.generation_cancel_event.is_set()
    with pytest.raises(LocalProcessingUnavailable):
        capture(authority)


def test_local_state_changes_in_cloud_do_not_change_mode_or_cloud_context():
    authority = cloud()
    context = capture(authority)
    assert authority.set_local_state(context.generation, LocalReadiness.FAILED)
    assert authority.snapshot().mode is ProcessingMode.CLOUD
    assert authority.is_current(context)


def test_cloud_binding_under_local_does_not_change_local_identity_or_gate():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
                              engine_fingerprint=A)
    context = capture(authority)
    snapshot = authority.bind_cloud_engine(B)
    assert snapshot.mode is ProcessingMode.LOCAL
    assert snapshot.engine_fingerprint == A
    assert authority.is_current(context)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")


def test_cloud_identity_change_fences_work_but_same_identity_does_not():
    authority = cloud()
    context = capture(authority)
    authority.bind_cloud_engine(A)
    assert authority.is_current(context)
    authority.bind_cloud_engine(B)
    assert not authority.is_current(context)
    assert context.generation_cancel_event.is_set()
    with pytest.raises(CloudDispatchBlocked):
        capture(authority)


def test_cancellation_checked_at_capture_and_every_commit_never_cleared():
    authority = cloud()
    cancelled = threading.Event()
    context = capture(authority, task_cancel_event=cancelled)
    cancelled.set()
    assert not authority.is_current(context)
    with pytest.raises(ProcessingSuperseded):
        capture(authority, task_cancel_event=cancelled)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")
    assert cancelled.is_set()


def test_foreign_or_forged_values_never_authorize():
    authority = cloud()
    other = cloud()
    context = capture(authority)
    for invalid in [capture(other), replace(context), copy(context), object(), None]:
        assert not authority.is_current(invalid)
        with pytest.raises(ProcessingSuperseded):
            authority.assert_current(invalid)
        with pytest.raises(CloudDispatchBlocked):
            authority.commit_cloud_attempt(invalid, "attempt-1")
    receipt = authority.commit_cloud_attempt(context, "attempt-1")
    intent = authority.request_cloud_choice()
    for invalid in [other.request_cloud_choice(), replace(intent), copy(intent), object(), None]:
        assert not authority.complete_choice(invalid, persisted=True)
    for invalid in [replace(receipt), copy(receipt), object(), None]:
        with pytest.raises(ProcessingStateError):
            authority.finish_attempt(invalid)
    with pytest.raises(ProcessingStateError):
        other.finish_attempt(receipt)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(receipt, "attempt-2")
    assert authority.snapshot().committed_attempts == 1
    authority.finish_attempt(receipt)


def test_attempt_ids_cannot_repeat_after_finish_and_finish_cannot_underflow():
    authority = cloud()
    context = capture(authority)
    receipt = authority.commit_cloud_attempt(context, "attempt-1")
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")
    authority.finish_attempt(receipt)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")
    with pytest.raises(ProcessingStateError):
        authority.finish_attempt(receipt)
    assert authority.snapshot().committed_attempts == 0


def test_attempt_ledger_has_32_limit_and_is_per_context():
    authority = cloud()
    context = capture(authority)
    for index in range(32):
        authority.finish_attempt(authority.commit_cloud_attempt(context, str(index)))
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "32")
    fresh = capture(authority)
    authority.finish_attempt(authority.commit_cloud_attempt(fresh, "0"))


def test_context_is_not_retained_by_authority_even_with_outstanding_receipt():
    authority = cloud()
    context = capture(authority)
    reference = weakref.ref(context)
    receipt = authority.commit_cloud_attempt(context, "attempt-1")
    del context
    gc.collect()
    assert reference() is None
    authority.finish_attempt(receipt)


@pytest.mark.parametrize("fingerprint", [None, "", "A" * 64, "a" * 63, "g" * 64,
                                          "private/path", 1, True, b"a" * 64])
def test_invalid_fingerprints_fail_with_fixed_error(fingerprint):
    authority = cloud()
    with pytest.raises(ProcessingStateError, match="^PROCESSING_STATE_ERROR$"):
        authority.bind_cloud_engine(fingerprint)
    with pytest.raises(ProcessingStateError, match="^PROCESSING_STATE_ERROR$"):
        authority.capture_work(engine_fingerprint=fingerprint, task_attempt_id="task-1")
    authority.select_local()
    with pytest.raises(ProcessingStateError, match="^PROCESSING_STATE_ERROR$"):
        authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
                                  engine_fingerprint=fingerprint)


@pytest.mark.parametrize("kwargs", [dict(initial_mode="cloud"), dict(initial_mode=None),
    dict(initial_mode=ProcessingMode.CLOUD, initial_revision=True),
    dict(initial_mode=ProcessingMode.CLOUD, initial_revision=-1),
    dict(initial_mode=ProcessingMode.CLOUD, initial_revision=2**63),
    dict(initial_mode=ProcessingMode.CLOUD, startup_error=1)])
def test_invalid_constructor_types_fail_closed(kwargs):
    with pytest.raises(ProcessingStateError):
        ProcessingAuthority(**kwargs)


def test_invalid_method_types_do_not_mutate_state_or_invoke_callbacks():
    authority = cloud()
    before = authority.snapshot()

    class DangerousEvent(threading.Event):
        def is_set(self):
            pytest.fail("external callback invoked")

    for event in [object(), DangerousEvent()]:
        with pytest.raises(ProcessingStateError):
            capture(authority, task_cancel_event=event)
    for task_id in [None, "", 1, True]:
        with pytest.raises(ProcessingStateError):
            authority.capture_work(engine_fingerprint=A, task_attempt_id=task_id)
    for generation, state in [(True, LocalReadiness.FAILED), (-1, LocalReadiness.FAILED),
                              (before.generation, "ready")]:
        with pytest.raises(ProcessingStateError):
            authority.set_local_state(generation, state)
    assert authority.snapshot() == before
    intent = authority.request_cloud_choice()
    with pytest.raises(ProcessingStateError):
        authority.complete_choice(intent, persisted=1)
    assert authority.complete_choice(intent, persisted=True)


def test_public_values_frozen_and_repr_omits_task_data():
    authority = cloud()
    context = authority.capture_work(engine_fingerprint=A, task_attempt_id="private-task-marker")
    receipt = authority.commit_cloud_attempt(context, "private-attempt-marker")
    local = authority.select_local()
    for value in [context, context.snapshot, local, local.intent, receipt]:
        assert "private-task-marker" not in repr(value)
        assert "private-attempt-marker" not in repr(value)
        with pytest.raises(FrozenInstanceError):
            value.new_field = 1
    assert context.mode is ProcessingMode.CLOUD
    assert context.session_id == context.snapshot.session_id
    assert context.engine_fingerprint == A
    authority.finish_attempt(receipt)


def test_exhausted_cloud_choice_is_fixed_error_without_transition():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD,
                                    initial_revision=2**63 - 1)
    before = authority.snapshot()
    with pytest.raises(ProcessingStateError):
        authority.request_cloud_choice()
    assert authority.snapshot() == before


def test_exhausted_local_choice_still_closes_and_invalidates_pending_cloud():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD,
                                    initial_revision=2**63 - 2)
    authority.bind_cloud_engine(A)
    context = capture(authority)
    pending_cloud = authority.request_cloud_choice()
    with pytest.raises(ProcessingStateError, match="^PROCESSING_STATE_ERROR$"):
        authority.select_local()
    snapshot = authority.snapshot()
    assert snapshot.mode is ProcessingMode.LOCAL
    assert snapshot.revision == 2**63 - 1
    assert snapshot.generation > context.generation
    assert snapshot.persistence_status == "error"
    assert snapshot.error_code == "PROCESSING_PERSISTENCE_ERROR"
    assert context.generation_cancel_event.is_set()
    assert not authority.is_current(context)
    assert not authority.complete_choice(pending_cloud, persisted=True)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "attempt-1")


def probe(authority, **kwargs):
    assert hasattr(authority, "capture_cloud_probe"), "dedicated probe capture is missing"
    return authority.capture_cloud_probe(candidate_fingerprint=B, candidate_model="candidate-model",
                                         request_id="probe-1", **kwargs)


def test_probe_capture_needs_no_binding_and_does_not_mutate_business_identity():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    before = authority.snapshot()
    context = probe(authority)
    assert authority.snapshot() == before
    assert context.session_id == before.session_id
    assert context.generation == before.generation
    assert context.candidate_fingerprint == B
    assert context.candidate_model == "candidate-model"
    assert authority.is_current_cloud_probe(context)
    assert not authority.is_current(context)
    with pytest.raises(ProcessingSuperseded):
        authority.assert_current(context)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_attempt(context, "business")
    bound = cloud()
    work = capture(bound)
    before = bound.snapshot()
    probe(bound)
    assert bound.snapshot() == before
    assert bound.is_current(work)
    assert not bound.is_current_cloud_probe(work)
    with pytest.raises(CloudDispatchBlocked):
        bound.commit_cloud_probe_attempt(work, "probe")


def test_probe_identity_copies_cross_owner_and_reconstructions_are_not_permits():
    authority = cloud()
    context = probe(authority)
    copied = deepcopy(context, {id(context.generation_cancel_event): context.generation_cancel_event})
    for invalid in [copy(context), copied, replace(context), probe(cloud()), None, object()]:
        assert not authority.is_current_cloud_probe(invalid)
        with pytest.raises(CloudDispatchBlocked):
            authority.commit_cloud_probe_attempt(invalid, "attempt")
    assert B not in repr(context)
    assert "candidate-model" not in repr(context)
    assert "probe-1" not in repr(context)
    with pytest.raises(FrozenInstanceError):
        context.candidate_model = "other"


def test_probe_unique_bounded_attempts_and_shared_receipts_survive_local():
    authority = cloud()
    context = probe(authority)
    business = authority.commit_cloud_attempt(capture(authority), "business")
    receipt = authority.commit_cloud_probe_attempt(context, "0")
    assert authority.snapshot().committed_attempts == 2
    authority.finish_attempt(receipt)
    with pytest.raises(ProcessingStateError):
        authority.finish_attempt(receipt)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(context, "0")
    for index in range(1, 32):
        authority.finish_attempt(authority.commit_cloud_probe_attempt(context, str(index)))
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(context, "32")
    latest = probe(authority)
    receipt = authority.commit_cloud_probe_attempt(latest, "0")
    authority.select_local()
    assert not authority.is_current_cloud_probe(latest)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(latest, "1")
    authority.finish_attempt(receipt)
    authority.finish_attempt(business)
    assert authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize("mode,startup_error", [(ProcessingMode.LOCAL, False),
                                               (ProcessingMode.CLOUD, True)])
def test_probe_capture_fails_when_cloud_not_available(mode, startup_error):
    authority = ProcessingAuthority(initial_mode=mode, startup_error=startup_error)
    with pytest.raises(CloudDispatchBlocked):
        probe(authority)


def test_probe_capture_and_currentness_fail_on_persistence_error():
    authority = cloud()
    context = probe(authority)
    intent = authority.request_cloud_choice()
    authority.complete_choice(intent, persisted=False)
    assert not authority.is_current_cloud_probe(context)
    with pytest.raises(CloudDispatchBlocked):
        probe(authority)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(context, "attempt")


def test_probe_cancel_capture_and_invalidation_keep_selection_binding_and_readiness():
    authority = cloud()
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.FAILED)
    event = threading.Event()
    context = probe(authority, task_cancel_event=event)
    event.set()
    assert not authority.is_current_cloud_probe(context)
    with pytest.raises(ProcessingSuperseded):
        probe(authority, task_cancel_event=event)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(context, "attempt")
    context = probe(authority)
    business = capture(authority)
    before = authority.snapshot()
    after = authority.invalidate_work()
    assert after == replace(before, generation=before.generation + 1)
    assert context.generation_cancel_event.is_set()
    assert not authority.is_current_cloud_probe(context)
    assert not authority.is_current(business)
    assert authority.is_current_cloud_probe(probe(authority))
    assert authority.is_current(capture(authority))


@pytest.mark.parametrize("field,value", [
    ("candidate_fingerprint", "A" * 64), ("candidate_fingerprint", None),
    ("candidate_model", ""), ("candidate_model", "m" * 129),
    ("candidate_model", True), ("request_id", ""), ("request_id", 1),
    ("request_id", "r" * 129), ("task_cancel_event", object()),
])
def test_probe_capture_strict_types_fail_before_mutation(field, value):
    authority = cloud()
    before = authority.snapshot()
    assert hasattr(authority, "capture_cloud_probe"), "dedicated probe capture is missing"
    kwargs = dict(candidate_fingerprint=B, candidate_model="candidate-model", request_id="probe-1")
    kwargs[field] = value
    with pytest.raises(ProcessingStateError):
        authority.capture_cloud_probe(**kwargs)
    assert authority.snapshot() == before


def test_probe_context_is_not_retained_by_authority_or_receipt():
    authority = cloud()
    context = probe(authority)
    reference = weakref.ref(context)
    receipt = authority.commit_cloud_probe_attempt(context, "attempt")
    del context
    gc.collect()
    assert reference() is None
    authority.finish_attempt(receipt)


def test_invalidate_local_keeps_readiness_identity_revision_and_does_not_reopen_cloud():
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
                              engine_fingerprint=A)
    context = capture(authority)
    before = authority.snapshot()
    after = authority.invalidate_work()
    assert after == replace(before, generation=before.generation + 1)
    assert context.generation_cancel_event.is_set()
    assert not authority.is_current(context)
    assert authority.is_current(capture(authority))
    with pytest.raises(CloudDispatchBlocked):
        probe(authority)


def test_probe_exact_event_type_and_identifiers_do_not_run_callback_under_lock():
    authority = cloud()
    before = authority.snapshot()

    class CallbackEvent(threading.Event):
        def is_set(self):
            pytest.fail("event callback reached")

    with pytest.raises(ProcessingStateError):
        probe(authority, task_cancel_event=CallbackEvent())
    context = probe(authority)
    for invalid in ("", None, True, "a" * 129):
        with pytest.raises(ProcessingStateError):
            authority.commit_cloud_probe_attempt(context, invalid)
    assert authority.snapshot() == before


def test_probe_binding_generation_change_and_foreign_receipt_fail_closed():
    authority = cloud()
    context = probe(authority)
    receipt = authority.commit_cloud_probe_attempt(context, "attempt")
    for invalid in (copy(receipt), replace(receipt), None):
        with pytest.raises(ProcessingStateError):
            authority.finish_attempt(invalid)
    with pytest.raises(ProcessingStateError):
        cloud().finish_attempt(receipt)
    authority.bind_cloud_engine(B)
    assert not authority.is_current_cloud_probe(context)
    with pytest.raises(CloudDispatchBlocked):
        authority.commit_cloud_probe_attempt(context, "new")
    authority.finish_attempt(receipt)
