# data_fetcher.py
# This file is responsible for pulling all raw financial data from Yahoo Finance
# using the yfinance library. Every other file in this project depends on this one.

import yfinance as yf
import pandas as pd

# ============================================================
# MAIN FUNCTION — this is what all other files will call
# ============================================================

def get_stock_data(ticker_symbol):
    """
    Master function that fetches all data for a given ticker.
    Returns a clean dictionary with everything the app needs.
    
    Usage:
        data = get_stock_data("AAPL")       # US stock
        data = get_stock_data("RELIANCE.NS") # Indian stock
    """

    print(f"Fetching data for {ticker_symbol}...")

    # Create the yfinance ticker object — this is our connection to Yahoo Finance
    ticker = yf.Ticker(ticker_symbol)

    # Pull the three core data sources from Yahoo Finance
    info        = _safe_info(ticker)
    financials  = _safe_financials(ticker)
    cashflow    = _safe_cashflow(ticker)
    balance     = _safe_balance(ticker)

    # If we couldn't get basic info, the ticker is probably wrong
    if not info:
        return {"error": f"Could not find data for ticker '{ticker_symbol}'. Check the symbol and try again."}

    # Build and return the master data dictionary
    return {
        "ticker":           ticker_symbol.upper(),
        "company_info":     _get_company_info(info),
        "price_data":       _get_price_data(info),
        "income_statement": _get_income_statement(info, financials),
        "balance_sheet":    _get_balance_sheet(info, balance),
        "cash_flow":        _get_cash_flow(cashflow),
        "valuation":        _get_valuation_multiples(info),
        "analyst":          _get_analyst_data(info),
        "market_signals":   _get_market_signals(info),
        "meta":             _get_meta(info, ticker_symbol),
    }


# ============================================================
# SECTION BUILDERS — each builds one slice of the dictionary
# ============================================================

def _get_company_info(info):
    """Basic identity information about the company."""
    return {
        "name":         _safe_get(info, "longName", "N/A"),
        "sector":       _safe_get(info, "sector", "N/A"),
        "industry":     _safe_get(info, "industry", "N/A"),
        "country":      _safe_get(info, "country", "N/A"),
        "description":  _safe_get(info, "longBusinessSummary", "N/A"),
        "employees":    _safe_get(info, "fullTimeEmployees", None),
        "website":      _safe_get(info, "website", "N/A"),
    }


def _get_price_data(info):
    """Current price and trading range data."""
    return {
        "current_price":    _safe_get(info, "currentPrice", None),
        "previous_close":   _safe_get(info, "previousClose", None),
        "day_high":         _safe_get(info, "dayHigh", None),
        "day_low":          _safe_get(info, "dayLow", None),
        "week_52_high":     _safe_get(info, "fiftyTwoWeekHigh", None),
        "week_52_low":      _safe_get(info, "fiftyTwoWeekLow", None),
        "market_cap":       _safe_get(info, "marketCap", None),
        "shares_outstanding": _safe_get(info, "sharesOutstanding", None),
        "beta":             _safe_get(info, "beta", None),
        "volume":           _safe_get(info, "volume", None),
        "avg_volume":       _safe_get(info, "averageVolume", None),
    }


def _get_income_statement(info, financials):
    """
    Revenue, earnings, and margin data.
    Pulls from both the info dict (TTM) and the financials table (historical).
    """
    # Historical annual revenue — last 3 years if available
    revenue_history = []
    if financials is not None and "Total Revenue" in financials.index:
        rev_row = financials.loc["Total Revenue"]
        # Each column is a year — take last 3, most recent first
        revenue_history = [
            {"year": str(col.year), "revenue": _clean_number(val)}
            for col, val in rev_row.items()
            if pd.notna(val)
        ][:3]

    # Historical EBITDA
    ebitda_history = []
    if financials is not None and "EBITDA" in financials.index:
        ebitda_row = financials.loc["EBITDA"]
        ebitda_history = [
            {"year": str(col.year), "ebitda": _clean_number(val)}
            for col, val in ebitda_row.items()
            if pd.notna(val)
        ][:3]

    return {
        # TTM (Trailing Twelve Months) figures — most current
        "revenue_ttm":          _safe_get(info, "totalRevenue", None),
        "gross_profit_ttm":     _safe_get(info, "grossProfits", None),
        "ebitda_ttm":           _safe_get(info, "ebitda", None),
        "net_income_ttm":       _safe_get(info, "netIncomeToCommon", None),
        "eps_ttm":              _safe_get(info, "trailingEps", None),
        "eps_forward":          _safe_get(info, "forwardEps", None),

        # Margins
        "gross_margin":         _safe_get(info, "grossMargins", None),
        "operating_margin":     _safe_get(info, "operatingMargins", None),
        "net_margin":           _safe_get(info, "profitMargins", None),
        "ebitda_margin":        _calculate_ebitda_margin(info),

        # Historical data for trend charts and CAGR calculations
        "revenue_history":      revenue_history,
        "ebitda_history":       ebitda_history,

        # Growth rates
        "revenue_growth_yoy":   _safe_get(info, "revenueGrowth", None),
        "earnings_growth_yoy":  _safe_get(info, "earningsGrowth", None),
    }


