from .contract_suite import ProviderContract


class TestQwenContract(ProviderContract):
    provider_id = "qwen"
    expected_url = "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"
    supports_visual = True
