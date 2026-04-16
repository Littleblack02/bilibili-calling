"""
B站智能推荐外部调度器

功能：
- 每5分钟检查一次时间
- 预取时间（11:00, 17:00）：通知Agent提前检索视频并存入短期记忆
- 推送时间（12:00, 18:00）：通知Agent从短期记忆读取并推送

使用方法：
1. 确保服务已启动：python -m app.main
2. 运行调度器：python scripts/recommendation_scheduler.py
"""
import asyncio
import httpx
import json
from datetime import datetime
from loguru import logger
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings

# 配置
API_BASE_URL = "http://localhost:8000"
CHECK_INTERVAL_SECONDS = 300  # 5分钟检查一次

# 推送时间点（小时）
PUSH_HOURS = [12, 18]
# 预取时间点（比推送时间提前1小时）
PREFETCH_HOURS = [11, 17]


class RecommendationScheduler:
    """推荐调度器 - 检测时间，通知Agent执行预取或推送"""

    def __init__(self):
        self.prefetched_today = set()  # 今天已预取的时间点
        self.pushed_today = set()  # 今天已推送的时间点
        self.last_check = None
        logger.info("推荐调度器初始化完成")

    def reset_daily(self):
        """每天零点重置记录"""
        self.prefetched_today = set()
        self.pushed_today = set()
        logger.info("已重置每日记录")

    async def check_time(self) -> dict:
        """检查当前时间"""
        now = datetime.now()
        current_hour = now.hour
        current_time = now.strftime("%H:%M")

        is_prefetch_time = current_hour in PREFETCH_HOURS
        is_push_time = current_hour in PUSH_HOURS

        already_prefetched = current_hour in self.prefetched_today
        already_pushed = current_hour in self.pushed_today

        result = {
            "current_time": current_time,
            "hour": current_hour,
            "is_prefetch_time": is_prefetch_time,
            "is_push_time": is_push_time,
            "already_prefetched_today": already_prefetched,
            "already_pushed_today": already_pushed
        }

        if is_prefetch_time and not already_prefetched:
            result["action"] = "prefetch"
            result["message"] = f"现在是 {current_time}，是预取时间！请检索视频并存入短期记忆"
            result["should_trigger"] = True
        elif is_push_time and not already_pushed:
            result["action"] = "push"
            result["message"] = f"现在是 {current_time}，是推送时间！请从短期记忆读取并推送"
            result["should_trigger"] = True
        elif is_prefetch_time and already_prefetched:
            result["message"] = f"{current_time} 预取已完成，跳过"
            result["should_trigger"] = False
        elif is_push_time and already_pushed:
            result["message"] = f"{current_time} 已推送过，跳过"
            result["should_trigger"] = False
        else:
            # 计算下次时间
            if current_hour < 11:
                next_time = "11:00"
                next_action = "预取"
            elif current_hour < 12:
                next_time = "12:00"
                next_action = "推送"
            elif current_hour < 17:
                next_time = "17:00"
                next_action = "预取"
            elif current_hour < 18:
                next_time = "18:00"
                next_action = "推送"
            else:
                next_time = "明天11:00"
                next_action = "预取"
            result["message"] = f"现在不是关键时间点，下次{next_action}: {next_time}"
            result["should_trigger"] = False

        return result

    async def notify_agent_prefetch(self, session_id: str, current_time: str) -> dict:
        """通知Agent执行预取任务（检索视频并存入短期记忆）"""
        try:
            if current_time == "11:00":
                time_context = "现在是午餐前预取时间11:00"
                target_push = "12:00"
            else:
                time_context = "现在是下班前预取时间17:00"
                target_push = "18:00"

            message = f"""{time_context}，请执行B站视频预取任务：
            1. 使用 check_recommendation_needed 工具确认当前是预取时间
            2. 基于用户画像（收藏夹、追番、历史记录、稍后观看、影视收藏）检索推荐视频
            3. 生成15条个性化推荐
            4. 使用 save_prefetch_recommendations 工具将推荐存入短期记忆
            5. 存入成功后返回确认信息

            这些推荐将在{target_push}推送时间发送给用户。
            """

            logger.info(f"[{current_time}] 通知Agent执行预取任务（目标推送时间: {target_push}）...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{API_BASE_URL}/agent/chat",
                    json={
                        "session_id": session_id,
                        "message": message,
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        self.prefetched_today.add(datetime.now().hour)
                        logger.info(f"[{current_time}] Agent预取任务执行成功！")
                        return {
                            "success": True,
                            "action": "prefetch",
                            "message": "预取任务执行成功",
                            "target_push_time": target_push,
                            "answer": result.get("answer", "")[:500] if result.get("answer") else ""
                        }
                    else:
                        logger.error(f"Agent预取失败: {result.get('error')}")
                        return {
                            "success": False,
                            "action": "prefetch",
                            "error": result.get("error", "未知错误")
                        }
                else:
                    logger.error(f"Agent API调用失败: HTTP {response.status_code}")
                    return {
                        "success": False,
                        "action": "prefetch",
                        "error": f"HTTP {response.status_code}: {response.text[:200]}"
                    }

        except httpx.ConnectError:
            logger.error("无法连接到服务，请确保服务已启动")
            return {
                "success": False,
                "action": "prefetch",
                "error": "无法连接到服务 (python -m app.main)"
            }
        except Exception as e:
            logger.error(f"通知Agent预取失败: {e}")
            return {
                "success": False,
                "action": "prefetch",
                "error": str(e)
            }

    async def notify_agent_push(self, session_id: str, current_time: str) -> dict:
        """通知Agent执行推送任务（从短期记忆读取并推送）"""
        try:
            if current_time == "12:00":
                time_context = "现在是午餐推送时间12:00"
            else:
                time_context = "现在是下班推送时间18:00"

            message = f"""{time_context}，请执行B站视频推送任务：
            1. 使用 check_recommendation_needed 工具确认当前是推送时间
            2. 使用 get_prefetch_recommendations 工具从短期记忆读取预取的推荐视频
            3. 如果有预取数据，通过WebSocket将推荐推送给用户
            4. 如果没有预取数据，实时生成推荐并推送
            5. 推送完成后使用 clear_prefetch_cache 工具清除缓存
            6. 向用户展示推荐结果
            """

            logger.info(f"[{current_time}] 通知Agent执行推送任务...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{API_BASE_URL}/agent/chat",
                    json={
                        "session_id": session_id,
                        "message": message,
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        self.pushed_today.add(datetime.now().hour)
                        logger.info(f"[{current_time}] Agent推送任务执行成功！")
                        return {
                            "success": True,
                            "action": "push",
                            "message": "推送任务执行成功",
                            "answer": result.get("answer", "")[:500] if result.get("answer") else ""
                        }
                    else:
                        logger.error(f"Agent推送失败: {result.get('error')}")
                        return {
                            "success": False,
                            "action": "push",
                            "error": result.get("error", "未知错误")
                        }
                else:
                    logger.error(f"Agent API调用失败: HTTP {response.status_code}")
                    return {
                        "success": False,
                        "action": "push",
                        "error": f"HTTP {response.status_code}: {response.text[:200]}"
                    }

        except httpx.ConnectError:
            logger.error("无法连接到服务，请确保服务已启动")
            return {
                "success": False,
                "action": "push",
                "error": "无法连接到服务 (python -m app.main)"
            }
        except Exception as e:
            logger.error(f"通知Agent推送失败: {e}")
            return {
                "success": False,
                "action": "push",
                "error": str(e)
            }


async def main():
    """主函数"""
    print("=" * 70)
    print("B站智能推荐调度器（预取-推送模式）")
    print("=" * 70)
    print(f"检查间隔: {CHECK_INTERVAL_SECONDS}秒")
    print(f"预取时间点: {PREFETCH_HOURS} (推送前1小时)")
    print(f"推送时间点: {PUSH_HOURS}")
    print(f"API地址: {API_BASE_URL}")
    print("=" * 70)
    print()

    # session_id（可配置）
    session_id = "default_session"

    scheduler = RecommendationScheduler()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 调度器启动，等待关键时间点...")
    print(f"预取时间: {PREFETCH_HOURS[0]}:00, {PREFETCH_HOURS[1]}:00")
    print(f"推送时间: {PUSH_HOURS[0]}:00, {PUSH_HOURS[1]}:00\n")

    while True:
        try:
            # 1. 检查时间
            time_result = await scheduler.check_time()
            current_time = datetime.now().strftime("%H:%M:%S")

            if time_result.get("should_trigger"):
                action = time_result.get("action")
                print(f"[{current_time}] 检测到{action}时间: {time_result['current_time']}")

                if action == "prefetch":
                    print(f"[{current_time}] 正在通知Agent执行预取任务...")
                    agent_result = await scheduler.notify_agent_prefetch(session_id, time_result['current_time'])
                else:
                    print(f"[{current_time}] 正在通知Agent执行推送任务...")
                    agent_result = await scheduler.notify_agent_push(session_id, time_result['current_time'])

                if agent_result.get("success"):
                    print(f"[{current_time}] Agent {action}任务执行成功！")
                else:
                    print(f"[{current_time}] Agent {action}执行失败: {agent_result.get('error')}")
            else:
                print(f"[{current_time}] {time_result.get('message', '检查中...')}")

            # 检查是否需要重置每日记录
            now = datetime.now()
            if now.hour == 0 and scheduler.last_check and scheduler.last_check.hour == 23:
                scheduler.reset_daily()

            scheduler.last_check = now

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 异常: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    print("外部调度器")
    print("确保服务已启动: python -m app.main\n")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n调度器已停止")
