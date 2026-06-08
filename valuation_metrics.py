# valuation_metrics.py
# This file calculates fair value estimates using market-based valuation methods.
# It complements dcf_model.py by providing relative valuation (comps) approaches.
#
# Methods implemented (v1.0 baseline):
#   1. P/E Comps          — Apply a reference P/E multiple to EPS
#   2. EV/EBITDA Comps    — Apply a reference EV/EBITDA multiple to EBITDA
#   3. 52-Week Positioning — Where does the current price sit in the 52W range?
#
# Every function returns the same shape dictionary so composite_score.py
# can treat all valuation outputs uniformly.

# ============================================================
# SECTOR P/E BENCHMARKS
# Rough median P/E ratios by sector — used when we can't pull live comps.
# These are conservative long-run averages, not peak multiples.
# Source: Historical S&P 500 sector medians (updated manually)
# ============================================================

SECTOR_PE = {
    "Technology":               28.0,
    "Consumer Cyclical":        22.0,
    "Communication Services":   20.0,
    "Healthcare":               22.0,
    "Financial Services":       14.0,
    "Industrials":              18.0,
    "Consumer Defensive":       20.0,
    "Energy":                   12.0,
    "Basic Materials":          14.0,
    "Real Estate":              30.0,   # REITs trade on different metrics
    "Utilities":                17.0,
    "N/A":                      18.0,   # Default if sector unknown
}

# Sector EV/EBITDA benchmarks — same logic as P/E above
SECTOR_EV_EBITDA = {
    "Technology":               20.0,
    "Consumer Cyclical":        13.0,
    "Communication Services":   12.0,
    "Healthcare":               15.0,
    "Financial Services":       11.0,   # Less meaningful for banks — use with caution
    "Industrials":              12.0,
    "Consumer Defensive":       13.0,
    "Energy":                   7.0,
    "Basic Materials":          8.0,
    "Real Estate":              18.0,
    "Utilities":                10.0,
    "N/A":                      12.0,   # Default
}


# ============================================================
# MASTER FUNCTION — called by app.py and composite_score.py
# ============================================================

def run_valuation_metrics(data):
    """
    Runs all three v1.0 valuation methods and returns their results.

    Takes:
        data — from data_fetcher.get_stock_data()

    Returns a dictionary with three keys:
        pe_comps        — P/E based fair value
        ev_ebitda       — EV/EBITDA based fair value
        week_52         — 52-week range positioning (no fair value, just context)

    Usage:
        data    = get_stock_data("AAPL")
        metrics = run_valuation_metrics(data)
        print(metrics['pe_comps']['fair_value_per_share'])
    """

    sector = data["company_info"]["sector"]

    return {
        "pe_comps":   _run_pe_comps(data, sector),
        "ev_ebitda":  _run_ev_ebitda(data, sector),
        "week_52":    _run_52_week(data),
    }


# ============================================================
# METHOD 1 — P/E COMPS
# ============================================================

