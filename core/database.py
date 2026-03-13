"""
Credit Catalyst - Database Layer

Minimal database setup for storing:
- Credit assessments history
- Alert log
- Portfolio positions
- Spread history

Uses SQLAlchemy with SQLite by default, PostgreSQL in production.
"""

import os
from typing import Optional
from loguru import logger

try:
    from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text, Boolean
    from sqlalchemy.orm import declarative_base, sessionmaker, Session
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

from core.config import settings

Base = None
engine = None
SessionLocal = None

if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()

    class AssessmentRecord(Base):
        __tablename__ = "assessments"

        id = Column(Integer, primary_key=True, autoincrement=True)
        entity_name = Column(String, index=True)
        assessment_date = Column(DateTime)
        credit_score = Column(Float)
        fair_spread_bps = Column(Float)
        current_spread_bps = Column(Float, nullable=True)
        direction = Column(String)
        conviction = Column(Integer)
        summary = Column(Text)
        created_at = Column(DateTime)

    class AlertRecord(Base):
        __tablename__ = "alerts"

        id = Column(Integer, primary_key=True, autoincrement=True)
        entity_name = Column(String, index=True)
        alert_type = Column(String)
        priority = Column(String)
        headline = Column(String)
        detail = Column(Text, nullable=True)
        source = Column(String, nullable=True)
        timestamp = Column(DateTime)
        sent = Column(Boolean, default=False)

    class SpreadHistory(Base):
        __tablename__ = "spread_history"

        id = Column(Integer, primary_key=True, autoincrement=True)
        entity_name = Column(String, index=True)
        spread_bps = Column(Float)
        tenor = Column(String, default="5Y")
        timestamp = Column(DateTime)
        source = Column(String, nullable=True)


def init_db() -> Optional[Session]:
    """Initialize database connection and create tables."""
    global engine, SessionLocal

    if not SQLALCHEMY_AVAILABLE:
        logger.warning("SQLAlchemy not installed - database features disabled")
        return None

    try:
        engine = create_engine(settings.database.url, echo=settings.database.echo)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        logger.info("Database initialized: {}", settings.database.url)
        return SessionLocal()
    except Exception as e:
        logger.error("Database initialization failed: {}", e)
        return None


def get_session() -> Optional[Session]:
    """Get a database session."""
    if SessionLocal is None:
        return init_db()
    return SessionLocal()
