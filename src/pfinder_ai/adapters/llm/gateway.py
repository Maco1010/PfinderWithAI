"""通过企业模型网关提供结构化生成能力。"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError, StructuredOutputError
from pfinder_ai.monitoring import UsageMonitor
from pfinder_ai.ports.llm import LLMProvider, StructuredModel

GatewayProtocol = Literal["anthropic_messages"]
GatewayAuthStyle = Literal["bearer", "x_api_key"]
Sleep = Callable[[float], Awaitable[None]]

_STRUCTURED_TOOL_NAME = "submit_structured_result"
_SYSTEM_INSTRUCTION = (
    "你是企业故障调查流程中的结构化推理组件。只能根据输入生成结果，"
    "不得猜测企业内部地址、凭证或未提供的事实。必须调用指定工具提交结果。"
)


@dataclass(frozen=True, slots=True)
class GatewayLLMSettings:
    """调用企业模型网关所需的受控配置。"""

    base_url: str = field(repr=False)
    api_key: SecretStr = field(repr=False)
    model: str
    protocol: GatewayProtocol = "anthropic_messages"
    auth_style: GatewayAuthStyle = "bearer"
    timeout_seconds: float = 60
    max_tokens: int = 2048
    max_retries: int = 1
    retry_backoff_seconds: float = 0.5
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        """拒绝缺失凭证、无效地址和无界重试配置。"""

        if not self.base_url.strip():
            raise ValueError("base_url 不能为空")
        if not self.api_key.get_secret_value():
            raise ValueError("api_key 不能为空")
        if not self.model.strip():
            raise ValueError("model 不能为空")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if self.max_tokens < 1:
            raise ValueError("max_tokens 必须大于 0")
        if not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries 必须在 0 到 3 之间")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds 不能小于 0")

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url 不得包含凭证、查询参数或片段")
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            parsed.scheme == "http"
            and not is_loopback
            and not self.allow_insecure_http
        ):
            raise ValueError("非本地 HTTP 模型地址必须显式允许不安全传输")

    @property
    def messages_endpoint(self) -> str:
        """根据受控根地址生成 Anthropic Messages 端点。"""

        base_url = self.base_url.rstrip("/")
        return f"{base_url}/messages" if base_url.endswith("/v1") else f"{base_url}/v1/messages"


@dataclass(slots=True)
class _UsageAccumulator:
    """汇总一次逻辑调用内所有实际模型响应的明确用量。"""

    retries: int = 0
    response_count: int = 0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    input_tokens_complete: bool = True
    output_tokens_complete: bool = True

    def add_response(self, payload: Mapping[str, Any]) -> None:
        """累加供应商明确返回的 Token，不推测缺失值。"""

        self.response_count += 1
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            self.input_tokens_complete = False
            self.output_tokens_complete = False
            return
        self._add_token_value(usage.get("input_tokens"), input_side=True)
        self._add_token_value(usage.get("output_tokens"), input_side=False)

    def add_unknown_response(self) -> None:
        """记录无法解析用量的成功响应。"""

        self.response_count += 1
        self.input_tokens_complete = False
        self.output_tokens_complete = False

    @property
    def input_tokens(self) -> int | None:
        """只在每个响应都提供输入 Token 时返回合计。"""

        if self.response_count == 0 or not self.input_tokens_complete:
            return None
        return self.input_tokens_total

    @property
    def output_tokens(self) -> int | None:
        """只在每个响应都提供输出 Token 时返回合计。"""

        if self.response_count == 0 or not self.output_tokens_complete:
            return None
        return self.output_tokens_total

    def _add_token_value(self, value: Any, *, input_side: bool) -> None:
        """校验并累加单侧 Token。"""

        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            if input_side:
                self.input_tokens_complete = False
            else:
                self.output_tokens_complete = False
            return
        if input_side:
            self.input_tokens_total += value
        else:
            self.output_tokens_total += value


class _StructuredResultFailure(Exception):
    """内部使用的非敏感结构化解析失败。"""

    def __init__(self, reason: str, *, fields: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fields = fields


class GatewayLLMProvider(LLMProvider):
    """通过可配置企业网关实现主流程 LLMProvider。"""

    def __init__(
        self,
        settings: GatewayLLMSettings,
        *,
        usage_monitor: UsageMonitor | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._usage_monitor = usage_monitor
        self._client = client
        self._sleep = sleep

    @property
    def provider_name(self) -> str:
        """返回不包含公司或网关地址的稳定供应商名称。"""

        return "llm_gateway"

    async def generate_structured(
        self,
        *,
        task: str,
        prompt: str,
        output_type: type[StructuredModel],
    ) -> StructuredModel:
        """强制模型通过 Tool Use 返回结果，并执行 Pydantic 校验。"""

        if not task.strip() or not prompt.strip():
            raise ProviderError(
                "模型任务名和输入不能为空",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
            )

        usage = _UsageAccumulator()
        if self._usage_monitor is None:
            return await self._generate_with_repair(task, prompt, output_type, usage)

        async with self._usage_monitor.track(
            provider=self.provider_name,
            operation=task,
            details={
                "model": self._settings.model,
                "protocol": self._settings.protocol,
            },
        ) as measurement:
            try:
                return await self._generate_with_repair(
                    task,
                    prompt,
                    output_type,
                    usage,
                )
            finally:
                measurement.retries = usage.retries
                measurement.set_model_usage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )

    async def _generate_with_repair(
        self,
        task: str,
        prompt: str,
        output_type: type[StructuredModel],
        usage: _UsageAccumulator,
    ) -> StructuredModel:
        """首次解析失败后只执行一次受控格式修复。"""

        request = self._build_request(prompt, output_type)
        try:
            payload = await self._request_with_retries(request, usage)
            return self._parse_structured_result(payload, output_type)
        except _StructuredResultFailure as first_failure:
            usage.retries += 1
            repair_prompt = self._build_repair_prompt(prompt, first_failure)

        try:
            payload = await self._request_with_retries(
                self._build_request(repair_prompt, output_type),
                usage,
            )
            return self._parse_structured_result(payload, output_type)
        except _StructuredResultFailure as second_failure:
            raise StructuredOutputError(
                "模型返回的结构化结果连续两次未通过校验",
                context={
                    "task": task,
                    "output_type": output_type.__name__,
                    "reason": second_failure.reason,
                },
            ) from second_failure

    def _build_request(
        self,
        prompt: str,
        output_type: type[BaseModel],
    ) -> dict[str, Any]:
        """使用调用方模型 Schema 构造强制 Tool Use 请求。"""

        return {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "stream": False,
            "system": _SYSTEM_INSTRUCTION,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": _STRUCTURED_TOOL_NAME,
                    "description": "提交经过校验的结构化任务结果。",
                    "input_schema": output_type.model_json_schema(),
                }
            ],
            "tool_choice": {
                "type": "tool",
                "name": _STRUCTURED_TOOL_NAME,
                "disable_parallel_tool_use": True,
            },
        }

    async def _request_with_retries(
        self,
        request: Mapping[str, Any],
        usage: _UsageAccumulator,
    ) -> Mapping[str, Any]:
        """只对网络错误、限流和临时服务错误进行有限重试。"""

        attempt = 0
        while True:
            try:
                response = await self._post(request)
            except httpx.RequestError as error:
                if attempt < self._settings.max_retries:
                    attempt += 1
                    usage.retries += 1
                    await self._wait_before_retry(attempt)
                    continue
                raise ProviderError(
                    "模型网关连接失败",
                    kind=ErrorKind.TRANSIENT,
                    retryable=True,
                    context={"error_type": type(error).__name__},
                ) from error

            if self._is_retryable_status(response.status_code) and (
                attempt < self._settings.max_retries
            ):
                attempt += 1
                usage.retries += 1
                await self._wait_before_retry(attempt)
                continue

            self._raise_for_status(response.status_code)
            try:
                payload = response.json()
            except ValueError as error:
                usage.add_unknown_response()
                raise _StructuredResultFailure("invalid_json") from error
            if not isinstance(payload, Mapping):
                usage.add_unknown_response()
                raise _StructuredResultFailure("response_not_object")
            usage.add_response(payload)
            return payload

    async def _post(self, request: Mapping[str, Any]) -> httpx.Response:
        """发送请求；不跟随重定向，避免凭证被转发到其他主机。"""

        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        secret = self._settings.api_key.get_secret_value()
        if self._settings.auth_style == "bearer":
            headers["authorization"] = f"Bearer {secret}"
        else:
            headers["x-api-key"] = secret

        if self._client is not None:
            return await self._client.post(
                self._settings.messages_endpoint,
                headers=headers,
                json=dict(request),
                timeout=self._settings.timeout_seconds,
            )

        async with httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return await client.post(
                self._settings.messages_endpoint,
                headers=headers,
                json=dict(request),
                timeout=self._settings.timeout_seconds,
            )

    def _parse_structured_result(
        self,
        payload: Mapping[str, Any],
        output_type: type[StructuredModel],
    ) -> StructuredModel:
        """要求响应中恰好存在一个目标工具调用。"""

        content = payload.get("content")
        if not isinstance(content, list):
            raise _StructuredResultFailure("missing_content")
        matching_blocks = [
            block
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "tool_use"
            and block.get("name") == _STRUCTURED_TOOL_NAME
        ]
        if len(matching_blocks) != 1:
            raise _StructuredResultFailure("invalid_tool_use_count")
        tool_input = matching_blocks[0].get("input")
        try:
            return output_type.model_validate(tool_input)
        except ValidationError as error:
            fields = tuple(
                ".".join(str(part) for part in item["loc"])
                for item in error.errors(include_input=False, include_url=False)
            )
            raise _StructuredResultFailure(
                "schema_validation_failed",
                fields=fields,
            ) from error

    def _build_repair_prompt(
        self,
        original_prompt: str,
        failure: _StructuredResultFailure,
    ) -> str:
        """只反馈字段路径和错误类别，不回传原始错误响应。"""

        field_summary = ", ".join(failure.fields) if failure.fields else "无具体字段"
        return (
            f"{original_prompt}\n\n"
            "前一次结构化结果未通过校验，请重新完成同一任务。"
            f"错误类别：{failure.reason}；相关字段：{field_summary}。"
            "不得补造输入中不存在的事实。"
        )

    async def _wait_before_retry(self, attempt: int) -> None:
        """使用有界指数退避等待下一次请求。"""

        delay = self._settings.retry_backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            await self._sleep(delay)

    def _raise_for_status(self, status_code: int) -> None:
        """把 HTTP 状态转换为稳定且不泄密的领域错误。"""

        if 200 <= status_code < 300:
            return
        context = {"status_code": status_code}
        if status_code in {401, 403}:
            raise ProviderError(
                "模型网关认证失败",
                kind=ErrorKind.UNAUTHORIZED,
                retryable=False,
                context=context,
            )
        if status_code == 404:
            raise ProviderError(
                "模型网关端点或模型不存在",
                kind=ErrorKind.NOT_FOUND,
                retryable=False,
                context=context,
            )
        if self._is_retryable_status(status_code):
            raise ProviderError(
                "模型网关暂时不可用",
                kind=ErrorKind.TRANSIENT,
                retryable=True,
                context=context,
            )
        if 400 <= status_code < 500:
            raise ProviderError(
                "模型网关拒绝请求",
                kind=ErrorKind.INVALID_INPUT,
                retryable=False,
                context=context,
            )
        raise ProviderError(
            "模型网关返回无法识别的响应状态",
            kind=ErrorKind.INVALID_RESPONSE,
            retryable=False,
            context=context,
        )

    def _is_retryable_status(self, status_code: int) -> bool:
        """判断是否属于可以安全重试的临时状态。"""

        return status_code in {408, 429} or status_code >= 500
