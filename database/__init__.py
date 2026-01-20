"""
Database module for Apex Credit Monitor
"""

from .db import (
    Base,
    Company,
    DebtInstrument,
    DebtPricing,
    CDSPricing,
    Financial,
    NewsAlert,
    get_database_url,
    get_engine,
    get_session,
    init_database,
    get_or_create_company,
    get_company_by_name,
    get_all_companies,
    get_latest_financials,
    get_debt_instruments,
    get_latest_pricing,
    add_news_alert
)

__all__ = [
    'Base',
    'Company',
    'DebtInstrument',
    'DebtPricing',
    'CDSPricing',
    'Financial',
    'NewsAlert',
    'get_database_url',
    'get_engine',
    'get_session',
    'init_database',
    'get_or_create_company',
    'get_company_by_name',
    'get_all_companies',
    'get_latest_financials',
    'get_debt_instruments',
    'get_latest_pricing',
    'add_news_alert'
]
