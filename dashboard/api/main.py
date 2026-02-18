"""
APEX Trading Dashboard API

FastAPI backend for the trading dashboard.
Provides REST endpoints and WebSocket for real-time updates.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from dashboard.api.routers import positions, pnl
from dashboard.api.websocket.manager import get_manager, Events
from dashboard.api.services.coordinator_bridge import get_bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    logger.info("[Dashboard] Starting API server...")

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(heartbeat_loop())

    yield

    # Cleanup
    heartbeat_task.cancel()
    logger.info("[Dashboard] API server stopped")


app = FastAPI(
    title="APEX Trading Dashboard",
    description="Real-time trading dashboard API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Local Next.js dev
        "http://127.0.0.1:3000",
        "https://dashboard.apex.trade",  # Production domain
        "*"  # Allow all for development - restrict in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(positions.router)
app.include_router(pnl.router)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "APEX Trading Dashboard",
        "version": "1.0.0"
    }


@app.get("/api/health")
async def health_check():
    """Detailed health check"""
    bridge = get_bridge()
    ws_manager = get_manager()

    return {
        "status": "healthy",
        "coordinator_connected": bridge.is_connected(),
        "websocket_clients": ws_manager.connection_count
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Events sent:
    - position_update: When position P&L changes
    - position_opened: New position entered
    - position_closed: Position exited
    - pnl_update: Daily P&L recalculated
    - opportunity_new: High-score opportunity detected
    - heartbeat: Keep-alive every 30 seconds
    """
    manager = get_manager()
    await manager.connect(websocket)

    try:
        # Send initial data on connection
        bridge = get_bridge()

        await manager.send_personal(websocket, "connected", {
            "message": "Connected to APEX Dashboard",
            "coordinator_connected": bridge.is_connected()
        })

        # Send current positions
        positions = bridge.get_positions()
        await manager.send_personal(websocket, "initial_positions", {
            "positions": [p.model_dump() for p in positions]
        })

        # Send current P&L
        pnl = bridge.get_pnl_summary()
        await manager.send_personal(websocket, "initial_pnl", pnl.model_dump())

        # Keep connection alive and listen for client messages
        while True:
            try:
                # Wait for client message (ping/pong or commands)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # 60 second timeout
                )

                # Handle client commands if needed
                if data == "ping":
                    await manager.send_personal(websocket, "pong", {})

            except asyncio.TimeoutError:
                # Send keepalive if no message received
                await manager.send_personal(websocket, Events.HEARTBEAT, {
                    "connected": True
                })

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"[WebSocket] Error: {e}")
        await manager.disconnect(websocket)


async def heartbeat_loop():
    """Send periodic heartbeats to all connected clients"""
    manager = get_manager()

    while True:
        await asyncio.sleep(30)  # Every 30 seconds

        if manager.connection_count > 0:
            bridge = get_bridge()

            # Broadcast updated P&L
            try:
                pnl = bridge.get_pnl_summary()
                await manager.broadcast(Events.PNL_UPDATE, pnl.model_dump())
            except Exception as e:
                logger.error(f"[Heartbeat] Error broadcasting P&L: {e}")


# Function to broadcast position updates (called from trading system)
async def broadcast_position_update(symbol: str, position_data: dict):
    """Broadcast position update to all dashboard clients"""
    manager = get_manager()
    await manager.broadcast(Events.POSITION_UPDATE, {
        "symbol": symbol,
        **position_data
    })


async def broadcast_new_position(symbol: str, position_data: dict):
    """Broadcast new position opened"""
    manager = get_manager()
    await manager.broadcast(Events.POSITION_OPENED, {
        "symbol": symbol,
        **position_data
    })


async def broadcast_position_closed(symbol: str, pnl: float, pnl_pct: float):
    """Broadcast position closed"""
    manager = get_manager()
    await manager.broadcast(Events.POSITION_CLOSED, {
        "symbol": symbol,
        "pnl": pnl,
        "pnl_pct": pnl_pct
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
