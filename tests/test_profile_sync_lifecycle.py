import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ProfileSyncRun, UserContentSignal
from app.services.profile.sync import (
    begin_sync_run,
    complete_sync_run,
    fail_sync_run,
    upsert_sync_signal,
)


async def _factory(path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


def test_successful_full_snapshot_invalidates_missing_rows_and_retry_is_idempotent(tmp_path):
    async def scenario():
        engine, factory = await _factory(tmp_path / "snapshot.db")
        async with factory() as db:
            first = await begin_sync_run(
                db, session_id="s", channel="followings", request_key="initial"
            )
            for item_id in ("1", "2"):
                await upsert_sync_signal(
                    db, first, item_type="creator", item_id=item_id, title=item_id
                )
            await complete_sync_run(
                db, first, item_count=2, page_count=1, full_snapshot=True
            )
            await db.commit()

        async with factory() as db:
            second = await begin_sync_run(
                db, session_id="s", channel="followings", request_key="second"
            )
            retry = await begin_sync_run(
                db, session_id="s", channel="followings", request_key="second"
            )
            assert retry.run_id == second.run_id
            await upsert_sync_signal(
                db, second, item_type="creator", item_id="1", title="still followed"
            )
            invalidated = await complete_sync_run(
                db, second, item_count=1, page_count=1, full_snapshot=True
            )
            assert invalidated == 1
            await db.commit()

        async with factory() as db:
            rows = (await db.execute(select(UserContentSignal))).scalars().all()
            active = {row.item_id: row.is_active for row in rows}
            assert active == {"1": True, "2": False}
            assert len((await db.execute(select(ProfileSyncRun))).scalars().all()) == 2
        await engine.dispose()
    asyncio.run(scenario())


def test_failed_snapshot_and_successful_event_stream_never_invalidate_old_rows(tmp_path):
    async def scenario():
        engine, factory = await _factory(tmp_path / "failure.db")
        async with factory() as db:
            old_snapshot = UserContentSignal(
                signal_key="old-follow", session_id="s", source="followings",
                item_type="creator", item_id="1", is_active=True,
            )
            old_event = UserContentSignal(
                signal_key="old-history", session_id="s", source="history",
                item_type="video", item_id="BV1", is_active=True,
            )
            db.add_all([old_snapshot, old_event])
            await db.commit()

            failed = await begin_sync_run(
                db, session_id="s", channel="followings", request_key="failed"
            )
            await fail_sync_run(
                db, failed, status="rate_limited", capability_status="degraded",
                error_summary="HTTP 429", http_status=429,
            )
            events = await begin_sync_run(
                db, session_id="s", channel="history", request_key="events"
            )
            assert await complete_sync_run(
                db, events, item_count=0, page_count=1, full_snapshot=True
            ) == 0
            await db.commit()
        async with factory() as db:
            rows = (await db.execute(select(UserContentSignal))).scalars().all()
            assert all(row.is_active for row in rows)
        await engine.dispose()
    asyncio.run(scenario())
