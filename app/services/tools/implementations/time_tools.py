"""
时间感知工具实现
"""
import json
from datetime import datetime
from typing import Optional
from app.services.tools.base import BaseTool, ToolResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetCurrentTimeTool(BaseTool):
    """获取当前时间工具"""

    name = "get_current_time"
    description = "获取当前系统时间，用于时间相关的判断和操作。"
    agent_type = "supervisor"
    parameters = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "时间格式，默认'%H:%M'返回如'12:00'格式",
                "default": "%H:%M"
            }
        }
    }

    async def execute(
        self,
        format: str = "%H:%M",
        **kwargs
    ) -> ToolResult:
        try:
            now = datetime.now()
            push_hours = [12, 18]
            current_hour = now.hour
            is_push_time = current_hour in push_hours

            result = {
                "current_time": now.strftime("%H:%M"),
                "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "hour": current_hour,
                "minute": now.minute,
                "is_push_time": is_push_time,
                "push_times": push_hours,
                "message": f"现在是{now.strftime('%H:%M')}"
            }

            if is_push_time:
                if current_hour == 12:
                    result["message"] = "现在是12:00，是午餐时间，适宜推送推荐视频"
                elif current_hour == 18:
                    result["message"] = "现在是18:00，是下班时间，适宜推送推荐视频"
                result["recommendation_triggered"] = True
            else:
                next_push = "12:00" if current_hour < 12 else "18:00"
                if current_hour >= 18:
                    next_push = "明天12:00"
                result["message"] += f"，下次推送时间是{next_push}"
                result["recommendation_triggered"] = False

            return ToolResult(
                success=True,
                message=json.dumps(result, ensure_ascii=False, indent=2)
            )

        except Exception as e:
            logger.error(f"获取当前时间失败: {e}")
            return ToolResult(success=False, message=f"获取当前时间失败: {str(e)}")


class CheckRecommendationNeededTool(BaseTool):
    """检查是否需要推送推荐工具"""

    name = "check_recommendation_needed"
    description = "检查当前时间是否是推送时间点，并返回相关信息。"
    agent_type = "supervisor"
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "用户会话ID"
            }
        },
        "required": ["session_id"]
    }

    async def execute(
        self,
        session_id: str,
        **kwargs
    ) -> ToolResult:
        try:
            now = datetime.now()
            current_hour = now.hour
            push_hours = [12, 18]
            should_push = current_hour in push_hours

            result = {
                "should_push": should_push,
                "current_time": now.strftime("%H:%M"),
                "hour": current_hour,
                "session_id": session_id,
                "message": ""
            }

            if should_push:
                time_label = "中午" if current_hour == 12 else "傍晚"
                result["message"] = f"现在是{time_label}推送时间，应该生成并推送推荐给用户"
            else:
                if current_hour < 12:
                    next_time = "12:00"
                elif current_hour < 18:
                    next_time = "18:00"
                else:
                    next_time = "明天12:00"
                result["message"] = f"现在不是推送时间，下次推送时间: {next_time}"

            return ToolResult(
                success=True,
                message=json.dumps(result, ensure_ascii=False, indent=2)
            )

        except Exception as e:
            logger.error(f"检查推荐时间失败: {e}")
            return ToolResult(success=False, message=f"检查推荐时间失败: {str(e)}")