def _run_pe_comps(data, sector):
    """
    Fair value using Price-to-Earnings multiple.

    Logic:
        Fair Value = EPS (TTM) × Reference P/E Multiple

    Reference P/E: we first try the stock's own forward P/E as a sanity check,
    then fall back to the sector median from our table above.

    Only valid if the company is profitable (positive EPS).
    """

    eps         = data["income_statement"]["eps_ttm"]
    net_income  = data["income_statement"]["net_income_ttm"]
    current_pe  = data["valuation"]["pe_ratio_ttm"]
    current_price = data["price_data"]["current_price"]

    # --- Guard: hide P/E entirely if company is loss-making ---
    if not eps or eps <= 0 or not net_income or net_income <= 0:
        return {
            "available":    False,
            "reason":       "P/E not applicable — company has negative earnings",
            "method":       "P/E Comps",
        }

    if not current_price:
        return {
            "available":    False,
            "reason":       "Current price unavailable",
            "method":       "P/E Comps",
        }

    # --- Select reference P/E multiple ---
    # Use sector median as the benchmark
    sector_pe = SECTOR_PE.get(sector, SECTOR_PE["N/A"])

    # If the stock's own P/E is available and reasonable, blend it in
    # This makes the estimate more company-specific
    if current_pe and 5 <= current_pe <= 80:
        # 40% weight on stock's own P/E, 60% on sector median
        # This avoids blindly using an extreme current multiple
        reference_pe = (0.40 * current_pe) + (0.60 * sector_pe)
        pe_source = (
            f"Blended: stock P/E ({current_pe:.1f}x) at 40% + "
            f"sector median ({sector_pe:.1f}x) at 60%"
        )
    else:
        # Stock P/E is extreme or unavailable — use sector median only
        reference_pe = sector_pe
        pe_source = f"Sector median P/E ({sector_pe:.1f}x) — stock P/E was unavailable or extreme"

    # --- Calculate fair value ---
    fair_value = round(eps * reference_pe, 2)

    # Sanity cap: fair value shouldn't be more than 5x or less than 0.1x current price
    fair_value = max(fair_value, current_price * 0.10)
    fair_value = min(fair_value, current_price * 5.0)

    upside = round((fair_value - current_price) / current_price, 4)
    verdict = _get_verdict(upside)

    return {
        "available":            True,
        "method":               "P/E Comps",
        "fair_value_per_share": fair_value,
        "current_price":        current_price,
        "upside_downside":      upside,
        "verdict":              verdict["label"],
        "verdict_color":        verdict["color"],
        "verdict_emoji":        verdict["emoji"],

        # Inputs used — shown in UI for transparency
        "eps_used":             eps,
        "reference_pe":         round(reference_pe, 1),
        "sector_median_pe":     sector_pe,
        "stock_pe":             current_pe,
        "pe_source":            pe_source,

        # For football field chart
        "range_low":            round(eps * sector_pe * 0.80, 2),   # 20% below
        "range_high":           round(eps * sector_pe * 1.20, 2),   # 20% above
    }


# ============================================================
# METHOD 2 — EV/EBITDA COMPS
# ============================================================

def _run_ev_ebitda(data, sector):
    """
    Fair value using Enterprise Value to EBITDA multiple.

    Logic:
        Implied EV    = EBITDA × Reference EV/EBITDA Multiple
        Implied Equity = Implied EV − Total Debt + Total Cash
        Fair Value/Share = Implied Equity / Shares Outstanding

    EV/EBITDA is more reliable than P/E for capital-intensive companies
    because it's unaffected by debt structure or tax rates.
    """

    ebitda          = data["income_statement"]["ebitda_ttm"]
    current_ev_mult = data["valuation"]["ev_to_ebitda"]
    total_debt      = data["balance_sheet"]["total_debt"] or 0
    total_cash      = data["balance_sheet"]["total_cash"] or 0
    shares          = data["price_data"]["shares_outstanding"]
    current_price   = data["price_data"]["current_price"]

    # --- Guard: EBITDA must be positive and meaningful ---
    if not ebitda or ebitda <= 0:
        return {
            "available":    False,
            "reason":       "EV/EBITDA not applicable — EBITDA is negative or unavailable",
            "method":       "EV/EBITDA Comps",
        }

    if not shares or shares <= 0:
        return {
            "available":    False,
            "reason":       "Shares outstanding unavailable",
            "method":       "EV/EBITDA Comps",
        }

    if not current_price:
        return {
            "available":    False,
            "reason":       "Current price unavailable",
            "method":       "EV/EBITDA Comps",
        }

    # --- Select reference EV/EBITDA multiple ---
    sector_mult = SECTOR_EV_EBITDA.get(sector, SECTOR_EV_EBITDA["N/A"])

    if current_ev_mult and 3 <= current_ev_mult <= 50:
        # Blend stock's own multiple with sector median (same logic as P/E)
        reference_mult = (0.40 * current_ev_mult) + (0.60 * sector_mult)
        mult_source = (
            f"Blended: stock EV/EBITDA ({current_ev_mult:.1f}x) at 40% + "
            f"sector median ({sector_mult:.1f}x) at 60%"
        )
    else:
        reference_mult = sector_mult
        mult_source = f"Sector median EV/EBITDA ({sector_mult:.1f}x) — stock multiple unavailable or extreme"

    # --- Calculate implied equity value ---
    implied_ev     = ebitda * reference_mult
    net_debt       = total_debt - total_cash           # Positive = net debt, Negative = net cash
    implied_equity = implied_ev - net_debt             # Bridge from EV to equity value

    # Guard against negative implied equity (heavily indebted company)
    if implied_equity <= 0:
        return {
            "available":    False,
            "reason":       "Implied equity value is negative — company has more debt than implied EV",
            "method":       "EV/EBITDA Comps",
        }

    fair_value = round(implied_equity / shares, 2)

    # Sanity cap
    fair_value = max(fair_value, current_price * 0.10)
    fair_value = min(fair_value, current_price * 5.0)

    upside  = round((fair_value - current_price) / current_price, 4)
    verdict = _get_verdict(upside)

    # Range: ±20% on the multiple for football field chart
    low_ev     = ebitda * sector_mult * 0.80
    high_ev    = ebitda * sector_mult * 1.20
    range_low  = round(max((low_ev  - net_debt) / shares, current_price * 0.10), 2)
    range_high = round(min((high_ev - net_debt) / shares, current_price * 5.0),  2)

    return {
        "available":            True,
        "method":               "EV/EBITDA Comps",
        "fair_value_per_share": fair_value,
        "current_price":        current_price,
        "upside_downside":      upside,
        "verdict":              verdict["label"],
        "verdict_color":        verdict["color"],
        "verdict_emoji":        verdict["emoji"],

        # Inputs used
        "ebitda_used":          ebitda,
        "reference_multiple":   round(reference_mult, 1),
        "sector_median_mult":   sector_mult,
        "stock_multiple":       current_ev_mult,
        "implied_ev":           round(implied_ev, 0),
        "net_debt":             round(net_debt, 0),
        "implied_equity":       round(implied_equity, 0),
        "mult_source":          mult_source,

        # For football field chart
        "range_low":            range_low,
        "range_high":           range_high,
    }


