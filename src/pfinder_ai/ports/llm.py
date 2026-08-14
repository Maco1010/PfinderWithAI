"""主调查流程使用的通用结构化模型接口。"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class LLMProvider(Protocol):
    """屏蔽具体模型供应商的结构化生成能力。"""

    @property
    def provider_name(self) -> str:
        """返回 UsageMonitor 使用的稳定供应商名称。"""

        ...

    async def generate_structured(
        self,
        *,
        task: str,
        prompt: str,
        output_type: type[StructuredModel],
    ) -> StructuredModel:
        """生成并校验结构化结果，解析失败时抛出标准化异常。"""

        ...

