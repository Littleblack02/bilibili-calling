"""
检查用户画像构建情况
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.profile.multi_source_profile_builder import MultiSourceProfileBuilder
from app.database import async_session_factory
from app.models import UserInterestProfile
from sqlalchemy import select


async def check_profile():
    """检查用户画像构建情况"""
    # 使用你之前登录的 session_id
    session_id = "61106df9-6925-474f-b91b-c6114cbd8156"

    print(f"\n[CHECK] 正在检查用户 {session_id} 的画像构建情况...\n")

    # 1. 检查数据库中存储的画像
    async with async_session_factory() as db:
        result = await db.execute(
            select(UserInterestProfile).where(UserInterestProfile.session_id == session_id)
        )
        profile = result.scalar_one_or_none()

        if profile:
            print("📊 数据库中存储的用户画像:")
            print(f"   兴趣标签数量: {len(profile.interest_tags or {})}")
            print(f"   追踪UP主数量: {len(profile.followed_ups or [])}")
            print(f"   总收藏视频: {profile.total_favorites}")
            print(f"   更新时间: {profile.updated_at}")

            if profile.interest_tags:
                print(f"\n   🔝 Top 10 兴趣标签:")
                sorted_tags = sorted(profile.interest_tags.items(), key=lambda x: x[1], reverse=True)[:10]
                for i, (tag, score) in enumerate(sorted_tags, 1):
                    print(f"      {i}. {tag}: {score:.3f}")
        else:
            print("❌ 数据库中没有找到用户画像")

    # 2. 重新构建画像，查看采集过程
    print(f"\n🔄 重新构建用户画像，查看采集详情...")

    builder = MultiSourceProfileBuilder()

    # 创建模拟的 bilibili 服务（不实际请求网络）
    from app.services.bilibili import BilibiliService

    # 尝试使用空 cookies 构建
    try:
        bilibili = BilibiliService()
        async with bilibili:
            data_sources = await builder._collect_all_sources(bilibili, session_id)

            print(f"\n📈 各通道采集情况:")
            total_videos = 0

            for source_name, videos in data_sources.items():
                count = len(videos)
                total_videos += count
                print(f"   {source_name}: {count} 个视频")

                # 显示前3个视频作为示例
                if videos:
                    print(f"      示例视频:")
                    for i, video in enumerate(videos[:3], 1):
                        title = video.get('title', 'Unknown')[:40]
                        source = video.get('source', 'Unknown')
                        print(f"         {i}. {title}... ({source})")

                    if count > 3:
                        print(f"         ... 还有 {count - 3} 个视频")

            print(f"\n   总计采集: {total_videos} 个视频")

            # 检查是否真的每个通道都采集到了10个视频
            print(f"\n📋 采集目标验证:")
            print(f"   收藏夹目标: {builder.MAX_FAVORITES} 个")
            print(f"   历史记录目标: {builder.MAX_HISTORY} 个")
            print(f"   稍后观看目标: {builder.MAX_WATCHLATER} 个")
            print(f"   影视收藏目标: {builder.MAX_CINEMA} 个")

            # 检查去重情况
            all_videos = builder._merge_and_deduplicate(data_sources)
            print(f"\n🔄 去重后总计: {len(all_videos)} 个唯一视频")

            # 分析每个通道的视频来源分布
            print(f"\n📊 视频来源分布:")
            source_count = {}
            for video in all_videos:
                source = video.get('source', 'unknown')
                source_count[source] = source_count.get(source, 0) + 1

            for source, count in sorted(source_count.items(), key=lambda x: x[1], reverse=True):
                print(f"   {source}: {count} 个")

    except Exception as e:
        print(f"❌ 重新构建画像失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_profile())