"""
日志配置 - 使用loguru

修复循环导入：延迟导入 settings
"""
import sys
from loguru import logger
from app.services.security.cookies import redact_log_record

# 移除默认处理器
logger.remove()

# 添加控制台处理器（使用默认 DEBUG 级别，后续可动态调整）
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",  # 默认 DEBUG，可根据 settings.debug 调整
    filter=redact_log_record,
)

# 添加文件处理器
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    filter=redact_log_record,
)


def get_logger(name: str = "app"):
    """获取logger实例"""
    return logger

