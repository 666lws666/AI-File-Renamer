"""M2 UndoManager — per-record outcomes, unified batch undo, no direct file I/O."""
from dataclasses import replace
from src.core.rename_plan import BatchResult, validate_move_evidence
from src.core.rename_history import RenameHistory


class UndoManager:
    def __init__(self, history_path: str, executor=None):
        self._history = RenameHistory(history_path)
        self._executor = executor

    def undo_last_batch(self) -> list[BatchResult]:
        if self._executor is None:
            return [BatchResult("", "", False, error="No executor configured for undo")]
        batch_id = self._history.get_last_batch_id()
        if batch_id is None:
            return []
        return self._undo_batch(batch_id)

    def _undo_batch(self, batch_id: str) -> list[BatchResult]:
        """Single unified undo path for one batch."""
        records = self._history.get_by_batch(batch_id)
        active = [r for r in records if not getattr(r, 'undone', False)]
        if not active:
            # Fully undone — try previous
            return self._try_previous(batch_id)
        return self._undo_records(batch_id, active)

    def _try_previous(self, current_batch_id: str) -> list[BatchResult]:
        """Skip fully-done batch, find previous with active records."""
        all_recs = self._history.get_all()
        found_prev = None
        seen = False
        for rec in reversed(all_recs):
            bid = getattr(rec, 'batch_id', '')
            if bid == current_batch_id and not seen:
                seen = True; continue
            if seen and bid and bid != current_batch_id:
                active_prev = [r for r in all_recs if getattr(r, 'batch_id', '') == bid and not getattr(r, 'undone', False)]
                if active_prev:
                    return self._undo_records(bid, active_prev)
        return []

    def _undo_records(self, batch_id: str, records: list) -> list[BatchResult]:
        """Execute undo for given records in reverse order, track per-record outcomes."""
        reversed_records = list(reversed(records))
        results = []
        success_ids = []
        for rec in reversed_records:
            rec_id = getattr(rec, 'id', '')
            rec_task_id = getattr(rec, 'task_id', '')
            new_path = str(getattr(rec, 'new_path', ''))
            old_path = str(getattr(rec, 'old_path', ''))
            try:
                validate_move_evidence(rec.move_evidence)
            except (AttributeError, ValueError):
                results.append(BatchResult(rec_task_id, batch_id, False,
                                           error='fileops.error.undoEvidenceMissing'))
                continue
            move_result = self._executor.undo_move(new_path, old_path, evidence=rec.move_evidence)
            results.append(replace(move_result, task_id=rec_task_id, batch_id=batch_id))
            if move_result.success and not move_result.recovery_required:
                success_ids.append(rec_id)
        if success_ids:
            try:
                self._history.mark_records_undone(batch_id, success_ids)
            except OSError:
                # The moves already completed; preserve their physical outcomes.
                for result in results:
                    if result.success:
                        result.recovery_required = True
                        result.error = 'fileops.error.historySaveRecovery'
        return results

    def undo_task(self, task_id: str):
        """Undo only the latest active history record for ``task_id``.

        Row-level undo deliberately shares the same per-record execution path as
        batch undo, so failures never mark the wrong history record as undone.
        """
        if self._executor is None:
            return BatchResult(task_id, "", False,
                               error="No executor configured for undo")
        record = next(
            (
                item for item in reversed(self._history.get_all())
                if getattr(item, "task_id", "") == task_id
                and not getattr(item, "undone", False)
            ),
            None,
        )
        if record is None:
            return None
        batch_id = str(getattr(record, "batch_id", ""))
        results = self._undo_records(batch_id, [record])
        return results[0] if results else None

    def get_undoable_batches(self):
        all_recs = self._history.get_all()
        batches = {}
        for r in all_recs:
            bid = getattr(r, 'batch_id', '')
            if bid and not getattr(r, 'undone', False):
                batches[bid] = True
        return [{"batch_id": k} for k in batches.keys()]
