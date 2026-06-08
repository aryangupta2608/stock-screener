# dcf_model.py
# This file takes the data and assumptions from the previous two files
# and runs the actual DCF (Discounted Cash Flow) valuation math.
#
# DCF Logic:
# 1. Start with current Free Cash Flow
# 2. Project it forward N years using the revenue growth + FCF margin assumptions
# 3. Discount each year's FCF back to today using WACC
# 4. Add a Terminal Value (what the company is worth after year N)
# 5. Divide by shares outstanding = intrinsic value per share

import math

# ============================================================
# MASTER FUNCTION — called by app.py and composite_score.py
# ============================================================

def run_dcf(data, assumptions):
    """
    Runs a full DCF valuation and returns fair value per share.

    Takes:
        data        — from data_fetcher.get_stock_data()
        assumptions — from assumptions_engine.get_assumptions()

    Returns a dictionary with:
        fair_value_per_share  — the DCF intrinsic value
        current_price         — for comparison
        upside_downside       — % difference
        verdict               — Undervalued / Fairly Valued / Overvalued
        details               — year-by-year breakdown for UI display
    """

    # --- Pull inputs ---
    current_price    = data["price_data"]["current_price"]
    shares           = data["price_data"]["shares_outstanding"]
    revenue_ttm      = data["income_statement"]["revenue_ttm"]
    fcf_ttm          = data["cash_flow"]["fcf_ttm"]

    growth_rate      = assumptions["revenue_growth"]["value"]
    fcf_margin       = assumptions["fcf_margin"]["value"]
    wacc             = assumptions["wacc"]["value"]
    terminal_growth  = assumptions["terminal_growth"]["value"]
    tax_rate         = assumptions["tax_rate"]["value"]
    projection_years = assumptions["projection_years"]["value"]

    # --- Validate inputs ---
    validation = _validate_inputs(
        current_price, shares, revenue_ttm,
        fcf_ttm, wacc, terminal_growth
    )
    if validation["has_error"]:
        return {"error": validation["message"]}

    # --- Choose base FCF ---
    # If we have a real FCF TTM number, use it directly
    # Otherwise estimate it from revenue × FCF margin
    if fcf_ttm and fcf_ttm > 0:
        base_fcf    = fcf_ttm
        fcf_source  = "TTM Free Cash Flow"
    elif revenue_ttm and fcf_margin:
        base_fcf    = revenue_ttm * fcf_margin
        fcf_source  = "Estimated from Revenue × FCF Margin"
    else:
        return {"error": "Insufficient data to run DCF — no FCF or revenue data available."}

    # --- Project FCF year by year ---
    yearly_projections = []
    pv_sum = 0  # Sum of all discounted cash flows

    for year in range(1, projection_years + 1):
        # Grow FCF each year by growth rate
        projected_fcf = base_fcf * ((1 + growth_rate) ** year)

        # Discount it back to today's value
        # Formula: PV = FCF / (1 + WACC)^year
        discount_factor = (1 + wacc) ** year
        present_value   = projected_fcf / discount_factor

        pv_sum += present_value

        yearly_projections.append({
            "year":             year,
            "projected_fcf":    round(projected_fcf, 0),
            "discount_factor":  round(discount_factor, 4),
            "present_value":    round(present_value, 0),
        })

    # --- Terminal Value ---
    # What is the company worth after the projection period?
    # Gordon Growth Model: TV = FCF_final × (1 + terminal_growth) / (WACC - terminal_growth)
    final_fcf      = base_fcf * ((1 + growth_rate) ** projection_years)
    terminal_value = (final_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)

    # Discount terminal value back to today
    terminal_pv    = terminal_value / ((1 + wacc) ** projection_years)

    # --- Total Intrinsic Value ---
    total_equity_value   = pv_sum + terminal_pv

    # Convert to per share value
    fair_value_per_share = total_equity_value / shares

    # --- Add net cash (Enterprise Value → Equity Value bridge) ---
    # If company has more cash than debt, it adds to fair value per share
    total_cash = data["balance_sheet"]["total_cash"] or 0
    total_debt = data["balance_sheet"]["total_debt"] or 0
    net_cash   = total_cash - total_debt
    net_cash_per_share = net_cash / shares if shares else 0

    # Add net cash per share to get equity value
    fair_value_per_share = fair_value_per_share + net_cash_per_share

    # Sanity check — cap at 10x current price to avoid absurd outputs
    fair_value_per_share = min(fair_value_per_share, current_price * 10)
    fair_value_per_share = max(fair_value_per_share, 0)
    fair_value_per_share = round(fair_value_per_share, 2)

    # --- Upside / Downside ---
    upside = (fair_value_per_share - current_price) / current_price
    upside = round(upside, 4)

    # --- Verdict ---
    verdict = _get_verdict(upside)

    # --- TV as % of total value (important context for user) ---
    tv_percentage = (terminal_pv / (pv_sum + terminal_pv)) * 100

    return {
        "fair_value_per_share":  fair_value_per_share,
        "current_price":         current_price,
        "upside_downside":       upside,
        "verdict":               verdict["label"],
        "verdict_color":         verdict["color"],
        "verdict_emoji":         verdict["emoji"],

        # Breakdown for display
        "pv_of_cashflows":       round(pv_sum, 0),
        "terminal_value":        round(terminal_value, 0),
        "terminal_value_pv":     round(terminal_pv, 0),
        "tv_as_pct_of_total":    round(tv_percentage, 1),
        "net_cash_per_share":    round(net_cash_per_share, 2),
        "base_fcf":              round(base_fcf, 0),
        "fcf_source":            fcf_source,
        "yearly_projections":    yearly_projections,

        # Echo back assumptions used (for UI display)
        "assumptions_used": {
            "revenue_growth":   growth_rate,
            "fcf_margin":       fcf_margin,
            "wacc":             wacc,
            "terminal_growth":  terminal_growth,
            "projection_years": projection_years,
        }
    }


