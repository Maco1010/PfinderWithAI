"""PfinderWithAI 本地 Demo 的 Typer 命令行入口。"""

import asyncio
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from pfinder_ai.application import InvestigationEvent
from pfinder_ai.bootstrap import build_application
from pfinder_ai.config import AppSettings
from pfinder_ai.domain.errors import PfinderAIError
from pfinder_ai.domain.models import DiagnosisResult, IncidentInput, TimeRange

app = typer.Typer(
    help="使用 Trace、日志和代码证据调查微服务故障。",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


class RichEventSink:
    """将非敏感应用事件显示到控制台。"""

    async def emit(self, event: InvestigationEvent) -> None:
        """输出调查编号、事件类型和摘要。"""

        console.print(
            f"[dim]{event.investigation_id}[/dim] "
            f"[cyan]{event.kind.value}[/cyan] {event.message}"
        )


@app.callback()
def root() -> None:
    """保留命令组入口，便于后续增加回放和查询命令。"""


@app.command()
def investigate(
    description: Annotated[str, typer.Argument(help="错误现象或业务问题描述")],
    start_system: Annotated[
        str,
        typer.Option("--start-system", "-s", help="调查起始系统"),
    ],
    business_key: Annotated[
        list[str] | None,
        typer.Option(
            "--business-key",
            "-k",
            help="业务标识，格式为 key=value，可重复提供",
        ),
    ] = None,
    trace_id: Annotated[
        str | None,
        typer.Option("--trace-id", help="已知 TraceID"),
    ] = None,
    time_description: Annotated[
        str | None,
        typer.Option("--time-description", help="大致发生时间或查询范围"),
    ] = None,
    investigation_id: Annotated[
        str | None,
        typer.Option("--investigation-id", help="可选的外部调查编号"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="只输出结构化 JSON"),
    ] = False,
) -> None:
    """运行一次 Fake 纵向调查并输出诊断结果。"""

    try:
        keys = _parse_business_keys(business_key or [])
        incident = IncidentInput(
            description=description,
            business_keys=keys,
            start_system=start_system,
            trace_id=trace_id,
            time_range=(
                TimeRange(description=time_description)
                if time_description
                else None
            ),
        )
        bundle = build_application(
            AppSettings(),
            event_sink=None if json_output else RichEventSink(),
        )
        result = asyncio.run(
            bundle.service.investigate(
                incident,
                investigation_id=investigation_id,
            )
        )
    except (PfinderAIError, ValidationError, ValueError) as error:
        error_console.print(f"[red]调查失败：{error}[/red]")
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _render_result(result)


def _parse_business_keys(values: list[str]) -> dict[str, str]:
    """解析重复 key=value 参数，并拒绝空值和重复键。"""

    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"业务标识格式错误：{value}")
        key, item_value = (part.strip() for part in value.split("=", maxsplit=1))
        if not key or not item_value:
            raise ValueError(f"业务标识键和值不能为空：{value}")
        if key in parsed:
            raise ValueError(f"业务标识键重复：{key}")
        parsed[key] = item_value
    return parsed


def _render_result(result: DiagnosisResult) -> None:
    """渲染适合本地排查人员阅读的简要报告。"""

    console.print(f"\n[bold]结论：[/bold]{result.summary}")
    console.print(f"执行状态：{result.execution_status.value}")
    console.print(f"结论状态：{result.conclusion_status.value}")
    console.print(f"置信度：{result.confidence:.0%}")
    console.print(f"终止原因：{result.termination_reason}")

    evidence_table = Table(title="证据链")
    evidence_table.add_column("类型")
    evidence_table.add_column("系统")
    evidence_table.add_column("摘要")
    evidence_table.add_column("来源定位")
    for evidence in result.evidence:
        evidence_table.add_row(
            evidence.source.value,
            evidence.system or "-",
            evidence.summary,
            evidence.locator,
        )
    console.print(evidence_table)
    console.print(
        f"API 调用：{result.usage.calls}，"
        f"已知输入 Token：{result.usage.input_tokens or '未知'}，"
        f"已知输出 Token：{result.usage.output_tokens or '未知'}"
    )


def main() -> None:
    """启动 Typer 应用。"""

    app()


if __name__ == "__main__":
    main()