# ============================================================
# METHOD 3 — 52-WEEK RANGE POSITIONING
# ============================================================

def _run_52_week(data):
    """
    52-Week range positioning — not a fair value estimate, but useful context.

    Shows where the current price sits within its 52-week trading range.
    A stock near its 52-week low may be beaten down; near its high may be stretched.

    Returns a percentile (0% = at 52W low, 100% = at 52W high).
    Also returns a signal: Depressed / Fair Zone / Elevated
    """

    current_price = data["price_data"]["current_price"]
    week_52_high  = data["price_data"]["week_52_high"]
    week_52_low   = data["price_data"]["week_52_low"]

    # --- Guard: need all three values ---
    if not all([current_price, week_52_high, week_52_low]):
        return {
            "available":    False,
            "reason":       "52-week range data unavailable",
            "method":       "52-Week Range",
        }

    if week_52_high <= week_52_low:
        return {
            "available":    False,
            "reason":       "52-week high/low data appears corrupted",
            "method":       "52-Week Range",
        }

    # --- Calculate position ---
    price_range  = week_52_high - week_52_low
    position_pct = (current_price - week_52_low) / price_range   # 0.0 to 1.0

    # Clamp to 0–1 in case of data quirks
    position_pct = max(0.0, min(1.0, position_pct))

    # --- Midpoint as a rough fair value anchor ---
    # Not a rigorous valuation — just the midpoint of the trading range
    midpoint = round((week_52_high + week_52_low) / 2, 2)

    # --- Signal based on position ---
    if position_pct <= 0.25:
        signal       = "Depressed"
        signal_color = "#10B981"   # Green — potentially attractive entry
        signal_emoji = "🟢"
        signal_note  = "Trading near 52-week lows — may be oversold or facing headwinds"
    elif position_pct <= 0.75:
        signal       = "Fair Zone"
        signal_color = "#F59E0B"   # Amber — middle of the range
        signal_emoji = "🟡"
        signal_note  = "Trading in the middle of its 52-week range"
    else:
        signal       = "Elevated"
        signal_color = "#EF4444"   # Red — near highs, may be stretched
        signal_emoji = "🔴"
        signal_note  = "Trading near 52-week highs — momentum is strong but limited upside from range"

    # Distance from current price to high and low
    pct_from_low  = round((current_price - week_52_low)  / week_52_low,  4)
    pct_from_high = round((current_price - week_52_high) / week_52_high, 4)  # Will be negative

    return {
        "available":        True,
        "method":           "52-Week Range",

        # This method doesn't give a fair_value_per_share in the traditional sense
        # so we use the midpoint as a loose anchor for the football field chart
        "fair_value_per_share": midpoint,
        "current_price":    current_price,

        # Range data
        "week_52_high":     week_52_high,
        "week_52_low":      week_52_low,
        "midpoint":         midpoint,
        "position_pct":     round(position_pct, 4),   # 0 = at low, 1 = at high

        # Signal
        "signal":           signal,
        "signal_color":     signal_color,
        "signal_emoji":     signal_emoji,
        "signal_note":      signal_note,

        # Context
        "pct_from_low":     pct_from_low,
        "pct_from_high":    pct_from_high,

        # For football field chart
        "range_low":        week_52_low,
        "range_high":       week_52_high,
    }


