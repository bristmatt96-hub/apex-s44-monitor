"""
Master list of 80+ financial institutions to search for.

Each entry: (canonical_name, category, aliases)
Aliases are alternative spellings / abbreviations that appear in documents.
"""

FIRMS = [
    # ── Investment Banks ──────────────────────────────────────────────
    ("Goldman Sachs", "Investment Bank", ["GS", "Goldman"]),
    ("JP Morgan", "Investment Bank", ["JPMorgan", "J.P. Morgan", "JPM", "JP Morgan Chase"]),
    ("Morgan Stanley", "Investment Bank", ["MS", "Morgan Stanley & Co"]),
    ("Bank of America", "Investment Bank", ["BofA", "Merrill Lynch", "BofA Securities", "BAML"]),
    ("Citigroup", "Investment Bank", ["Citi", "Citibank", "Citicorp"]),
    ("Barclays", "Investment Bank", ["Barclays Capital", "BarCap"]),
    ("HSBC", "Investment Bank", ["HSBC Global Banking"]),
    ("Deutsche Bank", "Investment Bank", ["DB", "Deutsche"]),
    ("UBS", "Investment Bank", ["UBS AG", "UBS Group"]),
    ("Credit Suisse", "Investment Bank", ["CS", "Credit Suisse Group"]),
    ("BNP Paribas", "Investment Bank", ["BNPP", "BNP"]),
    ("Societe Generale", "Investment Bank", ["SocGen", "Société Générale", "SG"]),
    ("Nomura", "Investment Bank", ["Nomura Holdings", "Nomura International"]),
    ("Jefferies", "Investment Bank", ["Jefferies Group", "Jefferies LLC"]),
    ("Lazard", "Investment Bank", ["Lazard Freres", "Lazard Ltd"]),
    ("Rothschild", "Investment Bank", ["Rothschild & Co", "NM Rothschild"]),
    ("Evercore", "Investment Bank", ["Evercore Partners", "Evercore ISI"]),
    ("Moelis", "Investment Bank", ["Moelis & Company"]),
    ("PJT Partners", "Investment Bank", ["PJT"]),
    ("Houlihan Lokey", "Investment Bank", ["Houlihan"]),
    ("RBC Capital Markets", "Investment Bank", ["RBC", "Royal Bank of Canada"]),
    ("Macquarie", "Investment Bank", ["Macquarie Group", "Macquarie Capital"]),
    ("Natixis", "Investment Bank", ["Natixis CIB"]),
    ("ING", "Investment Bank", ["ING Bank", "ING Group"]),
    ("Standard Chartered", "Investment Bank", ["StanChart"]),
    ("UniCredit", "Investment Bank", ["UniCredit Bank"]),
    ("Commerzbank", "Investment Bank", []),

    # ── Hedge Funds ───────────────────────────────────────────────────
    ("Citadel", "Hedge Fund", ["Citadel LLC", "Citadel Securities"]),
    ("Bridgewater", "Hedge Fund", ["Bridgewater Associates"]),
    ("Two Sigma", "Hedge Fund", ["Two Sigma Investments", "TwoSigma"]),
    ("DE Shaw", "Hedge Fund", ["D.E. Shaw", "D. E. Shaw", "DE Shaw Group"]),
    ("Renaissance Technologies", "Hedge Fund", ["RenTech", "Renaissance"]),
    ("Point72", "Hedge Fund", ["Point72 Asset Management", "Point 72"]),
    ("Millennium Management", "Hedge Fund", ["Millennium", "Millennium Partners"]),
    ("AQR Capital", "Hedge Fund", ["AQR", "AQR Capital Management"]),
    ("Man Group", "Hedge Fund", ["Man GLG", "Man AHL", "Man Investments"]),
    ("Brevan Howard", "Hedge Fund", ["Brevan Howard Asset Management"]),
    ("BlueCrest Capital", "Hedge Fund", ["BlueCrest", "BlueCrest Capital Management"]),
    ("Cheyne Capital", "Hedge Fund", ["Cheyne Capital Management"]),
    ("CQS", "Hedge Fund", ["CQS New City", "CQS Investment Management"]),
    ("Algebris", "Hedge Fund", ["Algebris Investments"]),
    ("Marshall Wace", "Hedge Fund", ["Marshall Wace LLP"]),
    ("Capula Investment", "Hedge Fund", ["Capula", "Capula Investment Management"]),
    ("Winton Group", "Hedge Fund", ["Winton", "Winton Capital"]),
    ("Balyasny", "Hedge Fund", ["Balyasny Asset Management", "BAM"]),
    ("ExodusPoint", "Hedge Fund", ["ExodusPoint Capital"]),
    ("Sculptor Capital", "Hedge Fund", ["Sculptor", "Och-Ziff"]),
    ("Elliott Management", "Hedge Fund", ["Elliott", "Elliott Investment Management"]),
    ("Third Point", "Hedge Fund", ["Third Point LLC"]),
    ("Pershing Square", "Hedge Fund", ["Pershing Square Capital", "PSTH"]),
    ("Viking Global", "Hedge Fund", ["Viking Global Investors"]),
    ("Tiger Global", "Hedge Fund", ["Tiger Global Management"]),
    ("Lone Pine Capital", "Hedge Fund", ["Lone Pine"]),
    ("Coatue Management", "Hedge Fund", ["Coatue"]),
    ("Anchorage Capital", "Hedge Fund", ["Anchorage Capital Group"]),
    ("Saba Capital", "Hedge Fund", ["Saba Capital Management"]),
    ("Eisler Capital", "Hedge Fund", ["Eisler"]),
    ("Rokos Capital", "Hedge Fund", ["Rokos Capital Management"]),
    ("Segantii Capital", "Hedge Fund", ["Segantii"]),
    ("Schonfeld Strategic", "Hedge Fund", ["Schonfeld", "Schonfeld Strategic Advisors"]),

    # ── Private Equity ────────────────────────────────────────────────
    ("Blackstone", "Private Equity", ["Blackstone Group", "BX"]),
    ("KKR", "Private Equity", ["Kohlberg Kravis Roberts", "KKR & Co"]),
    ("Apollo Global", "Private Equity", ["Apollo", "Apollo Global Management"]),
    ("Carlyle Group", "Private Equity", ["Carlyle", "The Carlyle Group"]),
    ("TPG", "Private Equity", ["TPG Capital", "Texas Pacific Group"]),
    ("Bain Capital", "Private Equity", ["Bain"]),
    ("Warburg Pincus", "Private Equity", ["Warburg"]),
    ("CVC Capital", "Private Equity", ["CVC", "CVC Capital Partners"]),
    ("Permira", "Private Equity", ["Permira Advisers"]),
    ("EQT Partners", "Private Equity", ["EQT"]),
    ("Advent International", "Private Equity", ["Advent"]),
    ("Cinven", "Private Equity", ["Cinven Partners"]),
    ("Apax Partners", "Private Equity", ["Apax"]),
    ("Hellman & Friedman", "Private Equity", ["H&F", "Hellman Friedman"]),
    ("TDR Capital", "Private Equity", ["TDR"]),
    ("BC Partners", "Private Equity", []),
    ("PAI Partners", "Private Equity", ["PAI"]),
    ("Ardian", "Private Equity", ["Ardian Private Equity"]),

    # ── Asset Managers ────────────────────────────────────────────────
    ("BlackRock", "Asset Manager", ["BlackRock Inc", "BLK"]),
    ("Vanguard", "Asset Manager", ["Vanguard Group"]),
    ("Fidelity", "Asset Manager", ["Fidelity Investments", "FMR"]),
    ("PIMCO", "Asset Manager", ["Pacific Investment Management"]),
    ("State Street", "Asset Manager", ["State Street Global Advisors", "SSGA"]),
    ("Schroders", "Asset Manager", ["Schroders plc"]),
    ("Invesco", "Asset Manager", ["Invesco Ltd"]),
    ("T. Rowe Price", "Asset Manager", ["T Rowe Price"]),
    ("Wellington Management", "Asset Manager", ["Wellington"]),
    ("Amundi", "Asset Manager", ["Amundi Asset Management"]),
    ("M&G Investments", "Asset Manager", ["M&G", "M&G plc"]),
    ("Legal & General", "Asset Manager", ["LGIM", "Legal and General"]),
    ("Baillie Gifford", "Asset Manager", ["Baillie Gifford & Co"]),
    ("abrdn", "Asset Manager", ["Aberdeen", "Aberdeen Standard", "Aberdeen Asset Management"]),
    ("Muzinich", "Asset Manager", ["Muzinich & Co"]),
    ("BlueBay", "Asset Manager", ["BlueBay Asset Management"]),
    ("Tikehau Capital", "Asset Manager", ["Tikehau"]),
]


def get_all_firms():
    """Return list of (canonical_name, category, aliases) tuples."""
    return FIRMS


def build_search_index():
    """
    Build a dict mapping every lowercase search term → (canonical_name, category).
    Includes the canonical name itself and all aliases.
    """
    index = {}
    for name, category, aliases in FIRMS:
        index[name.lower()] = (name, category)
        for alias in aliases:
            index[alias.lower()] = (name, category)
    return index


def get_firm_count():
    """Return the number of unique firms in the list."""
    return len(FIRMS)
