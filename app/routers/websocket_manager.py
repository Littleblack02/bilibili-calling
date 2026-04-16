from typing import Dict, List
from fastapi import WebSocket
from datetime import datetime
import json
import asyncio
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # session_id -> [WebSocket connections]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # websocket -> session_id
        self.websocket_to_session: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """接受新连接"""
        await websocket.accept()

        if session_id not in self.active_connections:
            self.active_connections[session_id] = []

        self.active_connections[session_id].append(websocket)
        self.websocket_to_session[websocket] = session_id

        logger.info(f"WebSocket connected for session {session_id}")

    def disconnect(self, websocket: WebSocket):
        """断开连接"""
        session_id = self.websocket_to_session.get(websocket)

        if session_id and session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)

            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

        if websocket in self.websocket_to_session:
            del self.websocket_to_session[websocket]

        logger.info(f"WebSocket disconnected for session {session_id}")

    async def send_personal_message(self, message: dict, session_id: str):
        """向指定会话发送消息"""
        if session_id not in self.active_connections:
            return

        for connection in self.active_connections[session_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message to {session_id}: {e}")
                self.disconnect(connection)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        for session_id in list(self.active_connections.keys()):
            await self.send_personal_message(message, session_id)

    async def send_heartbeat(self):
        """发送心跳包"""
        message = {
            "type": "heartbeat",
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(message)

    def get_connection_count(self, session_id: str = None) -> int:
        """获取连接数"""
        if session_id:
            return len(self.active_connections.get(session_id, []))
        return sum(len(conns) for conns in self.active_connections.values())


# 全局连接管理器实例
manager = ConnectionManager()


async def heartbeat_loop(interval_seconds: int = 30):
    """心跳循环"""
    while True:
        try:
            await manager.send_heartbeat()
            await asyncio.sleep(interval_seconds)
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(interval_seconds)
