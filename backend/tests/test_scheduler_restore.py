"""Unit coverage for restoring in-memory scheduler jobs after restart."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs


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
    db = SimpleNamespace(commit=AsyncMock())

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return db

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeScheduleRepository:
        def __init__(self, db: object) -> None:
            self.db = db

        async def get_all(self, *, active_only: bool = False) -> list[object]:
            assert active_only is True
            return cast(list[object], schedules)

        async def update(self, schedule: object, values: dict[str, object]) -> None:
            setattr(schedule, "next_run_at", values["next_run_at"])

    next_run = datetime(2026, 8, 31, 6, tzinfo=UTC)
    add_job = MagicMock(return_value=next_run)
    monkeypatch.setattr(scheduler_service, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(scheduler_service, "ScheduleRepository", FakeScheduleRepository)
    monkeypatch.setattr(scheduler_service, "add_schedule_job", add_job)

    restored = await scheduler_service.restore_active_schedules()

    assert restored == 2
    assert add_job.call_count == 2
    assert add_job.call_args_list[0].kwargs["schedule_id"] == schedules[0].id
    assert all(schedule.next_run_at == next_run for schedule in schedules)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_active_schedules_fails_when_a_job_is_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduler as scheduler_service

    schedule = SimpleNamespace(
        id=uuid.uuid4(),
        endpoint_id=uuid.uuid4(),
        schedule_type="cron",
        cron_expression=None,
        interval_seconds=None,
    )

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
            return [schedule]

    monkeypatch.setattr(scheduler_service, "AsyncSessionLocal", FakeSessionContext)
    monkeypatch.setattr(scheduler_service, "ScheduleRepository", FakeScheduleRepository)

    with pytest.raises(RuntimeError, match=str(schedule.id)):
        await scheduler_service.restore_active_schedules()


@pytest.mark.asyncio
async def test_start_scheduler_cleans_up_and_propagates_restore_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduler as scheduler_service
    from apscheduler.schedulers import asyncio as apscheduler_asyncio

    scheduler = MagicMock()
    monkeypatch.setattr(apscheduler_asyncio, "AsyncIOScheduler", MagicMock(return_value=scheduler))
    monkeypatch.setattr(
        scheduler_service,
        "restore_active_schedules",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(scheduler_service, "_scheduler", None)

    with capture_logs() as logs:
        with pytest.raises(RuntimeError, match="database unavailable"):
            await scheduler_service.start_scheduler()

    scheduler.shutdown.assert_called_once_with(wait=False)
    assert scheduler_service._scheduler is None
    failure = next(log for log in logs if log["event"] == "scheduler_start_failed")
    assert failure["request_id"] is None
    assert failure["user"] == "scheduler"
    assert failure["endpoint"] is None
    assert failure["status"] is None
    assert failure["duration_ms"] is None
    assert failure["method"] == "SCHEDULE"
    assert failure["client_ip"] is None


def test_add_schedule_job_uses_schedule_timezone_and_returns_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import scheduler as scheduler_service

    next_run = datetime(2026, 8, 31, 6, tzinfo=UTC)
    fake_scheduler = MagicMock()
    fake_scheduler.add_job.return_value = SimpleNamespace(next_run_time=next_run)
    monkeypatch.setattr(scheduler_service, "_scheduler", fake_scheduler)

    result = scheduler_service.add_schedule_job(
        schedule_id=uuid.uuid4(),
        endpoint_id=uuid.uuid4(),
        schedule_type="cron",
        cron_expression="0 6 * * *",
        timezone_name="Asia/Riyadh",
    )

    assert result == next_run
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert str(kwargs["timezone"]) == "Asia/Riyadh"
