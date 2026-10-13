"""M1 QML test fixtures — deterministic mock data for Batch tests."""
from src.controllers.mock_batch_controller import MockBatchController

def make_default_controller():
    """Default controller with 20 tasks covering 8 states."""
    return MockBatchController()

def make_empty_controller():
    """Controller with zero tasks (empty state)."""
    ctrl = MockBatchController()
    ctrl.set_empty()
    return ctrl
