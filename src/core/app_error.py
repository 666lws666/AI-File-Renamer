"""Provider-neutral, presentation-neutral application error contract."""
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class ErrorScope(str, Enum):
    FILE = "file"
    BATCH = "batch"
    APP = "app"


class ErrorSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class AppError:
    code: str
    scope: ErrorScope
    severity: ErrorSeverity
    retryable: bool = False
    user_message_id: str = "error.generic"
    recommended_action: str = ""
    sanitized_detail: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid4()))