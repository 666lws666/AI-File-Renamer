"""M3 ProviderProfile — pure metadata, no API keys, no secrets in serialization."""
from dataclasses import asdict, dataclass, field
import ipaddress
from urllib.parse import parse_qsl, urlsplit

from .provider_protocol import ProviderCapabilities


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    id: str = ""
    display_name: str = ""
    provider_id: str = ""
    protocol_kind: str = "openai_compatible"
    auth_scheme: str = "bearer"
    base_url_mode: str = "FIXED"
    base_url: str = ""
    region: str = ""
    workspace_id: str = ""
    model: str = ""
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    timeout_seconds: int = 30
    retry_policy_id: str = "default"
    enabled: bool = True
    needs_connection_verification: bool = True
    credential_account_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.capabilities, ProviderCapabilities):
            raise TypeError("Provider capabilities must be ProviderCapabilities")
        if self.auth_scheme not in {"bearer", "api_key_header"}:
            raise ValueError(f"Unsupported auth_scheme: {self.auth_scheme}")
        if self.timeout_seconds <= 0:
            raise ValueError("Provider timeout_seconds must be positive")
        if self.base_url_mode not in {
            "FIXED", "REGIONAL", "WORKSPACE", "USER_CONFIGURED"
        }:
            raise ValueError(f"Unsupported base_url_mode: {self.base_url_mode}")
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "Provider base_url must be an absolute HTTP(S) URL"
                )
            if parsed.scheme == "http":
                hostname = (parsed.hostname or "").casefold()
                is_loopback = hostname == "localhost" or hostname.endswith(
                    ".localhost"
                )
                if not is_loopback:
                    try:
                        is_loopback = ipaddress.ip_address(hostname).is_loopback
                    except ValueError:
                        is_loopback = False
                if not is_loopback:
                    raise ValueError(
                        "Remote Provider base_url must use HTTPS; HTTP is loopback-only"
                    )
            if parsed.username or parsed.password:
                raise ValueError("Provider base_url cannot contain credentials")
            sensitive_exact = {"key", "credential", "signature", "sig"}
            sensitive_markers = {
                "apikey",
                "token",
                "authorization",
                "secret",
                "password",
            }
            query_keys = {
                key.casefold().replace("_", "").replace("-", "")
                for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
            }
            normalized_fragment = (
                parsed.fragment.casefold().replace("_", "").replace("-", "")
            )
            if any(
                key in sensitive_exact
                or any(marker in key for marker in sensitive_markers)
                for key in query_keys
            ) or any(
                marker in normalized_fragment
                for marker in sensitive_exact | sensitive_markers
            ):
                raise ValueError("Provider base_url cannot contain secret parameters")

    def to_safe_dict(self) -> dict:
        """Serialize metadata without any credential value."""
        data = asdict(self)
        for banned in ("api_key", "token", "authorization", "secret", "password"):
            data.pop(banned, None)
        return data

    @classmethod
    def from_safe_dict(cls, data: dict) -> "ProviderProfile":
        """Restore a profile from persisted, secret-free metadata."""
        values = dict(data)
        for key in values:
            normalized = key.casefold().replace("_", "").replace("-", "")
            if normalized in {
                "apikey", "token", "authorization", "secret", "password"
            }:
                raise ValueError(f"Credential field is forbidden in profile JSON: {key}")
        capabilities = values.get("capabilities", {})
        if not isinstance(capabilities, ProviderCapabilities):
            values["capabilities"] = ProviderCapabilities(**capabilities)
        return cls(**values)
