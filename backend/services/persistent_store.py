from __future__ import annotations

from ..models import ExecutionLogRecord, RollbackRecord
from ..repositories.execution_repository import ExecutionRepository


class PersistentStore:
    """Minimal persistence facade for the demo.

    The SaaS tenant, snapshot, and audit-report stores were removed with the
    dashboard surfaces. Execution logs and rollback records remain.
    """

    def __init__(self) -> None:
        self.execution = ExecutionRepository()

    def save_execution_log(self, log: ExecutionLogRecord) -> ExecutionLogRecord:
        return self.execution.save_execution_log(log)

    def list_execution_logs(self, client_id: str = "", account_id: str = "", limit: int = 50) -> list[ExecutionLogRecord]:
        return self.execution.list_execution_logs(client_id=client_id, account_id=account_id, limit=limit)

    def get_execution_log(self, execution_id: str) -> ExecutionLogRecord | None:
        return self.execution.get_execution_log(execution_id)

    def save_rollback_record(self, record: RollbackRecord) -> RollbackRecord:
        return self.execution.save_rollback_record(record)


def store() -> PersistentStore:
    return PersistentStore()