"""
辅助工具函数
"""
import hashlib
import re
import uuid
from datetime import datetime
from typing import Optional


def generate_session_id() -> str:
    """生成唯一的会话ID"""
    return str(uuid.uuid4())


def calculate_hash(input_string: str, algorithm: str = "md5") -> str:
    """计算字符串哈希值"""
    if algorithm == "md5":
        return hashlib.md5(input_string.encode()).hexdigest()
    elif algorithm == "sha256":
        return hashlib.sha256(input_string.encode()).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除非法字符"""
    illegal_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(illegal_chars, '_', filename)
    sanitized = sanitized.strip()
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized


def extract_bvid(url_or_bvid: str) -> Optional[str]:
    """从B站URL或BV号中提取BV号"""
    if url_or_bvid.startswith("BV"):
        return url_or_bvid

    patterns = [
        r"/video/([BV][^/?]+)",
        r"bvid=([BV][^/&]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_bvid)
        if match:
            return match.group(1)

    return None


def parse_duration(seconds: int) -> str:
    """将秒数转换为可读时长"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
