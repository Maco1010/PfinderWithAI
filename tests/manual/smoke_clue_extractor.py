"""使用本地配置的真实模型网关手工验证 ClueExtractor 解析效果。"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from pfinder_ai.bootstrap import build_llm_provider
from pfinder_ai.config import AppSettings
from pfinder_ai.domain.models import IncidentInput
from pfinder_ai.graph.nodes.clue_extractor import ClueExtractorNode
from pfinder_ai.graph.state import InvestigationState
from pfinder_ai.monitoring import UsageMonitor

_DEFAULT_DESCRIPTION = (
    "2026年8月15日 14:30 左右，system-a 的订单号 "
    "order_id=synthetic-order-001 创建失败，trace id 为 "
    "trace-synthetic-001，调用 system-b 时发生超时。"
)


def _business_key(value: str) -> tuple[str, str]:
    """把命令行中的 KEY=VALUE 转换为期望业务标识。"""

    key, separator, expected = value.partition("=")
    if not separator or not key.strip() or not expected.strip():
        raise argparse.ArgumentTypeError("业务标识期望值必须使用 KEY=VALUE 格式")
    return key.strip(), expected.strip()


def _build_parser() -> argparse.ArgumentParser:
    """构造只接受合成或脱敏输入的 Smoke Test 参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "通过当前 .env 中的真实模型网关运行 ClueExtractor。"
            "输入会发送给模型，请勿使用生产数据或敏感信息。"
        )
    )
    parser.add_argument(
        "description",
        nargs="?",
        help="待解析的合成或脱敏问题描述；省略时使用内置合成样例",
    )
    parser.add_argument("--expect-start-system", help="期望解析出的起始系统")
    parser.add_argument("--expect-trace-id", help="期望解析出的 Trace ID")
    parser.add_argument(
        "--expect-business-key",
        action="append",
        default=[],
        type=_business_key,
        metavar="KEY=VALUE",
        help="期望解析出的业务标识；可重复提供",
    )
    return parser


def _resolve_expectations(
    args: argparse.Namespace,
    *,
    using_default_description: bool,
) -> tuple[str | None, str | None, dict[str, str]]:
    """默认样例自带断言，自定义输入只执行调用方声明的断言。"""

    start_system = args.expect_start_system
    trace_id = args.expect_trace_id
    business_keys = dict(args.expect_business_key)
    if using_default_description:
        start_system = start_system or "system-a"
        trace_id = trace_id or "trace-synthetic-001"
        business_keys.setdefault("order_id", "synthetic-order-001")
    return start_system, trace_id, business_keys


def _build_checks(
    *,
    incident: IncidentInput,
    provider_call_count: int,
    error_count: int,
    call_succeeded: bool,
    expected_start_system: str | None,
    expected_trace_id: str | None,
    expected_business_keys: dict[str, str],
) -> dict[str, bool]:
    """生成可以直接决定进程退出状态的显式检查结果。"""

    checks = {
        "provider_called_once": provider_call_count == 1,
        "gateway_call_succeeded": call_succeeded,
        "no_node_errors": error_count == 0,
    }
    if expected_start_system is not None:
        checks["expected_start_system"] = incident.start_system == expected_start_system
    if expected_trace_id is not None:
        checks["expected_trace_id"] = incident.trace_id == expected_trace_id
    for key, expected in expected_business_keys.items():
        checks[f"expected_business_key:{key}"] = incident.business_keys.get(key) == expected
    return checks


async def _run(args: argparse.Namespace) -> int:
    """执行一次真实解析并只输出受控的结构化结果。"""

    using_default_description = args.description is None
    description = args.description or _DEFAULT_DESCRIPTION
    expected_start_system, expected_trace_id, expected_business_keys = (
        _resolve_expectations(args, using_default_description=using_default_description)
    )

    try:
        settings = AppSettings()
    except (ValidationError, ValueError):
        print(
            json.dumps(
                {
                    "smoke_test": "clue_extractor_live",
                    "passed": False,
                    "configuration_error": (
                        "模型配置无效，请检查本地 .env；具体配置值未输出"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    monitor = UsageMonitor()
    llm = build_llm_provider(settings, monitor)
    if llm is None:
        print(
            json.dumps(
                {
                    "smoke_test": "clue_extractor_live",
                    "passed": False,
                    "configuration_error": (
                        "模型网关未启用，请设置 PFINDER_AI_LLM_PROVIDER=gateway"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    provided = IncidentInput(description=description)
    update = await ClueExtractorNode(llm)(
        InvestigationState(
            investigation_id="smoke-clue-extractor-live",
            incident=provided,
        )
    )
    incident = update["incident"]
    errors = update.get("errors", ())
    usage_records = monitor.snapshot()
    usage = usage_records[0] if usage_records else None
    checks = _build_checks(
        incident=incident,
        provider_call_count=update.get("provider_call_count", 0),
        error_count=len(errors),
        call_succeeded=usage is not None and usage.success,
        expected_start_system=expected_start_system,
        expected_trace_id=expected_trace_id,
        expected_business_keys=expected_business_keys,
    )
    passed = all(checks.values())

    output: dict[str, Any] = {
        "smoke_test": "clue_extractor_live",
        "passed": passed,
        "input": provided.model_dump(mode="json"),
        "parsed_incident": incident.model_dump(mode="json"),
        "checks": checks,
        "node": {
            "execution_status": update["execution_status"].value,
            "provider_call_count": update.get("provider_call_count", 0),
            "errors": [
                {
                    "kind": error.kind.value,
                    "message": error.message,
                    "retryable": error.retryable,
                    "context": error.context,
                }
                for error in errors
            ],
        },
        "usage": (
            {
                "provider": usage.provider,
                "operation": usage.operation,
                "success": usage.success,
                "retries": usage.retries,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
            if usage is not None
            else None
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    """解析命令行参数并返回适合自动检查的退出码。"""

    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
