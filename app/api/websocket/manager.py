"""
WebSocket connection manager for real-time credit data updates
"""
import asyncio
import json
from typing import List, Dict, Any
from datetime import datetime
from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"[WebSocket] Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"[WebSocket] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, event: str, data: Dict[str, Any]):
        if not self.active_connections:
            return

        message = json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, default=str)

        disconnected = []
        async with self._lock:
            for conn in self.active_connections:
                try:
                    await conn.send_text(message)
                except Exception as e:
                    logger.warning(f"[WebSocket] Send failed: {e}")
                    disconnected.append(conn)

            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)

    async def send_personal(self, websocket: WebSocket, event: str, data: Dict[str, Any]):
        message = json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }, default=str)

        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"[WebSocket] Personal send failed: {e}")

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


class Events:
    """WebSocket event types for credit analytics."""
    SPREAD_UPDATE = "spread_update"
    ALERT = "alert"
    ASSESSMENT_UPDATE = "assessment_update"
    RV_UPDATE = "rv_update"
    HEARTBEAT = "heartbeat"


# Singleton
_manager_instance: ConnectionManager = None


def get_manager() -> ConnectionManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConnectionManager()
    return _manager_instance
