from .contract_suite import ProviderContract


class TestMiMoContract(ProviderContract):
    provider_id = "mimo"
    expected_url = "https://api.xiaomimimo.com/v1/chat/completions"
    auth_header = "api-key"
    auth_value = "contract-secret"
    supports_visual = True
