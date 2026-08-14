"""使用标准库 sqlite3 实现可审计调查轨迹存储。"""

import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from pfinder_ai.domain.enums import ErrorKind
from pfinder_ai.domain.errors import ProviderError
from pfinder_ai.domain.models import (
    DiagnosisResult,
    IncidentInput,
    InvestigationStep,
)


class SQLiteInvestigationStore:
    """持久化领域 JSON，不承担 LangGraph Checkpointer 职责。"""

    def __init__(self, database_path: Path, *, timeout_seconds: float = 5) -> None:
        if str(database_path) == ":memory:":
            raise ValueError("请使用文件数据库，避免多连接下的内存数据库状态丢失")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self._database_path = database_path.resolve()
        self._timeout_seconds = timeout_seconds
        self._initialization_lock = Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """显式创建数据库目录和最小表结构。"""

        await self._run(self._initialize_once, "初始化 SQLite 调查存储")

    async def save_incident(
        self,
        investigation_id: str,
        incident: IncidentInput,
    ) -> None:
        """幂等保存调查输入，并拒绝同一编号对应不同输入。"""

        payload = incident.model_dump_json()

        def operation() -> None:
            self._initialize_once()
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT incident_json FROM investigations WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
                if existing is not None and existing[0] != payload:
                    raise ProviderError(
                        "同一调查编号对应了不同输入",
                        kind=ErrorKind.INVALID_INPUT,
                        retryable=False,
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO investigations (
                        investigation_id,
                        incident_json
                    ) VALUES (?, ?)
                    """,
                    (investigation_id, payload),
                )

        await self._run(operation, "保存调查输入")

    async def load_incident(self, investigation_id: str) -> IncidentInput | None:
        """读取标准化调查输入。"""

        def operation() -> IncidentInput | None:
            self._initialize_once()
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT incident_json FROM investigations WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()
            return IncidentInput.model_validate_json(row[0]) if row else None

        return await self._run(operation, "读取调查输入")

    async def append_step(
        self,
        investigation_id: str,
        step: InvestigationStep,
    ) -> None:
        """按步骤编号幂等追加，并拒绝内容冲突的重复编号。"""

        payload = step.model_dump_json()

        def operation() -> None:
            self._initialize_once()
            with self._connect() as connection:
                existing = connection.execute(
                    """
                    SELECT step_json
                    FROM investigation_steps
                    WHERE investigation_id = ? AND step_id = ?
                    """,
                    (investigation_id, step.step_id),
                ).fetchone()
                if existing is not None and existing[0] != payload:
                    raise ProviderError(
                        "同一调查步骤编号对应了不同内容",
                        kind=ErrorKind.INVALID_RESPONSE,
                        retryable=False,
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO investigation_steps (
                        investigation_id,
                        step_id,
                        step_json
                    ) VALUES (?, ?, ?)
                    """,
                    (investigation_id, step.step_id, payload),
                )

        await self._run(operation, "追加调查步骤")

    async def list_steps(self, investigation_id: str) -> tuple[InvestigationStep, ...]:
        """按首次写入顺序读取调查步骤。"""

        def operation() -> tuple[InvestigationStep, ...]:
            self._initialize_once()
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT step_json
                    FROM investigation_steps
                    WHERE investigation_id = ?
                    ORDER BY sequence_number ASC
                    """,
                    (investigation_id,),
                ).fetchall()
            return tuple(
                InvestigationStep.model_validate_json(row[0]) for row in rows
            )

        return await self._run(operation, "读取调查步骤")

    async def save_result(
        self,
        investigation_id: str,
        result: DiagnosisResult,
    ) -> None:
        """保存同一调查的最新结构化结果。"""

        payload = result.model_dump_json()

        def operation() -> None:
            self._initialize_once()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO investigation_results (
                        investigation_id,
                        result_json,
                        updated_at
                    ) VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(investigation_id) DO UPDATE SET
                        result_json = excluded.result_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (investigation_id, payload),
                )

        await self._run(operation, "保存诊断结果")

    async def load_result(self, investigation_id: str) -> DiagnosisResult | None:
        """读取最近一次保存的诊断结果。"""

        def operation() -> DiagnosisResult | None:
            self._initialize_once()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT result_json
                    FROM investigation_results
                    WHERE investigation_id = ?
                    """,
                    (investigation_id,),
                ).fetchone()
            return DiagnosisResult.model_validate_json(row[0]) if row else None

        return await self._run(operation, "读取诊断结果")

    def _initialize_once(self) -> None:
        """在进程内只执行一次幂等建表。"""

        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    PRAGMA foreign_keys = ON;

                    CREATE TABLE IF NOT EXISTS investigations (
                        investigation_id TEXT PRIMARY KEY,
                        incident_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS investigation_steps (
                        sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
                        investigation_id TEXT NOT NULL,
                        step_id TEXT NOT NULL,
                        step_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (investigation_id, step_id)
                    );

                    CREATE TABLE IF NOT EXISTS investigation_results (
                        investigation_id TEXT PRIMARY KEY,
                        result_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        """为当前线程创建短生命周期连接。"""

        return sqlite3.connect(
            self._database_path,
            timeout=self._timeout_seconds,
        )

    async def _run[T](self, operation: Callable[[], T], name: str) -> T:
        """在线程中执行阻塞 SQLite 操作并转换基础设施异常。"""

        try:
            return await asyncio.to_thread(operation)
        except ProviderError:
            raise
        except sqlite3.Error as error:
            raise ProviderError(
                f"{name}失败",
                kind=ErrorKind.TRANSIENT,
                retryable=True,
                context={"sqlite_error": type(error).__name__},
            ) from error
