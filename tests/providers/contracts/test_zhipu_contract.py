from .contract_suite import ProviderContract


class TestZhipuContract(ProviderContract):
    provider_id = "zhipu"
    expected_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    supports_visual = True
