# assumptions_engine.py
# This file takes the raw data from data_fetcher.py and automatically
# calculates smart default assumptions for the DCF valuation model.
# Every assumption has a data source label so the UI can show users
# where the number came from.

import pandas as pd
import numpy as np

# ============================================================
# MARKET CONSTANTS
# Used to calculate WACC based on which market the stock is from
# ============================================================

MARKET_CONSTANTS = {
    "IN": {  # India
        "risk_free_rate":       0.071,   # 10Y Indian Government Bond yield (~7.1%)
        "equity_risk_premium":  0.070,   # India ERP (~7%)
        "gdp_growth":           0.055,   # India long-run GDP growth (~5.5%)
        "statutory_tax_rate":   0.250,   # India corporate tax rate (25%)
    },
    "US": {  # United States
        "risk_free_rate":       0.043,   # 10Y US Treasury yield (~4.3%)
        "equity_risk_premium":  0.055,   # US ERP (~5.5%)
        "gdp_growth":           0.025,   # US long-run GDP growth (~2.5%)
        "statutory_tax_rate":   0.210,   # US corporate tax rate (21%)
    }
}


# ============================================================
# MASTER FUNCTION — this is what app.py and dcf_model.py call
# ============================================================

def get_assumptions(data):
    """
    Takes the full data dictionary from data_fetcher.py
    and returns a dictionary of smart default assumptions.

    Each assumption includes:
    - 'value':  the calculated default number
    - 'source': plain English explanation of how it was calculated
    - 'min':    minimum allowed value for the UI slider
    - 'max':    maximum allowed value for the UI slider

    Usage:
        data = get_stock_data("RELIANCE.NS")
        assumptions = get_assumptions(data)
        print(assumptions['wacc']['value'])  # e.g. 0.112
    """

    # Determine which market constants to use
    is_indian = data["meta"]["is_indian"]
    market    = "IN" if is_indian else "US"
    constants = MARKET_CONSTANTS[market]

    # Calculate each assumption independently
    revenue_growth  = _calc_revenue_growth(data)
    fcf_margin      = _calc_fcf_margin(data)
    wacc            = _calc_wacc(data, constants)
    terminal_growth = _calc_terminal_growth(constants)
    tax_rate        = _calc_tax_rate(data, constants)
    projection_years = {
        "value":  5,
        "source": "Industry standard DCF projection horizon",
        "options": [5, 7, 10]
    }

    return {
        "revenue_growth":   revenue_growth,
        "fcf_margin":       fcf_margin,
        "wacc":             wacc,
        "terminal_growth":  terminal_growth,
        "tax_rate":         tax_rate,
        "projection_years": projection_years,
        "market":           market,
        "constants":        constants,
    }


# ============================================================
# INDIVIDUAL ASSUMPTION CALCULATORS
# ============================================================

