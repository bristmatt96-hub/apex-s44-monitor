"""
Credit Catalyst API

FastAPI backend serving credit analytics endpoints.
Provides REST API and WebSocket for real-time spread/alert updates.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routers import assessments, analytics
from app.api.websocket.manager import get_manager, Events


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger.info("[CreditCatalyst] Starting API server...")
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    yield
    heartbeat_task.cancel()
    logger.info("[CreditCatalyst] API server stopped")


app = FastAPI(
    title="Credit Catalyst API",
    description="Credit analysis API for iTraxx Main and Crossover",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(assessments.router)
app.include_router(analytics.router)


# ── Health ───────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Credit Catalyst API",
        "version": "2.0.0",
    }


@app.get("/api/health")
async def health_check():
    components = {
        "analytics": Path("analytics").exists(),
        "agents": Path("agents").exists(),
        "monitors": Path("monitors").exists(),
        "snapshots": Path("snapshots").exists(),
        "knowledge": Path("knowledge").exists(),
    }
    return {
        "status": "healthy",
        "service": "Credit Catalyst API",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "components": components,
    }


# ── WebSocket ────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket for real-time updates.

    Events:
    - spread_update: CDS spread change
    - alert: Credit alert (rating action, filing, event)
    - heartbeat: Keep-alive every 30s
    """
    manager = get_manager()
    await manager.connect(websocket)

    try:
        await manager.send_personal(websocket, "connected", {
            "message": "Connected to Credit Catalyst",
        })

        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=60.0
                )
                if data == "ping":
                    await manager.send_personal(websocket, "pong", {})
            except asyncio.TimeoutError:
                await manager.send_personal(websocket, Events.HEARTBEAT, {
                    "connected": True,
                })

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"[WebSocket] Error: {e}")
        await manager.disconnect(websocket)


async def _heartbeat_loop():
    """Send periodic heartbeats to all connected clients."""
    manager = get_manager()
    while True:
        await asyncio.sleep(30)
        if manager.connection_count > 0:
            try:
                await manager.broadcast(Events.HEARTBEAT, {
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.error(f"[Heartbeat] Error: {e}")


# Broadcast helpers for monitors to push real-time data

async def broadcast_spread_update(entity: str, spread_bps: float, change_bps: float):
    """Push a spread change to all dashboard clients."""
    manager = get_manager()
    await manager.broadcast(Events.SPREAD_UPDATE, {
        "entity": entity,
        "spread_bps": spread_bps,
        "change_bps": change_bps,
        "timestamp": datetime.now().isoformat(),
    })


async def broadcast_credit_alert(entity: str, alert_type: str, message: str):
    """Push a credit alert to all dashboard clients."""
    manager = get_manager()
    await manager.broadcast(Events.ALERT, {
        "entity": entity,
        "alert_type": alert_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
