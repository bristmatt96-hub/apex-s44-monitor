"""
Watchlist Database

SQLite database for managing company watchlist and tracking credit events.

Schema Overview:
- companies: Core watchlist of monitored companies
- credit_ratings: Current and historical credit ratings
- filings: SEC filing history and analysis
- spread_history: Bond spread tracking
- alerts: Alert history and state
- trade_ideas: Generated trade opportunities
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class WatchlistDB:
    """SQLite database for credit catalyst watchlist management."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = "credit_catalyst.db"):
        """
        Initialize watchlist database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Companies watchlist - core table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT UNIQUE NOT NULL,
                    company_name TEXT NOT NULL,
                    cik TEXT,                          -- SEC CIK number
                    sector TEXT,
                    industry TEXT,
                    market_cap_millions REAL,

                    -- Credit profile
                    current_rating TEXT,               -- Latest credit rating
                    rating_agency TEXT,                -- Agency of current rating
                    rating_outlook TEXT,               -- Positive/Stable/Negative
                    is_investment_grade INTEGER,       -- 1 if IG, 0 if HY

                    -- Monitoring settings
                    priority INTEGER DEFAULT 1,        -- 1=low, 2=medium, 3=high
                    is_active INTEGER DEFAULT 1,       -- Active monitoring
                    notes TEXT,

                    -- Timestamps
                    added_date TEXT NOT NULL,
                    last_updated TEXT,
                    last_filing_check TEXT,
                    last_rating_check TEXT,
                    last_spread_check TEXT
                )
            """)

            # Credit ratings history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credit_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,

                    -- Rating details
                    agency TEXT NOT NULL,              -- moodys, sp, fitch
                    rating TEXT NOT NULL,
                    previous_rating TEXT,
                    outlook TEXT,
                    action_type TEXT,                  -- downgrade, upgrade, outlook_change, etc.

                    -- Analysis
                    notches_changed INTEGER,
                    is_fallen_angel INTEGER,           -- IG to HY transition

                    -- Metadata
                    action_date TEXT NOT NULL,
                    source_url TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (company_id) REFERENCES companies(id)
                )
            """)

            # SEC filings history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS filings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    cik TEXT,

                    -- Filing details
                    filing_type TEXT NOT NULL,         -- 8-K, 10-Q, etc.
                    accession_number TEXT UNIQUE,
                    filed_date TEXT NOT NULL,

                    -- Analysis
                    is_credit_relevant INTEGER,        -- Flagged as credit-relevant
                    credit_items TEXT,                 -- JSON list of credit-relevant items
                    ai_summary TEXT,                   -- AI-generated summary
                    severity_score INTEGER,            -- 1-10 severity rating

                    -- URLs
                    filing_url TEXT,

                    -- Processing state
                    is_processed INTEGER DEFAULT 0,
                    is_alerted INTEGER DEFAULT 0,

                    -- Timestamps
                    created_at TEXT NOT NULL,
                    processed_at TEXT,

                    FOREIGN KEY (company_id) REFERENCES companies(id)
                )
            """)

            # Bond spread history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS spread_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,

                    -- Spread data
                    spread_bps REAL NOT NULL,          -- Current spread in basis points
                    spread_change_1d REAL,
                    spread_change_5d REAL,
                    spread_change_20d REAL,
                    z_score REAL,                      -- Z-score vs historical

                    -- Bond details
                    cusip TEXT,
                    bond_maturity TEXT,

                    -- Source
                    data_source TEXT,
                    recorded_at TEXT NOT NULL,

                    FOREIGN KEY (company_id) REFERENCES companies(id)
                )
            """)

            # Alerts history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER,
                    ticker TEXT NOT NULL,

                    -- Alert details
                    alert_type TEXT NOT NULL,          -- rating, filing, spread, composite
                    severity TEXT NOT NULL,            -- low, medium, high, critical
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,

                    -- Source references
                    source_type TEXT,                  -- filing_id, rating_id, etc.
                    source_id INTEGER,

                    -- State
                    is_sent INTEGER DEFAULT 0,
                    sent_at TEXT,
                    is_acknowledged INTEGER DEFAULT 0,
                    acknowledged_at TEXT,

                    -- Timestamps
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (company_id) REFERENCES companies(id)
                )
            """)

            # Trade ideas generated from signals
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,

                    -- Trade structure
                    direction TEXT NOT NULL,           -- long, short
                    instrument TEXT NOT NULL,          -- put, call, stock
                    strategy TEXT,                     -- put_spread, straddle, etc.

                    -- Details
                    strike_price REAL,
                    expiration_date TEXT,
                    entry_price_range TEXT,            -- e.g., "1.50-2.00"

                    -- Thesis
                    catalyst TEXT NOT NULL,
                    thesis TEXT,

                    -- Risk/reward
                    risk_reward_ratio REAL,
                    max_loss_pct REAL,
                    target_return_pct REAL,
                    confidence_score INTEGER,          -- 1-10

                    -- State
                    status TEXT DEFAULT 'pending',     -- pending, entered, exited, expired
                    entry_price REAL,
                    exit_price REAL,
                    pnl_pct REAL,

                    -- Timestamps
                    created_at TEXT NOT NULL,
                    entered_at TEXT,
                    exited_at TEXT,

                    -- Source
                    alert_id INTEGER,

                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (alert_id) REFERENCES alerts(id)
                )
            """)

            # Create indexes for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_cik ON companies(cik)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_filings_date ON filings(filed_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ratings_ticker ON credit_ratings(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_unsent ON alerts(is_sent) WHERE is_sent = 0")

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    # ========== Company Watchlist Operations ==========

    def add_company(
        self,
        ticker: str,
        company_name: str,
        cik: Optional[str] = None,
        sector: Optional[str] = None,
        current_rating: Optional[str] = None,
        rating_agency: Optional[str] = None,
        priority: int = 1,
        notes: Optional[str] = None,
    ) -> int:
        """
        Add a company to the watchlist.

        Args:
            ticker: Stock ticker symbol
            company_name: Company name
            cik: SEC CIK number
            sector: Industry sector
            current_rating: Current credit rating
            rating_agency: Rating agency for current rating
            priority: Monitoring priority (1-3)
            notes: Additional notes

        Returns:
            Company ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            # Determine if investment grade
            is_ig = None
            if current_rating:
                ig_ratings = {'AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-',
                              'BBB+', 'BBB', 'BBB-',
                              'Aaa', 'Aa1', 'Aa2', 'Aa3', 'A1', 'A2', 'A3',
                              'Baa1', 'Baa2', 'Baa3'}
                is_ig = 1 if current_rating in ig_ratings else 0

            cursor.execute("""
                INSERT INTO companies (
                    ticker, company_name, cik, sector,
                    current_rating, rating_agency, is_investment_grade,
                    priority, notes, added_date, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker.upper(), company_name, cik, sector,
                current_rating, rating_agency, is_ig,
                priority, notes, now, now
            ))

            conn.commit()
            return cursor.lastrowid

    def get_company(self, ticker: str) -> Optional[Dict]:
        """Get company by ticker."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_watchlist(self) -> List[Dict]:
        """Get all active companies in watchlist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM companies
                WHERE is_active = 1
                ORDER BY priority DESC, ticker ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_watchlist_ciks(self) -> List[str]:
        """Get list of CIK numbers for active watchlist companies."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cik FROM companies
                WHERE is_active = 1 AND cik IS NOT NULL
            """)
            return [row['cik'] for row in cursor.fetchall()]

    def get_watchlist_tickers(self) -> List[str]:
        """Get list of tickers for active watchlist companies."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticker FROM companies
                WHERE is_active = 1
            """)
            return [row['ticker'] for row in cursor.fetchall()]

    def update_company(self, ticker: str, **kwargs) -> bool:
        """Update company fields."""
        if not kwargs:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            kwargs['last_updated'] = datetime.utcnow().isoformat()

            set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
            values = list(kwargs.values()) + [ticker.upper()]

            cursor.execute(f"""
                UPDATE companies SET {set_clause}
                WHERE ticker = ?
            """, values)

            conn.commit()
            return cursor.rowcount > 0

    def remove_company(self, ticker: str) -> bool:
        """Remove company from watchlist (soft delete)."""
        return self.update_company(ticker, is_active=0)

    # ========== Filing Operations ==========

    def add_filing(
        self,
        ticker: str,
        filing_type: str,
        filed_date: str,
        accession_number: Optional[str] = None,
        filing_url: Optional[str] = None,
        is_credit_relevant: bool = False,
        credit_items: Optional[str] = None,
    ) -> int:
        """Add a filing to the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            # Get company_id
            cursor.execute("SELECT id, cik FROM companies WHERE ticker = ?", (ticker.upper(),))
            row = cursor.fetchone()
            company_id = row['id'] if row else None
            cik = row['cik'] if row else None

            cursor.execute("""
                INSERT OR IGNORE INTO filings (
                    company_id, ticker, cik, filing_type, accession_number,
                    filed_date, filing_url, is_credit_relevant, credit_items,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_id, ticker.upper(), cik, filing_type, accession_number,
                filed_date, filing_url, 1 if is_credit_relevant else 0, credit_items,
                now
            ))

            conn.commit()
            return cursor.lastrowid

    def get_unprocessed_filings(self) -> List[Dict]:
        """Get filings that haven't been processed yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM filings
                WHERE is_processed = 0
                ORDER BY filed_date DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    # ========== Alert Operations ==========

    def add_alert(
        self,
        ticker: str,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        source_type: Optional[str] = None,
        source_id: Optional[int] = None,
    ) -> int:
        """Add an alert to the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()

            # Get company_id
            cursor.execute("SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),))
            row = cursor.fetchone()
            company_id = row['id'] if row else None

            cursor.execute("""
                INSERT INTO alerts (
                    company_id, ticker, alert_type, severity,
                    title, message, source_type, source_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_id, ticker.upper(), alert_type, severity,
                title, message, source_type, source_id, now
            ))

            conn.commit()
            return cursor.lastrowid

    def get_pending_alerts(self) -> List[Dict]:
        """Get alerts that haven't been sent yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alerts
                WHERE is_sent = 0
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def mark_alert_sent(self, alert_id: int) -> bool:
        """Mark an alert as sent."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            cursor.execute("""
                UPDATE alerts SET is_sent = 1, sent_at = ?
                WHERE id = ?
            """, (now, alert_id))
            conn.commit()
            return cursor.rowcount > 0

    # ========== Statistics ==========

    def get_watchlist_stats(self) -> Dict:
        """Get summary statistics for the watchlist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM companies WHERE is_active = 1")
            total = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as ig FROM companies WHERE is_active = 1 AND is_investment_grade = 1")
            ig_count = cursor.fetchone()['ig']

            cursor.execute("SELECT COUNT(*) as hy FROM companies WHERE is_active = 1 AND is_investment_grade = 0")
            hy_count = cursor.fetchone()['hy']

            cursor.execute("SELECT COUNT(*) as pending FROM alerts WHERE is_sent = 0")
            pending_alerts = cursor.fetchone()['pending']

            cursor.execute("SELECT COUNT(*) as today FROM filings WHERE date(filed_date) = date('now')")
            filings_today = cursor.fetchone()['today']

            return {
                'total_companies': total,
                'investment_grade': ig_count,
                'high_yield': hy_count,
                'pending_alerts': pending_alerts,
                'filings_today': filings_today,
            }


# Convenience function to create database
def init_database(db_path: str = "credit_catalyst.db") -> WatchlistDB:
    """Initialize and return a WatchlistDB instance."""
    return WatchlistDB(db_path)