def _calc_revenue_growth(data):
    """
    Calculate revenue growth rate from historical data.
    Method: 3-year CAGR with a slight haircut for conservatism.
    Falls back to YoY growth if history is unavailable.
    """

    revenue_history = data["income_statement"]["revenue_history"]
    yoy_growth      = data["income_statement"]["revenue_growth_yoy"]

    # Try to calculate 3Y CAGR first (most reliable)
    if len(revenue_history) >= 2:
        try:
            # revenue_history is most-recent-first
            most_recent = revenue_history[0]["revenue"]
            oldest      = revenue_history[-1]["revenue"]
            years       = len(revenue_history) - 1

            if oldest and oldest > 0 and most_recent and most_recent > 0:
                cagr = (most_recent / oldest) ** (1 / years) - 1

                # Apply a haircut — high growers slow down over time
                # The higher the growth, the bigger the haircut
                if cagr > 0.30:
                    haircut = 0.25   # Aggressive growers: cut by 25%
                elif cagr > 0.15:
                    haircut = 0.15   # Moderate growers: cut by 15%
                else:
                    haircut = 0.05   # Slow growers: cut by 5%

                adjusted = cagr * (1 - haircut)

                # Cap between -10% and 40% — sanity check
                adjusted = max(-0.10, min(0.40, adjusted))

                return {
                    "value":  round(adjusted, 4),
                    "source": f"Based on {years}Y historical revenue CAGR of {cagr:.1%}, adjusted for sustainability",
                    "min":    -0.10,
                    "max":    0.40,
                    "raw_cagr": round(cagr, 4),
                }
        except Exception as e:
            print(f"Warning: CAGR calculation failed: {e}")

    # Fallback to YoY growth if available
    if yoy_growth is not None:
        # Apply same haircut logic
        adjusted = yoy_growth * 0.85  # 15% haircut on single-year growth
        adjusted = max(-0.10, min(0.40, adjusted))
        return {
            "value":  round(adjusted, 4),
            "source": "Based on most recent year-over-year revenue growth, adjusted",
            "min":    -0.10,
            "max":    0.40,
            "raw_cagr": round(yoy_growth, 4),
        }

    # Final fallback — conservative default
    return {
        "value":  0.08,
        "source": "Default assumption (historical data unavailable)",
        "min":    -0.10,
        "max":    0.40,
        "raw_cagr": None,
    }


def _calc_fcf_margin(data):
    """
    Calculate FCF margin from historical data.
    Method: Average FCF/Revenue ratio over last 3 years.
    FCF Margin = Free Cash Flow / Revenue
    """

    fcf_history     = data["cash_flow"]["fcf_history"]
    revenue_history = data["income_statement"]["revenue_history"]

    margins = []

    # Calculate FCF margin for each year we have both FCF and Revenue
    for i, fcf_entry in enumerate(fcf_history):
        if i < len(revenue_history):
            fcf     = fcf_entry.get("fcf")
            revenue = revenue_history[i].get("revenue")

            if fcf is not None and revenue and revenue > 0:
                margin = fcf / revenue
                # Only include reasonable margins (-50% to +60%)
                if -0.50 <= margin <= 0.60:
                    margins.append(margin)

    if margins:
        avg_margin = sum(margins) / len(margins)
        avg_margin = round(avg_margin, 4)

        # If FCF margin is negative flag it
        if avg_margin < 0:
            return {
                "value":  avg_margin,
                "source": f"Average FCF margin over {len(margins)} years (negative — company is cash flow negative)",
                "min":    -0.30,
                "max":    0.50,
                "is_negative": True,
            }

        return {
            "value":  avg_margin,
            "source": f"Average FCF margin over {len(margins)} year(s) of historical data",
            "min":    -0.30,
            "max":    0.50,
            "is_negative": False,
        }

    # Fallback — use net margin as proxy if available
    net_margin = data["income_statement"]["net_margin"]
    if net_margin is not None:
        # FCF is typically 80-90% of net income for asset-light companies
        proxy = round(net_margin * 0.85, 4)
        return {
            "value":  proxy,
            "source": "Estimated from net margin (FCF history unavailable)",
            "min":    -0.30,
            "max":    0.50,
            "is_negative": proxy < 0,
        }

    # Final fallback
    return {
        "value":  0.10,
        "source": "Default assumption (data unavailable)",
        "min":    -0.30,
        "max":    0.50,
        "is_negative": False,
    }


