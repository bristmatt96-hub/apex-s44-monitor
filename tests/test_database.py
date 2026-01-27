"""
P8: Tests for database ORM models and helper functions (database/db.py).

Uses SQLite in-memory database instead of PostgreSQL for fast, isolated tests.
Note: ARRAY columns (used for business_positives) are PostgreSQL-specific
and will be tested as String columns in SQLite.
"""

import pytest
from datetime import datetime, date
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, Column, Text
from sqlalchemy.orm import sessionmaker

from database.db import (
    Base,
    Company,
    DebtInstrument,
    DebtPricing,
    CDSPricing,
    Financial,
    NewsAlert,
    get_or_create_company,
    get_company_by_name,
    get_all_companies,
    get_latest_financials,
    get_debt_instruments,
    get_latest_pricing,
    add_news_alert,
)


# ============================================================
# SQLite test engine — replaces PostgreSQL for testing
# ============================================================


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing.

    The ARRAY → Text shim is applied in conftest.py so all columns
    are SQLite-compatible by the time this fixture runs.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ============================================================
# Company model tests
# ============================================================


class TestCompanyModel:
    def test_create_company(self, db_session):
        company = Company(name="Test Corp", sector="TMT", country="Germany")
        db_session.add(company)
        db_session.commit()

        result = db_session.query(Company).filter_by(name="Test Corp").first()
        assert result is not None
        assert result.name == "Test Corp"
        assert result.sector == "TMT"

    def test_company_unique_name(self, db_session):
        c1 = Company(name="UniqueTest")
        db_session.add(c1)
        db_session.commit()

        c2 = Company(name="UniqueTest")
        db_session.add(c2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_company_relationships_exist(self, db_session):
        company = Company(name="RelTest")
        db_session.add(company)
        db_session.commit()

        assert company.debt_instruments == []
        assert company.financials == []
        assert company.news_alerts == []


# ============================================================
# DebtInstrument model tests
# ============================================================


class TestDebtInstrumentModel:
    def test_create_instrument(self, db_session):
        company = Company(name="InstrumentTest")
        db_session.add(company)
        db_session.commit()

        instrument = DebtInstrument(
            company_id=company.id,
            instrument_name="Senior Secured TLB",
            instrument_type="Term Loan",
            seniority="Senior Secured",
            currency="EUR",
            face_value=500.0,
        )
        db_session.add(instrument)
        db_session.commit()

        result = db_session.query(DebtInstrument).first()
        assert result.instrument_name == "Senior Secured TLB"
        assert result.company_id == company.id

    def test_instrument_company_relationship(self, db_session):
        company = Company(name="RelInstrTest")
        db_session.add(company)
        db_session.commit()

        instrument = DebtInstrument(
            company_id=company.id, instrument_name="Bond A"
        )
        db_session.add(instrument)
        db_session.commit()

        assert instrument.company.name == "RelInstrTest"
        assert len(company.debt_instruments) == 1


# ============================================================
# Financial model tests
# ============================================================


class TestFinancialModel:
    def test_create_financial(self, db_session):
        company = Company(name="FinTest")
        db_session.add(company)
        db_session.commit()

        fin = Financial(
            company_id=company.id,
            period_end=date(2024, 12, 31),
            period_type="FY",
            revenue=2000.0,
            ebitda=800.0,
            total_debt=5000.0,
            leverage_ratio=6.25,
        )
        db_session.add(fin)
        db_session.commit()

        result = db_session.query(Financial).first()
        assert result.revenue == 2000.0
        assert result.leverage_ratio == 6.25


# ============================================================
# get_or_create_company
# ============================================================


class TestGetOrCreateCompany:
    def test_creates_new_company(self, db_session):
        company = get_or_create_company(db_session, "NewCo", sector="TMT")
        assert company is not None
        assert company.name == "NewCo"
        assert company.sector == "TMT"
        assert company.id is not None

    def test_returns_existing_company(self, db_session):
        c1 = get_or_create_company(db_session, "ExistingCo")
        c2 = get_or_create_company(db_session, "ExistingCo")
        assert c1.id == c2.id

    def test_does_not_duplicate(self, db_session):
        get_or_create_company(db_session, "NoDupCo")
        get_or_create_company(db_session, "NoDupCo")
        count = db_session.query(Company).filter_by(name="NoDupCo").count()
        assert count == 1


# ============================================================
# get_company_by_name
# ============================================================


class TestGetCompanyByName:
    def test_finds_company(self, db_session):
        db_session.add(Company(name="FindMe"))
        db_session.commit()

        result = get_company_by_name(db_session, "FindMe")
        assert result is not None
        assert result.name == "FindMe"

    def test_returns_none_for_unknown(self, db_session):
        result = get_company_by_name(db_session, "DoesNotExist")
        assert result is None


# ============================================================
# get_all_companies
# ============================================================


class TestGetAllCompanies:
    def test_empty_database(self, db_session):
        result = get_all_companies(db_session)
        assert result == []

    def test_returns_all(self, db_session):
        db_session.add(Company(name="Co1"))
        db_session.add(Company(name="Co2"))
        db_session.add(Company(name="Co3"))
        db_session.commit()

        result = get_all_companies(db_session)
        assert len(result) == 3


# ============================================================
# get_latest_financials
# ============================================================


class TestGetLatestFinancials:
    def test_returns_most_recent(self, db_session):
        company = Company(name="LatestFinCo")
        db_session.add(company)
        db_session.commit()

        # Add older financial
        fin_old = Financial(
            company_id=company.id,
            period_end=date(2023, 12, 31),
            period_type="FY",
            revenue=1000.0,
        )
        # Add newer financial
        fin_new = Financial(
            company_id=company.id,
            period_end=date(2024, 12, 31),
            period_type="FY",
            revenue=2000.0,
        )
        db_session.add_all([fin_old, fin_new])
        db_session.commit()

        result = get_latest_financials(db_session, company.id)
        assert result.period_end == date(2024, 12, 31)
        assert result.revenue == 2000.0

    def test_no_financials_returns_none(self, db_session):
        company = Company(name="NoFinCo")
        db_session.add(company)
        db_session.commit()

        result = get_latest_financials(db_session, company.id)
        assert result is None


# ============================================================
# get_debt_instruments
# ============================================================


class TestGetDebtInstruments:
    def test_returns_instruments_sorted_by_maturity(self, db_session):
        company = Company(name="DebtCo")
        db_session.add(company)
        db_session.commit()

        i1 = DebtInstrument(
            company_id=company.id,
            instrument_name="Bond 2028",
            maturity_date=date(2028, 6, 15),
        )
        i2 = DebtInstrument(
            company_id=company.id,
            instrument_name="Bond 2026",
            maturity_date=date(2026, 3, 1),
        )
        db_session.add_all([i1, i2])
        db_session.commit()

        result = get_debt_instruments(db_session, company.id)
        assert len(result) == 2
        assert result[0].instrument_name == "Bond 2026"  # Earlier maturity first

    def test_empty_result(self, db_session):
        company = Company(name="NoDebtCo")
        db_session.add(company)
        db_session.commit()

        result = get_debt_instruments(db_session, company.id)
        assert result == []


# ============================================================
# get_latest_pricing
# ============================================================


class TestGetLatestPricing:
    def test_returns_most_recent_price(self, db_session):
        company = Company(name="PricedCo")
        db_session.add(company)
        db_session.commit()

        instrument = DebtInstrument(
            company_id=company.id, instrument_name="Bond"
        )
        db_session.add(instrument)
        db_session.commit()

        p1 = DebtPricing(
            instrument_id=instrument.id,
            price_date=date(2024, 1, 1),
            mid_price=95.0,
        )
        p2 = DebtPricing(
            instrument_id=instrument.id,
            price_date=date(2024, 6, 1),
            mid_price=97.0,
        )
        db_session.add_all([p1, p2])
        db_session.commit()

        result = get_latest_pricing(db_session, instrument.id)
        assert result.mid_price == 97.0

    def test_no_pricing_returns_none(self, db_session):
        company = Company(name="NoPriceCo")
        db_session.add(company)
        db_session.commit()
        instrument = DebtInstrument(
            company_id=company.id, instrument_name="Bond"
        )
        db_session.add(instrument)
        db_session.commit()

        result = get_latest_pricing(db_session, instrument.id)
        assert result is None


# ============================================================
# add_news_alert
# ============================================================


class TestAddNewsAlert:
    def test_creates_alert(self, db_session):
        company = Company(name="AlertCo")
        db_session.add(company)
        db_session.commit()

        alert = add_news_alert(
            db_session,
            company.id,
            "Company files for bankruptcy",
            source="Reuters",
            alert_type="bankruptcy",
            priority="HIGH",
        )
        assert alert.id is not None
        assert alert.headline == "Company files for bankruptcy"
        assert alert.source == "Reuters"

    def test_default_alert_date(self, db_session):
        company = Company(name="DateCo")
        db_session.add(company)
        db_session.commit()

        alert = add_news_alert(db_session, company.id, "Test headline")
        assert alert.alert_date is not None

    def test_custom_alert_date(self, db_session):
        company = Company(name="CustomDateCo")
        db_session.add(company)
        db_session.commit()

        custom_date = datetime(2025, 1, 15, 10, 30)
        alert = add_news_alert(
            db_session,
            company.id,
            "Test headline",
            alert_date=custom_date,
        )
        assert alert.alert_date == custom_date