# ============================================================
# SHARED HELPER — verdict label (same thresholds as dcf_model.py)
# ============================================================

def _get_verdict(upside):
    """
    Converts upside/downside % into a verdict label.
    Uses the same thresholds as dcf_model.py for consistency.
    """
    if upside > 0.20:
        return {"label": "Undervalued", "emoji": "🟢", "color": "#10B981"}
    elif upside > -0.10:
        return {"label": "Fairly Valued", "emoji": "🟡", "color": "#F59E0B"}
    else:
        return {"label": "Overvalued", "emoji": "🔴", "color": "#EF4444"}


# ============================================================
# TEST BLOCK
# ============================================================

if __name__ == "__main__":

    from data_fetcher import get_stock_data

    for ticker in ["AAPL", "RELIANCE.NS", "HDFCBANK.NS"]:
        print("\n" + "=" * 55)
        print(f"VALUATION METRICS — {ticker}")
        print("=" * 55)

        data = get_stock_data(ticker)

        if "error" in data:
            print(f"ERROR: {data['error']}")
            continue

        results  = run_valuation_metrics(data)
        currency = data["meta"]["currency"]

        # --- P/E Comps ---
        pe = results["pe_comps"]
        print(f"\n📊 P/E Comps:")
        if pe["available"]:
            print(f"   Fair Value:    {currency} {pe['fair_value_per_share']:,.2f}")
            print(f"   Current Price: {currency} {pe['current_price']:,.2f}")
            print(f"   Upside:        {pe['upside_downside']:+.2%}")
            print(f"   Verdict:       {pe['verdict_emoji']} {pe['verdict']}")
            print(f"   EPS Used:      {pe['eps_used']:.2f}")
            print(f"   P/E Used:      {pe['reference_pe']:.1f}x")
            print(f"   Source:        {pe['pe_source']}")
        else:
            print(f"   ⚠️  Not available: {pe['reason']}")

        # --- EV/EBITDA ---
        ev = results["ev_ebitda"]
        print(f"\n📊 EV/EBITDA Comps:")
        if ev["available"]:
            print(f"   Fair Value:    {currency} {ev['fair_value_per_share']:,.2f}")
            print(f"   Current Price: {currency} {ev['current_price']:,.2f}")
            print(f"   Upside:        {ev['upside_downside']:+.2%}")
            print(f"   Verdict:       {ev['verdict_emoji']} {ev['verdict']}")
            print(f"   EBITDA Used:   {currency} {ev['ebitda_used']:,.0f}")
            print(f"   Multiple Used: {ev['reference_multiple']:.1f}x")
            print(f"   Source:        {ev['mult_source']}")
        else:
            print(f"   ⚠️  Not available: {ev['reason']}")

        # --- 52-Week Range ---
        w52 = results["week_52"]
        print(f"\n📊 52-Week Range:")
        if w52["available"]:
            print(f"   Current Price: {currency} {w52['current_price']:,.2f}")
            print(f"   52W Low:       {currency} {w52['week_52_low']:,.2f}  (+{w52['pct_from_low']:.2%} from low)")
            print(f"   52W High:      {currency} {w52['week_52_high']:,.2f}  ({w52['pct_from_high']:.2%} from high)")
            print(f"   Position:      {w52['position_pct']:.0%} of range")
            print(f"   Signal:        {w52['signal_emoji']} {w52['signal']}")
            print(f"   Note:          {w52['signal_note']}")
        else:
            print(f"   ⚠️  Not available: {w52['reason']}")