def _calc_wacc(data, constants):
    """
    Calculate WACC (Weighted Average Cost of Capital).

    Formula:
        WACC = (E/V × Cost of Equity) + (D/V × After-tax Cost of Debt)

    Cost of Equity uses CAPM:
        Ke = Risk-free Rate + Beta × Equity Risk Premium

    Cost of Debt:
        Kd = Interest Expense / Total Debt
        After-tax Kd = Kd × (1 - Tax Rate)
    """

    rf  = constants["risk_free_rate"]
    erp = constants["equity_risk_premium"]

    # --- Step 1: Cost of Equity via CAPM ---
    beta = data["price_data"]["beta"]

    if beta is None or beta <= 0:
        beta = 1.0  # Default to market beta if unavailable
        beta_source = "Beta defaulted to 1.0 (data unavailable)"
    elif beta > 3.0:
        beta = 3.0  # Cap extreme betas
        beta_source = f"Beta capped at 3.0 (raw beta was extreme)"
    else:
        beta_source = f"Beta: {beta:.2f} from market data"

    cost_of_equity = rf + beta * erp

    # --- Step 2: Cost of Debt ---
    total_debt     = data["balance_sheet"]["total_debt"]
    market_cap     = data["price_data"]["market_cap"]
    tax_rate       = _calc_tax_rate_value(data, constants)

    # Try to estimate cost of debt from balance sheet
    # We don't have interest expense directly so use a proxy
    # Investment grade Indian/US companies typically pay rf + 1.5-2.5%
    cost_of_debt_pretax  = rf + 0.020  # Assume 200bps spread over risk-free
    cost_of_debt_aftertax = cost_of_debt_pretax * (1 - tax_rate)

    # --- Step 3: Capital Structure Weights ---
    if total_debt and market_cap and (total_debt + market_cap) > 0:
        total_capital   = total_debt + market_cap
        equity_weight   = market_cap / total_capital
        debt_weight     = total_debt / total_capital

        # Sanity check — debt weight shouldn't exceed 80%
        debt_weight   = min(debt_weight, 0.80)
        equity_weight = 1 - debt_weight

        wacc = (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt_aftertax)
        structure_source = f"E/V: {equity_weight:.0%}, D/V: {debt_weight:.0%} from market data"

    else:
        # If we can't get capital structure, assume all-equity
        wacc = cost_of_equity
        structure_source = "Assumed all-equity (debt data unavailable)"

    # Cap WACC between 6% and 20% — sanity check
    wacc = max(0.06, min(0.20, wacc))
    wacc = round(wacc, 4)

    return {
        "value":  wacc,
        "source": f"CAPM-based. Rf: {rf:.1%}, ERP: {erp:.1%}, {beta_source}. {structure_source}",
        "min":    0.06,
        "max":    0.20,
        "cost_of_equity":       round(cost_of_equity, 4),
        "cost_of_debt_pretax":  round(cost_of_debt_pretax, 4),
        "beta_used":            round(beta, 2),
    }


def _calc_terminal_growth(constants):
    """
    Terminal growth rate = long-run GDP growth of home market.
    Logic: A company cannot grow faster than the overall economy forever.
    India → 5.5%, US → 2.5%
    """

    gdp_growth = constants["gdp_growth"]

    return {
        "value":  gdp_growth,
        "source": f"Set to long-run GDP growth rate of home market ({gdp_growth:.1%}). Terminal growth cannot exceed economy growth.",
        "min":    0.01,
        "max":    0.07,
    }


def _calc_tax_rate(data, constants):
    """
    Calculate effective tax rate from historical income statement data.
    Averages last 3 years, floors at statutory rate.
    """
    rate  = _calc_tax_rate_value(data, constants)
    floor = constants["statutory_tax_rate"]

    return {
        "value":  rate,
        "source": f"Effective tax rate from financials, floored at statutory rate ({floor:.0%})",
        "min":    0.05,
        "max":    0.45,
    }


def _calc_tax_rate_value(data, constants):
    """
    Internal helper — returns just the tax rate number.
    Used by both _calc_tax_rate and _calc_wacc.
    """
    floor = constants["statutory_tax_rate"]

    # Try to get from income statement data
    # yfinance doesn't give us tax rate directly so we use net/pretax income proxy
    net_margin      = data["income_statement"]["net_margin"]
    operating_margin = data["income_statement"]["operating_margin"]

    if net_margin and operating_margin and operating_margin > 0:
        # Rough proxy: implied tax burden from margin compression
        implied_rate = 1 - (net_margin / operating_margin)
        if 0.05 <= implied_rate <= 0.45:
            return round(max(implied_rate, floor), 4)

    # Fallback to statutory rate
    return floor


