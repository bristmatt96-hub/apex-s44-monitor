"""
Database connection and models for Apex Credit Monitor
Uses SQLAlchemy with Supabase PostgreSQL
"""

import os
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text, ARRAY, ForeignKey, DECIMAL, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import streamlit as st

Base = declarative_base()

# ============================================
# MODELS
# ============================================

class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    ticker = Column(String(50))
    sector = Column(String(100))
    sub_sector = Column(String(100))
    country = Column(String(100))

    business_description = Column(Text)
    business_positives = Column(ARRAY(Text))
    fatal_flaw = Column(Text)

    ownership_status = Column(String(50))
    financial_sponsor = Column(String(255))
    group_parent = Column(String(255))

    itraxx_xo_series = Column(String(20))
    index_weight = Column(DECIMAL(5,4))

    lifecycle_status = Column(String(50))
    distress_probability = Column(DECIMAL(5,2))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    debt_instruments = relationship("DebtInstrument", back_populates="company", cascade="all, delete-orphan")
    financials = relationship("Financial", back_populates="company", cascade="all, delete-orphan")
    cds_pricing = relationship("CDSPricing", back_populates="company", cascade="all, delete-orphan")
    news_alerts = relationship("NewsAlert", back_populates="company", cascade="all, delete-orphan")


class DebtInstrument(Base):
    __tablename__ = 'debt_instruments'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'))

    instrument_name = Column(String(255), nullable=False)
    instrument_type = Column(String(50))
    seniority = Column(String(50))

    currency = Column(String(10))
    face_value = Column(DECIMAL(15,2))
    coupon_rate = Column(DECIMAL(6,4))
    coupon_type = Column(String(20))
    spread_bps = Column(Integer)

    issue_date = Column(Date)
    maturity_date = Column(Date)
    first_call_date = Column(Date)

    isin = Column(String(20))
    cusip = Column(String(15))

    rating_moodys = Column(String(10))
    rating_sp = Column(String(10))
    rating_fitch = Column(String(10))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="debt_instruments")
    pricing = relationship("DebtPricing", back_populates="instrument", cascade="all, delete-orphan")


class DebtPricing(Base):
    __tablename__ = 'debt_pricing'

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey('debt_instruments.id', ondelete='CASCADE'))

    price_date = Column(Date, nullable=False)
    bid_price = Column(DECIMAL(8,4))
    ask_price = Column(DECIMAL(8,4))
    mid_price = Column(DECIMAL(8,4))

    yield_to_worst = Column(DECIMAL(8,4))
    yield_to_maturity = Column(DECIMAL(8,4))
    spread_to_worst = Column(Integer)
    z_spread = Column(Integer)
    oas = Column(Integer)

    source = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('instrument_id', 'price_date'),)

    # Relationships
    instrument = relationship("DebtInstrument", back_populates="pricing")


class CDSPricing(Base):
    __tablename__ = 'cds_pricing'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'))

    price_date = Column(Date, nullable=False)
    tenor = Column(String(10))
    spread_bps = Column(Integer)

    spread_change_1d = Column(Integer)
    spread_change_1w = Column(Integer)
    spread_change_1m = Column(Integer)

    source = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('company_id', 'price_date', 'tenor'),)

    # Relationships
    company = relationship("Company", back_populates="cds_pricing")


