"""企业模型网关 Adapter 的结构化输出与错误边界测试。"""

import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from pfinder_ai.adapters.llm import GatewayLLMProvider, GatewayLLMSettings
from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError, StructuredOutputError
from pfinder_ai.monitoring import UsageMonitor


class StructuredAnswer(BaseModel):
    """测试使用的严格结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


def _settings(
    *,
    max_retries: int = 0,
    auth_style: str = "bearer",
) -> GatewayLLMSettings:
    """创建不包含真实地址和凭证的测试配置。"""

    return GatewayLLMSettings(
        base_url="https://llm.example.test/gateway",
        api_key=SecretStr("synthetic-secret"),
        model="synthetic-model",
        auth_style=auth_style,  # type: ignore[arg-type]
        max_retries=max_retries,
        retry_backoff_seconds=0,
    )


def _tool_response(
    tool_input: Mapping[str, Any],
    *,
    input_tokens: int = 10,
    output_tokens: int = 4,
) -> dict[str, Any]:
    """构造 Anthropic Messages Tool Use 合成响应。"""

    return {
        "type": "message",
        "content": [
            {
                "type": "tool_use",
                "name": "submit_structured_result",
                "input": dict(tool_input),
            }
        ],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


@pytest.mark.asyncio
async def test_gateway_returns_validated_tool_result_and_records_usage() -> None:
    """Provider 应强制 Tool Use、校验结果并记录明确 Token。"""

    captured_request: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(json.loads(request.content))
        assert request.url.path == "/gateway/v1/messages"
        assert request.headers["authorization"] == "Bearer synthetic-secret"
        return httpx.Response(
            200,
            json=_tool_response({"summary": "合成结论", "confidence": 0.8}),
        )

    monitor = UsageMonitor()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(
            _settings(),
            usage_monitor=monitor,
            client=client,
        )
        result = await provider.generate_structured(
            task="synthetic_task",
            prompt="分析合成输入",
            output_type=StructuredAnswer,
        )

    assert result == StructuredAnswer(summary="合成结论", confidence=0.8)
    assert captured_request["tool_choice"]["name"] == "submit_structured_result"
    schema = captured_request["tools"][0]["input_schema"]
    assert schema["additionalProperties"] is False
    assert "synthetic-secret" not in repr(_settings())
    assert monitor.snapshot()[0].input_tokens == 10
    assert monitor.snapshot()[0].output_tokens == 4
    assert monitor.snapshot()[0].retries == 0


@pytest.mark.asyncio
async def test_gateway_repairs_invalid_schema_once() -> None:
    """第一次字段缺失时应反馈安全摘要并只修复一次。"""

    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json=_tool_response({"summary": "缺少置信度"}))
        return httpx.Response(
            200,
            json=_tool_response({"summary": "修复成功", "confidence": 0.7}),
        )

    monitor = UsageMonitor()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(
            _settings(),
            usage_monitor=monitor,
            client=client,
        )
        result = await provider.generate_structured(
            task="synthetic_task",
            prompt="分析合成输入",
            output_type=StructuredAnswer,
        )

    assert result.summary == "修复成功"
    assert len(requests) == 2
    assert "schema_validation_failed" in requests[1]["messages"][0]["content"]
    record = monitor.snapshot()[0]
    assert record.retries == 1
    assert record.input_tokens == 20
    assert record.output_tokens == 8


@pytest.mark.asyncio
async def test_gateway_exposes_structured_error_after_second_invalid_result() -> None:
    """修复结果仍不合法时必须返回可观察错误。"""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_tool_response({"summary": "仍然缺字段"}))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(_settings(), client=client)
        with pytest.raises(StructuredOutputError) as caught:
            await provider.generate_structured(
                task="synthetic_task",
                prompt="分析合成输入",
                output_type=StructuredAnswer,
            )

    assert caught.value.kind is ErrorKind.INVALID_RESPONSE
    assert caught.value.context["reason"] == "schema_validation_failed"
    assert "synthetic-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_gateway_maps_authentication_error_without_retry() -> None:
    """认证错误属于确定性失败，不得消耗重试预算。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "sensitive"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(_settings(max_retries=2), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured(
                task="synthetic_task",
                prompt="分析合成输入",
                output_type=StructuredAnswer,
            )

    assert calls == 1
    assert caught.value.kind is ErrorKind.UNAUTHORIZED
    assert caught.value.retryable is False
    assert "sensitive" not in str(caught.value)


@pytest.mark.asyncio
async def test_gateway_retries_rate_limit_and_records_failed_usage() -> None:
    """限流只进行有限重试，并在最终失败时记录调用状态。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request)

    monitor = UsageMonitor()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(
            _settings(max_retries=1),
            usage_monitor=monitor,
            client=client,
        )
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured(
                task="synthetic_task",
                prompt="分析合成输入",
                output_type=StructuredAnswer,
            )

    assert calls == 2
    assert caught.value.kind is ErrorKind.TRANSIENT
    assert caught.value.retryable is True
    assert monitor.snapshot()[0].success is False
    assert monitor.snapshot()[0].retries == 1


@pytest.mark.asyncio
async def test_gateway_maps_network_timeout_to_retryable_error() -> None:
    """连接超时在耗尽有限重试后应暴露为临时错误。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("synthetic timeout", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(_settings(max_retries=1), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured(
                task="synthetic_task",
                prompt="分析合成输入",
                output_type=StructuredAnswer,
            )

    assert calls == 2
    assert caught.value.kind is ErrorKind.TRANSIENT
    assert caught.value.retryable is True
    assert caught.value.context == {"error_type": "ConnectTimeout"}


@pytest.mark.asyncio
async def test_gateway_supports_x_api_key_without_bearer_header() -> None:
    """认证策略选择 x-api-key 时不得同时发送 Bearer 凭证。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "synthetic-secret"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json=_tool_response({"summary": "合成结论", "confidence": 0.8}),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GatewayLLMProvider(
            _settings(auth_style="x_api_key"),
            client=client,
        )
        result = await provider.generate_structured(
            task="synthetic_task",
            prompt="分析合成输入",
            output_type=StructuredAnswer,
        )

    assert result.confidence == 0.8
