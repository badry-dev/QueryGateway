"""Unit coverage for restoring in-memory scheduler jobs after restart."""

import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_restore_active_schedules_registers_each_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduler as scheduler_service

    schedules = [
        SimpleNamespace(
            id=uuid.uuid4(),
            endpoint_id=uuid.uuid4(),
            schedule_type="cron",
            cron_expression="0 6 * * *",
            interval_seconds=None,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            endpoint_id=uuid.uuid4(),
            schedule_type="interval",
            cron_expression=None,
            interval_seconds=300,
        ),
    ]

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeScheduleRepository:
        def __init__(self, db: object) -> None:
            self.db = db

        async def get_all(self, *, active_only: bool = False) -> list[object]:
            assert active_only is True
            return cast(list[object], schedules)

    add_job = MagicMock()
    monkeypatch.setattr(scheduler_service, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(scheduler_service, "ScheduleRepository", FakeScheduleRepository)
    monkeypatch.setattr(scheduler_service, "add_schedule_job", add_job)

    restored = await scheduler_service.restore_active_schedules()

    assert restored == 2
    assert add_job.call_count == 2
    assert add_job.call_args_list[0].kwargs["schedule_id"] == schedules[0].id