def _get_balance_sheet(info, balance):
    """Debt, equity, and asset data."""
    return {
        "total_debt":           _safe_get(info, "totalDebt", None),
        "total_cash":           _safe_get(info, "totalCash", None),
        "book_value_per_share": _safe_get(info, "bookValue", None),
        "debt_to_equity":       _safe_get(info, "debtToEquity", None),
        "current_ratio":        _safe_get(info, "currentRatio", None),
        "quick_ratio":          _safe_get(info, "quickRatio", None),
        "return_on_equity":     _safe_get(info, "returnOnEquity", None),
        "return_on_assets":     _safe_get(info, "returnOnAssets", None),
    }


def _get_cash_flow(cashflow):
    """
    Free Cash Flow data — critical for DCF valuation.
    FCF = Operating Cash Flow - Capital Expenditure
    """
    if cashflow is None:
        return {"fcf_history": [], "fcf_ttm": None}

    fcf_history = []

    try:
        # Operating cash flow row
        op_cf = None
        for label in ["Operating Cash Flow", "Total Cash From Operating Activities"]:
            if label in cashflow.index:
                op_cf = cashflow.loc[label]
                break

        # Capital expenditure row (usually negative in yfinance)
        capex = None
        for label in ["Capital Expenditure", "Capital Expenditures"]:
            if label in cashflow.index:
                capex = cashflow.loc[label]
                break

        if op_cf is not None:
            for col in list(op_cf.index)[:3]:  # Last 3 years
                op_val = op_cf[col] if pd.notna(op_cf[col]) else 0
                cap_val = capex[col] if (capex is not None and pd.notna(capex[col])) else 0
                fcf = op_val + cap_val  # capex is negative so we add it
                fcf_history.append({
                    "year": str(col.year),
                    "operating_cf": _clean_number(op_val),
                    "capex":        _clean_number(cap_val),
                    "fcf":          _clean_number(fcf),
                })

    except Exception as e:
        print(f"Warning: Could not calculate FCF history: {e}")

    # Most recent FCF as single number
    fcf_ttm = fcf_history[0]["fcf"] if fcf_history else None

    return {
        "fcf_history":  fcf_history,
        "fcf_ttm":      fcf_ttm,
    }


def _get_valuation_multiples(info):
    """Current market valuation ratios — used for comps analysis."""
    return {
        "pe_ratio_ttm":         _safe_get(info, "trailingPE", None),
        "pe_ratio_forward":     _safe_get(info, "forwardPE", None),
        "peg_ratio":            _safe_get(info, "pegRatio", None),
        "price_to_book":        _safe_get(info, "priceToBook", None),
        "price_to_sales":       _safe_get(info, "priceToSalesTrailing12Months", None),
        "ev_to_ebitda":         _safe_get(info, "enterpriseToEbitda", None),
        "ev_to_revenue":        _safe_get(info, "enterpriseToRevenue", None),
        "enterprise_value":     _safe_get(info, "enterpriseValue", None),
        "dividend_yield":       _safe_get(info, "dividendYield", None),
        "payout_ratio":         _safe_get(info, "payoutRatio", None),
    }


def _get_analyst_data(info):
    """Analyst price targets and recommendations."""
    return {
        "target_mean_price":    _safe_get(info, "targetMeanPrice", None),
        "target_high_price":    _safe_get(info, "targetHighPrice", None),
        "target_low_price":     _safe_get(info, "targetLowPrice", None),
        "recommendation":       _safe_get(info, "recommendationKey", None),
        "num_analyst_opinions": _safe_get(info, "numberOfAnalystOpinions", None),
    }


def _get_market_signals(info):
    """Short interest, insider ownership, and other market signals."""
    return {
        "short_ratio":              _safe_get(info, "shortRatio", None),
        "short_percent_of_float":   _safe_get(info, "shortPercentOfFloat", None),
        "held_by_insiders":         _safe_get(info, "heldPercentInsiders", None),
        "held_by_institutions":     _safe_get(info, "heldPercentInstitutions", None),
    }