# ============================================================
# SCENARIO GENERATOR — Bull / Base / Bear
# ============================================================

def get_scenarios(assumptions):
    """
    Generates Bull, Base, and Bear scenario assumption sets
    from the base (auto-calculated) assumptions.

    Used for scenario analysis in the UI.
    """

    base_growth     = assumptions["revenue_growth"]["value"]
    base_fcf_margin = assumptions["fcf_margin"]["value"]
    base_wacc       = assumptions["wacc"]["value"]
    base_terminal   = assumptions["terminal_growth"]["value"]

    return {
        "bear": {
            "label":            "Bear Case",
            "revenue_growth":   round(base_growth * 0.50, 4),   # Half the base growth
            "fcf_margin":       round(base_fcf_margin * 0.80, 4), # 20% margin compression
            "wacc":             round(base_wacc * 1.15, 4),      # 15% higher discount rate
            "terminal_growth":  round(base_terminal * 0.60, 4),  # Lower terminal growth
            "color":            "#EF4444",  # Red
        },
        "base": {
            "label":            "Base Case",
            "revenue_growth":   base_growth,
            "fcf_margin":       base_fcf_margin,
            "wacc":             base_wacc,
            "terminal_growth":  base_terminal,
            "color":            "#3B82F6",  # Blue
        },
        "bull": {
            "label":            "Bull Case",
            "revenue_growth":   round(base_growth * 1.50, 4),    # 50% above base growth
            "fcf_margin":       round(base_fcf_margin * 1.20, 4), # 20% margin expansion
            "wacc":             round(base_wacc * 0.90, 4),       # 10% lower discount rate
            "terminal_growth":  round(base_terminal * 1.30, 4),   # Higher terminal growth
            "color":            "#10B981",  # Green
        },
    }


# ============================================================
# TEST BLOCK
# ============================================================

if __name__ == "__main__":

    # Import data fetcher for testing
    from data_fetcher import get_stock_data

    for ticker in ["RELIANCE.NS", "HDFCBANK.NS", "AAPL"]:
        print("\n" + "=" * 55)
        print(f"ASSUMPTIONS FOR {ticker}")
        print("=" * 55)

        data        = get_stock_data(ticker)

        if "error" in data:
            print(f"ERROR: {data['error']}")
            continue

        assumptions = get_assumptions(data)
        scenarios   = get_scenarios(assumptions)

        print(f"\n📈 Revenue Growth:   {assumptions['revenue_growth']['value']:.2%}")
        print(f"   Source: {assumptions['revenue_growth']['source']}")

        print(f"\n💰 FCF Margin:       {assumptions['fcf_margin']['value']:.2%}")
        print(f"   Source: {assumptions['fcf_margin']['source']}")

        print(f"\n⚖️  WACC:             {assumptions['wacc']['value']:.2%}")
        print(f"   Source: {assumptions['wacc']['source']}")

        print(f"\n🏁 Terminal Growth:  {assumptions['terminal_growth']['value']:.2%}")
        print(f"   Source: {assumptions['terminal_growth']['source']}")

        print(f"\n🧾 Tax Rate:         {assumptions['tax_rate']['value']:.2%}")
        print(f"   Source: {assumptions['tax_rate']['source']}")

        print(f"\n📊 Scenarios:")
        print(f"   Bear — Growth: {scenarios['bear']['revenue_growth']:.2%}, WACC: {scenarios['bear']['wacc']:.2%}")
        print(f"   Base — Growth: {scenarios['base']['revenue_growth']:.2%}, WACC: {scenarios['base']['wacc']:.2%}")
        print(f"   Bull — Growth: {scenarios['bull']['revenue_growth']:.2%}, WACC: {scenarios['bull']['wacc']:.2%}")