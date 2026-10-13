from .contract_suite import ProviderContract


class TestKimiContract(ProviderContract):
    provider_id = "kimi"
    expected_url = "https://api.moonshot.ai/v1/chat/completions"
    expected_response_format = "json_schema"
    supports_visual = True

    def test_request_response_usage_contract(self):
        super().test_request_response_usage_contract()
        adapter, transport = self.make_adapter([self._success()])
        result = adapter.invoke(self._request())
        assert result.success is True
        response_format = transport.calls[0]["json_body"]["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True

    @staticmethod
    def _success():
        from .contract_suite import success_response

        return success_response()

    @staticmethod
    def _request():
        from .contract_suite import request

        return request(with_visual=True)
