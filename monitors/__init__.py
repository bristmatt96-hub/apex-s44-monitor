"""
Credit Catalyst - Monitor Layer

Data ingestion monitors for credit-relevant information:
- regulatory_filings: EU filings (RNS, Companies House, ESMA)
- rating_actions: via ISDA agent and analyzer
- credit_events: Covenant breaches, ISDA triggers
- earnings: Earnings releases and SEC/EU filings
- earnings_sentiment: Transcript NLP analysis
- news_sentiment: Bond-moving news from RSS feeds
- social_sentiment: Twitter/X credit chatter
- market_data: CDS spreads, bond prices (via isda_news_checker)
"""