class Financial(Base):
    __tablename__ = 'financials'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'))

    period_end = Column(Date, nullable=False)
    period_type = Column(String(10))
    currency = Column(String(10))

    revenue = Column(DECIMAL(15,2))
    ebitda = Column(DECIMAL(15,2))
    ebitda_margin = Column(DECIMAL(6,4))
    ebit = Column(DECIMAL(15,2))
    interest_expense = Column(DECIMAL(15,2))
    net_income = Column(DECIMAL(15,2))

    cffo = Column(DECIMAL(15,2))
    capex = Column(DECIMAL(15,2))
    free_cash_flow = Column(DECIMAL(15,2))

    total_debt = Column(DECIMAL(15,2))
    cash_and_equivalents = Column(DECIMAL(15,2))
    net_debt = Column(DECIMAL(15,2))
    total_assets = Column(DECIMAL(15,2))
    total_equity = Column(DECIMAL(15,2))

    leverage_ratio = Column(DECIMAL(6,2))
    interest_coverage = Column(DECIMAL(6,2))
    fcf_to_debt = Column(DECIMAL(6,4))

    revolver_available = Column(DECIMAL(15,2))
    debt_due_one_year = Column(DECIMAL(15,2))

    source = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('company_id', 'period_end', 'period_type'),)

    # Relationships
    company = relationship("Company", back_populates="financials")


class NewsAlert(Base):
    __tablename__ = 'news_alerts'

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'))

    alert_date = Column(DateTime, nullable=False)
    source = Column(String(100))
    headline = Column(Text, nullable=False)
    summary = Column(Text)
    url = Column(Text)

    alert_type = Column(String(50))
    sentiment = Column(String(20))
    priority = Column(String(20))

    spread_impact_est = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="news_alerts")


# ============================================
# DATABASE CONNECTION
# ============================================

def get_database_url():
    """Get database URL from Streamlit secrets or environment"""
    # Try Streamlit secrets first
    try:
        return st.secrets.get("DATABASE_URL")
    except Exception:
        pass

    # Try environment variable
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # Try to construct from individual secrets
    try:
        host = st.secrets.get("SUPABASE_HOST")
        password = st.secrets.get("SUPABASE_PASSWORD")
        if host and password:
            return f"postgresql://postgres:{password}@{host}:5432/postgres"
    except Exception:
        pass

    return None


def get_engine():
    """Create SQLAlchemy engine"""
    db_url = get_database_url()
    if not db_url:
        raise ValueError("Database URL not configured. Set DATABASE_URL or SUPABASE_HOST/SUPABASE_PASSWORD in secrets.")

    # Supabase requires SSL
    if "supabase" in db_url:
        return create_engine(db_url, connect_args={"sslmode": "require"})
    return create_engine(db_url)


def get_session():
    """Get a database session"""
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_database():
    """Initialize database tables"""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("Database tables created successfully!")


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_or_create_company(session, name: str, **kwargs) -> Company:
    """Get existing company or create new one"""
    company = session.query(Company).filter_by(name=name).first()
    if not company:
        company = Company(name=name, **kwargs)
        session.add(company)
        session.commit()
    return company


def get_company_by_name(session, name: str) -> Optional[Company]:
    """Get company by name"""
    return session.query(Company).filter_by(name=name).first()


def get_all_companies(session) -> List[Company]:
    """Get all companies"""
    return session.query(Company).all()


def get_latest_financials(session, company_id: int) -> Optional[Financial]:
    """Get most recent financials for a company"""
    return session.query(Financial)\
        .filter_by(company_id=company_id)\
        .order_by(Financial.period_end.desc())\
        .first()


def get_debt_instruments(session, company_id: int) -> List[DebtInstrument]:
    """Get all debt instruments for a company"""
    return session.query(DebtInstrument)\
        .filter_by(company_id=company_id)\
        .order_by(DebtInstrument.maturity_date)\
        .all()


def get_latest_pricing(session, instrument_id: int) -> Optional[DebtPricing]:
    """Get most recent pricing for an instrument"""
    return session.query(DebtPricing)\
        .filter_by(instrument_id=instrument_id)\
        .order_by(DebtPricing.price_date.desc())\
        .first()


def add_news_alert(session, company_id: int, headline: str, **kwargs) -> NewsAlert:
    """Add a news alert"""
    alert = NewsAlert(
        company_id=company_id,
        headline=headline,
        alert_date=kwargs.get('alert_date', datetime.utcnow()),
        **{k: v for k, v in kwargs.items() if k != 'alert_date'}
    )
    session.add(alert)
    session.commit()
    return alert
