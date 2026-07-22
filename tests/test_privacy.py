import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, FavoriteFolder, FavoriteVideo, RecommendationEvent, UserContentSignal,
    UserInterestProfile, UserSession, VideoCache,
)
from app.services.privacy import (
    delete_profile_evidence, delete_user_data, set_channel_participation,
)


def test_evidence_channel_and_account_deletion_are_scoped(tmp_path):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'privacy.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as db:
            db.add_all([
                UserSession(session_id="s", bili_uname="user", is_valid=True),
                UserInterestProfile(session_id="s", interest_tags={"RAG": 1.0}, profile_features={}),
                UserContentSignal(
                    signal_key="s:history:BV1", session_id="s", source="history",
                    item_type="video", item_id="BV1", title="RAG", strength=1.0,
                ),
                UserContentSignal(
                    signal_key="s:favorites:BV2", session_id="s", source="favorites",
                    item_type="video", item_id="BV2", title="LangGraph", strength=1.0,
                ),
                VideoCache(bvid="BVSHARED00001", title="shared"),
            ])
            folder = FavoriteFolder(session_id="s", media_id=1, title="private")
            db.add(folder)
            await db.flush()
            db.add(FavoriteVideo(folder_id=folder.id, bvid="BVSHARED00001"))
            db.add(RecommendationEvent(
                event_id="e", session_id="s", bvid="BV1", event_type="like",
            ))
            await db.commit()

            signal = (await db.execute(select(UserContentSignal).where(
                UserContentSignal.source == "history"
            ))).scalar_one()
            report = await delete_profile_evidence(db, "s", signal.id)
            assert report["source"] == "history"
            assert (await db.execute(select(func.count(UserContentSignal.id)))).scalar_one() == 1

            control = await set_channel_participation(db, "s", "favorites", False)
            assert control["paused_channels"] == ["favorites"]
            profile = (await db.execute(select(UserInterestProfile))).scalar_one()
            assert profile.profile_features["concept_affinities"] == {}

            cookie_report = await delete_user_data(db, "s", "cookies")
            assert cookie_report["counts"]["user_sessions_credentials_cleared"] == 1
            session = (await db.execute(select(UserSession))).scalar_one()
            assert session.is_valid is False

            all_report = await delete_user_data(db, "s", "all")
            assert all_report["counts"]["recommendation_events"] == 1
            assert (await db.execute(select(func.count(UserSession.id)))).scalar_one() == 0
            assert (await db.execute(select(func.count(FavoriteVideo.id)))).scalar_one() == 0
            # Shared content is not erased when one user's relationship is deleted.
            assert (await db.execute(select(func.count(VideoCache.id)))).scalar_one() == 1
        await engine.dispose()

    asyncio.run(scenario())
