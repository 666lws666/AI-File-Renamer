"""Validate only the fixed native greeting; not an isolation attestation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.local_probe_process import ProcessResult


CANONICAL_HELLO_LINE = b'{"protocol":"xuxia-appcontainer-hello","version":1}\r\n'


class HelloValidationError(ValueError):
    """The child result does not match the fixed hello protocol."""


def validate_hello_result(result: ProcessResult) -> None:
    """Validate captured greeting bytes without changing the evidence."""
    if result.status != "completed":
        raise HelloValidationError("child did not complete")
    if type(result.exit_code) is not int or result.exit_code != 0:
        raise HelloValidationError("child exit code is not integer zero")
    if result.cleanup_complete is not True:
        raise HelloValidationError("child cleanup is incomplete")
    if type(result.stdout) is not bytes or result.stdout != CANONICAL_HELLO_LINE:
        raise HelloValidationError("stdout does not match the hello protocol")
    if type(result.stderr) is not bytes or result.stderr != b"":
        raise HelloValidationError("stderr is not empty")
