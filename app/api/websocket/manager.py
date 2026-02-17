"""
WebSocket connection manager for real-time dashboard updates
"""
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from fastapi import WebSocket
from loguru import logger
import json


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection"""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"[WebSocket] Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"[WebSocket] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, event: str, data: Dict[str, Any]):
        """Broadcast event to all connected clients"""
        if not self.active_connections:
            return

        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        # Convert to JSON
        message_json = json.dumps(message, default=str)

        # Send to all connections
        disconnected = []
        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message_json)
                except Exception as e:
                    logger.warning(f"[WebSocket] Failed to send to client: {e}")
                    disconnected.append(connection)

            # Clean up disconnected clients
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)

        if disconnected:
            logger.info(f"[WebSocket] Cleaned up {len(disconnected)} disconnected clients")

    async def send_personal(self, websocket: WebSocket, event: str, data: Dict[str, Any]):
        """Send message to specific client"""
        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.error(f"[WebSocket] Failed to send personal message: {e}")

    @property
    def connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)


# Event types
class Events:
    """WebSocket event types"""
    POSITION_UPDATE = "position_update"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    PNL_UPDATE = "pnl_update"
    OPPORTUNITY_NEW = "opportunity_new"
    OPPORTUNITY_UPDATE = "opportunity_update"
    TRADE_PENDING = "trade_pending"
    TRADE_EXECUTED = "trade_executed"
    TRADE_REJECTED = "trade_rejected"
    THESIS_UPDATE = "thesis_update"
    SYSTEM_STATUS = "system_status"
    HEARTBEAT = "heartbeat"


# Singleton instance
_manager_instance: ConnectionManager = None


def get_manager() -> ConnectionManager:
    """Get the WebSocket manager singleton"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConnectionManager()
    return _manager_instance
