import pytest
from src.controllers.batch_workspace_controller import BatchWorkspaceController


@pytest.mark.parametrize("raw,key", [
    ("No active AI provider is configured", "batch.error.providerMissing"),
    ("The active AI provider has no credential", "batch.error.credentialMissing"),
    ("Source file exceeds the configured size limit", "batch.error.fileTooLarge"),
    ("Vision cloud processing is disabled", "batch.error.privacyDisabled"),
    ("Video keyframe cloud processing is disabled", "batch.error.privacyDisabled"),
    ("Text cloud processing is disabled", "batch.error.privacyDisabled"),
])
def test_setup_failures_have_localizable_actionable_messages(raw, key):
    assert BatchWorkspaceController._safe_error(raw) == key