def _get_meta(info, ticker_symbol):
    """
    Metadata about the stock — used by assumptions_engine.py
    to auto-detect company type and apply correct logic.
    """
    # Detect if Indian stock from ticker suffix
    is_indian = ticker_symbol.upper().endswith(".NS") or ticker_symbol.upper().endswith(".BO")

    currency = "INR" if is_indian else _safe_get(info, "currency", "USD")

    sector = _safe_get(info, "sector", "").lower()
    industry = _safe_get(info, "industry", "").lower()

    # Company type detection — used for weighting valuation methods
    is_bank       = "financial" in sector or "bank" in industry or "insurance" in industry
    is_tech       = "technology" in sector or "software" in industry or "saas" in industry
    div_yield     = _safe_get(info, "dividendYield", 0) or 0
    is_dividend   = div_yield > 0.03  # >3% yield = dividend company
    net_income    = _safe_get(info, "netIncomeToCommon", 1) or 1
    is_profitable = net_income > 0

    return {
        "is_indian":        is_indian,
        "currency":         currency,
        "is_bank":          is_bank,
        "is_tech":          is_tech,
        "is_dividend":      is_dividend,
        "is_profitable":    is_profitable,
        "sector":           _safe_get(info, "sector", "N/A"),
        "industry":         _safe_get(info, "industry", "N/A"),
    }


# ============================================================
# HELPER FUNCTIONS — internal utilities
# ============================================================

def _safe_get(dictionary, key, default):
    """
    Safely get a value from a dictionary.
    Returns default if key doesn't exist or value is None.
    """
    val = dictionary.get(key, default)
    return val if val is not None else default


def _safe_info(ticker):
    """Safely fetch ticker.info — returns None if it fails."""
    try:
        info = ticker.info
        # If yfinance returns an empty or near-empty dict, treat as failure
        if not info or len(info) < 5:
            return None
        return info
    except Exception as e:
        print(f"Warning: Could not fetch info: {e}")
        return None


def _safe_financials(ticker):
    """Safely fetch annual income statement."""
    try:
        return ticker.financials
    except Exception as e:
        print(f"Warning: Could not fetch financials: {e}")
        return None


def _safe_cashflow(ticker):
    """Safely fetch annual cash flow statement."""
    try:
        return ticker.cashflow
    except Exception as e:
        print(f"Warning: Could not fetch cashflow: {e}")
        return None


def _safe_balance(ticker):
    """Safely fetch balance sheet."""
    try:
        return ticker.balance_sheet
    except Exception as e:
        print(f"Warning: Could not fetch balance sheet: {e}")
        return None


def _clean_number(val):
    """Convert large numbers to float, return None if invalid."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _calculate_ebitda_margin(info):
    """Calculate EBITDA margin from available data."""
    ebitda   = _safe_get(info, "ebitda", None)
    revenue  = _safe_get(info, "totalRevenue", None)
    if ebitda and revenue and revenue != 0:
        return ebitda / revenue
    return None


# ============================================================
# TEST BLOCK — runs only when you execute this file directly
# ============================================================

if __name__ == "__main__":
    # Test with Apple (US stock)
    print("=" * 50)
    print("TESTING WITH AAPL (US Stock)")
    print("=" * 50)
    data = get_stock_data("AAPL")

    if "error" in data:
        print(f"ERROR: {data['error']}")
    else:
        print(f"Company:       {data['company_info']['name']}")
        print(f"Sector:        {data['company_info']['sector']}")
        print(f"Current Price: {data['price_data']['current_price']}")
        print(f"Market Cap:    {data['price_data']['market_cap']}")
        print(f"Revenue TTM:   {data['income_statement']['revenue_ttm']}")
        print(f"EBITDA TTM:    {data['income_statement']['ebitda_ttm']}")
        print(f"Net Margin:    {data['income_statement']['net_margin']}")
        print(f"FCF (TTM):     {data['cash_flow']['fcf_ttm']}")
        print(f"P/E Ratio:     {data['valuation']['pe_ratio_ttm']}")
        print(f"EV/EBITDA:     {data['valuation']['ev_to_ebitda']}")
        print(f"Is Indian:     {data['meta']['is_indian']}")
        print(f"Is Bank:       {data['meta']['is_bank']}")
        print(f"Is Profitable: {data['meta']['is_profitable']}")
        print(f"\nRevenue History:")
        for r in data['income_statement']['revenue_history']:
            print(f"  {r['year']}: {r['revenue']:,.0f}")
        print(f"\nFCF History:")
        for f in data['cash_flow']['fcf_history']:
            print(f"  {f['year']}: FCF = {f['fcf']:,.0f}")

    # Test with an Indian stock
    print("\n" + "=" * 50)
    print("TESTING WITH INFY.NS (Indian Stock)")
    print("=" * 50)
    data_india = get_stock_data("INFY.NS")

    if "error" in data_india:
        print(f"ERROR: {data_india['error']}")
    else:
        print(f"Company:       {data_india['company_info']['name']}")
        print(f"Currency:      {data_india['meta']['currency']}")
        print(f"Current Price: {data_india['price_data']['current_price']}")
        print(f"Is Indian:     {data_india['meta']['is_indian']}")