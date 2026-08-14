"""调查轨迹持久化与历史案例 Memory 接口。"""

from typing import Protocol

from pfinder_ai.domain.models import (
    DiagnosisResult,
    IncidentInput,
    InvestigationStep,
)


class InvestigationStore(Protocol):
    """保存面向审计和回放的调查轨迹，不承担图检查点职责。"""

    async def save_incident(
        self,
        investigation_id: str,
        incident: IncidentInput,
    ) -> None:
        """幂等保存一次调查的标准化原始输入。"""

        ...

    async def load_incident(self, investigation_id: str) -> IncidentInput | None:
        """读取调查输入，供回放和恢复前校验。"""

        ...

    async def append_step(self, investigation_id: str, step: InvestigationStep) -> None:
        """幂等追加一个调查步骤。"""

        ...

    async def list_steps(self, investigation_id: str) -> tuple[InvestigationStep, ...]:
        """按发生顺序读取调查步骤。"""

        ...

    async def save_result(self, investigation_id: str, result: DiagnosisResult) -> None:
        """保存最终诊断结果和终止原因。"""

        ...

    async def load_result(self, investigation_id: str) -> DiagnosisResult | None:
        """读取已经完成的诊断结果。"""

        ...


class CaseMemoryProvider(Protocol):
    """历史案例检索接口；第一版不提供真实实现。"""

    async def find_similar(
        self,
        incident: IncidentInput,
        *,
        limit: int = 5,
    ) -> tuple[DiagnosisResult, ...]:
        """返回只能作为线索、必须重新验证的相似案例。"""

        ...

    async def save_case(self, incident: IncidentInput, result: DiagnosisResult) -> None:
        """保存已经确认或明确标注置信度的案例。"""

        ...
