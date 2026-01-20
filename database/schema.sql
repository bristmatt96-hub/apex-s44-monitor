-- Apex Credit Monitor Database Schema
-- For Supabase (PostgreSQL)

-- ============================================
-- COMPANIES TABLE
-- Core company information for XO constituents
-- ============================================
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    ticker VARCHAR(50),
    sector VARCHAR(100),
    sub_sector VARCHAR(100),
    country VARCHAR(100),

    -- Company details
    business_description TEXT,
    business_positives TEXT[],
    fatal_flaw TEXT,

    -- Ownership
    ownership_status VARCHAR(50), -- 'public', 'private', 'pe_backed'
    financial_sponsor VARCHAR(255),
    group_parent VARCHAR(255),

    -- Index membership
    itraxx_xo_series VARCHAR(20), -- e.g., 'S44', 'S43'
    index_weight DECIMAL(5,4),

    -- Lifecycle
    lifecycle_status VARCHAR(50), -- 'performing', 'stressed', 'distressed'
    distress_probability DECIMAL(5,2),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- DEBT_INSTRUMENTS TABLE
-- Individual bonds, loans, facilities
-- ============================================
CREATE TABLE IF NOT EXISTS debt_instruments (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    -- Instrument details
    instrument_name VARCHAR(255) NOT NULL,
    instrument_type VARCHAR(50), -- 'bond', 'loan', 'revolver', 'facility'
    seniority VARCHAR(50), -- 'senior_secured', 'senior_unsecured', 'subordinated'

    -- Terms
    currency VARCHAR(10),
    face_value DECIMAL(15,2),
    coupon_rate DECIMAL(6,4),
    coupon_type VARCHAR(20), -- 'fixed', 'floating'
    spread_bps INTEGER, -- For floating rate (e.g., E+375)

    -- Dates
    issue_date DATE,
    maturity_date DATE,
    first_call_date DATE,

    -- Identifiers
    isin VARCHAR(20),
    cusip VARCHAR(15),

    -- Ratings
    rating_moodys VARCHAR(10),
    rating_sp VARCHAR(10),
    rating_fitch VARCHAR(10),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- DEBT_PRICING TABLE
-- Daily/historical pricing for instruments
-- ============================================
CREATE TABLE IF NOT EXISTS debt_pricing (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES debt_instruments(id) ON DELETE CASCADE,

    price_date DATE NOT NULL,
    bid_price DECIMAL(8,4),
    ask_price DECIMAL(8,4),
    mid_price DECIMAL(8,4),

    -- Yields and spreads
    yield_to_worst DECIMAL(8,4),
    yield_to_maturity DECIMAL(8,4),
    spread_to_worst INTEGER, -- bps
    z_spread INTEGER, -- bps
    oas INTEGER, -- option-adjusted spread bps

    -- Source
    source VARCHAR(50), -- 'bloomberg', 'debtwire', 'manual'

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(instrument_id, price_date)
);

-- ============================================
-- CDS_PRICING TABLE
-- CDS spread data
-- ============================================
CREATE TABLE IF NOT EXISTS cds_pricing (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    price_date DATE NOT NULL,
    tenor VARCHAR(10), -- '5Y', '10Y'
    spread_bps INTEGER,

    -- Changes
    spread_change_1d INTEGER,
    spread_change_1w INTEGER,
    spread_change_1m INTEGER,

    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(company_id, price_date, tenor)
);

-- ============================================
-- FINANCIALS TABLE
-- Company financial metrics (quarterly/annual)
-- ============================================
CREATE TABLE IF NOT EXISTS financials (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    period_end DATE NOT NULL,
    period_type VARCHAR(10), -- 'Q1', 'Q2', 'Q3', 'Q4', 'FY', 'LTM'
    currency VARCHAR(10),

    -- Income Statement
    revenue DECIMAL(15,2),
    ebitda DECIMAL(15,2),
    ebitda_margin DECIMAL(6,4),
    ebit DECIMAL(15,2),
    interest_expense DECIMAL(15,2),
    net_income DECIMAL(15,2),

    -- Cash Flow
    cffo DECIMAL(15,2), -- Cash flow from operations
    capex DECIMAL(15,2),
    free_cash_flow DECIMAL(15,2),

    -- Balance Sheet
    total_debt DECIMAL(15,2),
    cash_and_equivalents DECIMAL(15,2),
    net_debt DECIMAL(15,2),
    total_assets DECIMAL(15,2),
    total_equity DECIMAL(15,2),

    -- Key Ratios
    leverage_ratio DECIMAL(6,2), -- Net Debt / EBITDA
    interest_coverage DECIMAL(6,2), -- EBITDA / Interest
    fcf_to_debt DECIMAL(6,4),

    -- Liquidity
    revolver_available DECIMAL(15,2),
    debt_due_one_year DECIMAL(15,2),

    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(company_id, period_end, period_type)
);

-- ============================================
-- MATURITY_SCHEDULE TABLE
-- Debt maturity wall
-- ============================================
CREATE TABLE IF NOT EXISTS maturity_schedule (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    as_of_date DATE NOT NULL,
    year INTEGER NOT NULL,
    amount DECIMAL(15,2),
    currency VARCHAR(10),

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(company_id, as_of_date, year)
);

-- ============================================
-- NEWS_ALERTS TABLE
-- Credit-relevant news and alerts
-- ============================================
CREATE TABLE IF NOT EXISTS news_alerts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    alert_date TIMESTAMP NOT NULL,
    source VARCHAR(100), -- 'twitter', 'rss', 'newsapi', 'manual'
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT,

    -- Classification
    alert_type VARCHAR(50), -- 'rating', 'earnings', 'regulatory', 'ma', 'restructuring'
    sentiment VARCHAR(20), -- 'positive', 'negative', 'neutral'
    priority VARCHAR(20), -- 'high', 'medium', 'low'

    -- Impact assessment
    spread_impact_est INTEGER, -- Estimated bps impact

    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- CREDIT_OPINIONS TABLE
-- Analyst opinions and recommendations
-- ============================================
CREATE TABLE IF NOT EXISTS credit_opinions (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,

    opinion_date DATE NOT NULL,
    analyst VARCHAR(100),

    -- Opinion
    summary TEXT,
    recommendation VARCHAR(50), -- 'overweight', 'underweight', 'neutral'

    -- Risks and catalysts
    key_risks TEXT[],
    key_catalysts TEXT[],

    -- Target levels
    target_spread INTEGER, -- bps

    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX idx_companies_sector ON companies(sector);
CREATE INDEX idx_companies_lifecycle ON companies(lifecycle_status);
CREATE INDEX idx_debt_instruments_company ON debt_instruments(company_id);
CREATE INDEX idx_debt_instruments_maturity ON debt_instruments(maturity_date);
CREATE INDEX idx_debt_pricing_date ON debt_pricing(price_date);
CREATE INDEX idx_cds_pricing_date ON cds_pricing(price_date);
CREATE INDEX idx_financials_period ON financials(period_end);
CREATE INDEX idx_news_alerts_date ON news_alerts(alert_date);
CREATE INDEX idx_news_alerts_company ON news_alerts(company_id);

-- ============================================
-- VIEWS
-- ============================================

-- Latest pricing view
CREATE OR REPLACE VIEW v_latest_pricing AS
SELECT
    c.name as company_name,
    c.sector,
    di.instrument_name,
    di.maturity_date,
    dp.price_date,
    dp.mid_price,
    dp.yield_to_worst,
    dp.spread_to_worst
FROM companies c
JOIN debt_instruments di ON c.id = di.company_id
JOIN debt_pricing dp ON di.id = dp.instrument_id
WHERE dp.price_date = (
    SELECT MAX(price_date)
    FROM debt_pricing
    WHERE instrument_id = di.id
);

-- Company summary view
CREATE OR REPLACE VIEW v_company_summary AS
SELECT
    c.id,
    c.name,
    c.sector,
    c.lifecycle_status,
    c.distress_probability,
    f.leverage_ratio,
    f.interest_coverage,
    f.total_debt,
    f.net_debt,
    f.ebitda,
    cds.spread_bps as cds_5y
FROM companies c
LEFT JOIN financials f ON c.id = f.company_id
    AND f.period_type = 'LTM'
    AND f.period_end = (SELECT MAX(period_end) FROM financials WHERE company_id = c.id AND period_type = 'LTM')
LEFT JOIN cds_pricing cds ON c.id = cds.company_id
    AND cds.tenor = '5Y'
    AND cds.price_date = (SELECT MAX(price_date) FROM cds_pricing WHERE company_id = c.id AND tenor = '5Y');