def run_dcf_scenario(data, assumptions, scenario):
    """
    Runs DCF for a specific scenario (bear/base/bull).
    Overrides the base assumptions with scenario-specific values.

    scenario — one entry from assumptions_engine.get_scenarios()
    e.g. scenarios['bear']
    """

    # Deep copy assumptions and override with scenario values
    scenario_assumptions = {
        **assumptions,
        "revenue_growth": {
            **assumptions["revenue_growth"],
            "value": scenario["revenue_growth"]
        },
        "fcf_margin": {
            **assumptions["fcf_margin"],
            "value": scenario["fcf_margin"]
        },
        "wacc": {
            **assumptions["wacc"],
            "value": scenario["wacc"]
        },
        "terminal_growth": {
            **assumptions["terminal_growth"],
            "value": scenario["terminal_growth"]
        },
    }

    result = run_dcf(data, scenario_assumptions)

    if "error" not in result:
        result["scenario_label"] = scenario["label"]
        result["scenario_color"] = scenario["color"]

    return result


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _validate_inputs(current_price, shares, revenue_ttm,
                     fcf_ttm, wacc, terminal_growth):
    """
    Checks that we have everything needed to run a DCF.
    Returns error message if something critical is missing.
    """

    if not current_price or current_price <= 0:
        return {"has_error": True, "message": "Current price unavailable."}

    if not shares or shares <= 0:
        return {"has_error": True, "message": "Shares outstanding unavailable."}

    if not revenue_ttm and not fcf_ttm:
        return {"has_error": True, "message": "Neither revenue nor FCF data available."}

    if wacc <= terminal_growth:
        return {
            "has_error": True,
            "message": f"WACC ({wacc:.1%}) must be greater than terminal growth rate ({terminal_growth:.1%}). Please adjust assumptions."
        }

    return {"has_error": False, "message": ""}


def _get_verdict(upside):
    """
    Converts upside/downside % into a human-readable verdict.
    Thresholds based on standard margin of safety principles.
    """

    if upside > 0.20:
        return {
            "label": "Undervalued",
            "emoji": "🟢",
            "color": "#10B981"  # Green
        }
    elif upside > -0.10:
        return {
            "label": "Fairly Valued",
            "emoji": "🟡",
            "color": "#F59E0B"  # Amber
        }
    else:
        return {
            "label": "Overvalued",
            "emoji": "🔴",
            "color": "#EF4444"  # Red
        }


# ============================================================
# TEST BLOCK
# ============================================================

if __name__ == "__main__":

    from data_fetcher import get_stock_data
    from assumptions_engine import get_assumptions, get_scenarios

    for ticker in ["RELIANCE.NS", "HDFCBANK.NS", "AAPL"]:
        print("\n" + "=" * 55)
        print(f"DCF VALUATION — {ticker}")
        print("=" * 55)

        data        = get_stock_data(ticker)

        if "error" in data:
            print(f"ERROR: {data['error']}")
            continue

        assumptions = get_assumptions(data)
        result      = run_dcf(data, assumptions)

        if "error" in result:
            print(f"DCF Error: {result['error']}")
            continue

        currency = data["meta"]["currency"]

        print(f"\n💰 Fair Value:     {currency} {result['fair_value_per_share']:,.2f}")
        print(f"📊 Current Price:  {currency} {result['current_price']:,.2f}")
        print(f"📈 Upside:         {result['upside_downside']:+.2%}")
        print(f"🏷️  Verdict:        {result['verdict_emoji']} {result['verdict']}")
        print(f"\n📋 Breakdown:")
        print(f"   PV of Cash Flows:  {currency} {result['pv_of_cashflows']:,.0f}")
        print(f"   Terminal Value PV: {currency} {result['terminal_value_pv']:,.0f}")
        print(f"   TV as % of Total:  {result['tv_as_pct_of_total']}%")
        print(f"   Net Cash/Share:    {currency} {result['net_cash_per_share']:,.2f}")
        print(f"   Base FCF Source:   {result['fcf_source']}")

        print(f"\n📅 Year-by-Year Projections:")
        for y in result["yearly_projections"]:
            print(f"   Year {y['year']}: FCF = {currency} {y['projected_fcf']:,.0f}  |  PV = {currency} {y['present_value']:,.0f}")

        # Run scenarios
        print(f"\n🎯 Scenario Analysis:")
        scenarios = get_scenarios(assumptions)
        for key in ["bear", "base", "bull"]:
            s_result = run_dcf_scenario(data, assumptions, scenarios[key])
            if "error" not in s_result:
                print(f"   {scenarios[key]['label']:12} Fair Value: {currency} {s_result['fair_value_per_share']:,.2f}  ({s_result['upside_downside']:+.2%})  {s_result['verdict_emoji']}")