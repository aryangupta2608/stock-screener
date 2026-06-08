# composite_score.py
# Combines DCF + P/E Comps + EV/EBITDA into a single weighted fair value.
# 52-week range is deliberately excluded from the composite — it's a
# momentum/sentiment signal, not an intrinsic value estimate.
#
# Flow:
#   1. Detect company type from data_fetcher metadata
#   2. Look up base weights for that company type
#   3. Zero out weights for any method that returned unavailable
#   4. Re-normalise remaining weights to sum to 100%
#   5. Compute weighted average fair value → verdict

# ============================================================
# WEIGHT TABLES — by company type
# Each row must conceptually sum to 1.0 across dcf + pe + ev_ebitda.
# Zeroing a method here has no effect — the re-normalisation step
# handles missing methods automatically at runtime.
# ============================================================

WEIGHTS = {
    #                     dcf     pe      ev_ebitda
    "mature":            (0.40,   0.35,   0.25),
    "growth_tech":       (0.55,   0.20,   0.25),
    "bank":              (0.35,   0.45,   0.20),   # EV/EBITDA less reliable for banks
    "loss_making":       (0.60,   0.00,   0.40),   # P/E meaningless when earnings negative
    "dividend_psu":      (0.35,   0.35,   0.30),
}

# Upside thresholds for the final verdict
UNDERVALUED_THRESHOLD =  0.20   # composite FV > 20% above current price
OVERVALUED_THRESHOLD  = -0.10   # composite FV > 10% below current price


# ============================================================
# MASTER FUNCTION — called by app.py
# ============================================================

def run_composite(dcf_result, metrics_result, data):
    """
    Builds the composite fair value from all available valuation methods.

    Parameters:
        dcf_result     — dict from dcf_model.run_dcf()
        metrics_result — dict from valuation_metrics.run_valuation_metrics()
        data           — dict from data_fetcher.get_stock_data()

    Returns:
        fair_value_per_share  — weighted composite intrinsic value
        current_price         — for comparison
        upside_downside       — (fair_value / current_price) - 1
        verdict               — "Undervalued" / "Fairly Valued" / "Overvalued"
        verdict_emoji         — matching emoji
        verdict_color         — hex colour for UI
        company_type          — detected type string (e.g. "mature")
        methods_used          — human-readable string e.g. "DCF (50%) · P/E (50%)"
        weight_breakdown      — per-method dict with fair_value + normalised weight
    """

    current_price = data["price_data"]["current_price"]

    if not current_price or current_price <= 0:
        return {"error": "Current price unavailable — cannot compute composite score."}

    # --- Step 1: detect company type → base weights ---
    company_type    = _detect_company_type(data)
    w_dcf, w_pe, w_ev = WEIGHTS[company_type]

    # --- Step 2: extract fair values from each method result ---
    dcf_fv = _extract_dcf_fv(dcf_result)
    pe_fv  = _extract_metric_fv(metrics_result, "pe_comps")
    ev_fv  = _extract_metric_fv(metrics_result, "ev_ebitda")

    # --- Step 3: zero out weight if method has no valid result ---
    if dcf_fv is None: w_dcf = 0.0
    if pe_fv  is None: w_pe  = 0.0
    if ev_fv  is None: w_ev  = 0.0

    total_weight = w_dcf + w_pe + w_ev

    if total_weight == 0:
        return {"error": "No valuation methods returned a usable result — cannot compute composite."}

    # --- Step 4: re-normalise weights to sum to 1.0 ---
    w_dcf_n = w_dcf / total_weight
    w_pe_n  = w_pe  / total_weight
    w_ev_n  = w_ev  / total_weight

    # --- Step 5: weighted average fair value ---
    composite_fv      = 0.0
    methods_used_list = []

    if dcf_fv is not None:
        composite_fv += dcf_fv * w_dcf_n
        methods_used_list.append(f"DCF ({w_dcf_n:.0%})")

    if pe_fv is not None:
        composite_fv += pe_fv * w_pe_n
        methods_used_list.append(f"P/E ({w_pe_n:.0%})")

    if ev_fv is not None:
        composite_fv += ev_fv * w_ev_n
        methods_used_list.append(f"EV/EBITDA ({w_ev_n:.0%})")

    composite_fv = round(composite_fv, 2)

    # --- Step 6: upside + verdict ---
    upside  = round((composite_fv - current_price) / current_price, 4)
    verdict = _get_verdict(upside)

    return {
        "fair_value_per_share":  composite_fv,
        "current_price":         current_price,
        "upside_downside":       upside,
        "verdict":               verdict["label"],
        "verdict_emoji":         verdict["emoji"],
        "verdict_color":         verdict["color"],
        "company_type":          company_type,
        "methods_used":          " · ".join(methods_used_list),

        # Per-method breakdown — useful for a tooltip or expanded view later
        "weight_breakdown": {
            "dcf":       {"fair_value": dcf_fv, "weight": round(w_dcf_n, 4)},
            "pe_comps":  {"fair_value": pe_fv,  "weight": round(w_pe_n,  4)},
            "ev_ebitda": {"fair_value": ev_fv,  "weight": round(w_ev_n,  4)},
        },
    }


# ============================================================
# COMPANY TYPE DETECTOR
# ============================================================

def _detect_company_type(data):
    """
    Returns one of: "mature", "growth_tech", "bank", "loss_making", "dividend_psu"

    Priority order matters:
        loss_making   — checked first (P/E is meaningless, overrides everything)
        bank          — capital structure makes EV metrics unreliable
        growth_tech   — high-growth tech: DCF-heavy, P/E less reliable
        dividend_psu  — high-yield dividend companies
        mature        — default for stable, profitable companies
    """

    meta      = data["meta"]
    income    = data["income_statement"]
    valuation = data["valuation"]

    is_profitable  = meta.get("is_profitable", True)
    is_bank        = meta.get("is_bank", False)
    is_tech        = meta.get("is_tech", False)
    div_yield      = valuation.get("dividend_yield") or 0
    revenue_growth = income.get("revenue_growth_yoy") or 0

    if not is_profitable:
        return "loss_making"

    if is_bank:
        return "bank"

    # High-growth tech: >20% revenue growth in tech sector
    if is_tech and revenue_growth > 0.20:
        return "growth_tech"

    # Dividend-heavy: >3% yield signals PSU/utility/REIT-like behaviour
    if div_yield > 0.03:
        return "dividend_psu"

    return "mature"


# ============================================================
# SAFE EXTRACTORS — handle the different result shapes
# ============================================================

def _extract_dcf_fv(dcf_result):
    """
    Pulls fair_value_per_share from a dcf_model result dict.
    Returns None if DCF errored or is missing.
    """
    if not dcf_result or "error" in dcf_result:
        return None
    fv = dcf_result.get("fair_value_per_share")
    # Reject obviously bad values
    if fv is None or fv <= 0:
        return None
    return fv


def _extract_metric_fv(metrics_result, method_key):
    """
    Pulls fair_value_per_share from a valuation_metrics result dict.
    Returns None if the method was marked unavailable or errored.

    Note: 52-week range also has a fair_value_per_share (the midpoint)
    but we intentionally don't call this for week_52 — it's not an
    intrinsic value and would distort the composite.
    """
    if not metrics_result:
        return None
    result = metrics_result.get(method_key, {})
    # Both "available: False" and missing key are handled here
    if not result.get("available", False):
        return None
    fv = result.get("fair_value_per_share")
    if fv is None or fv <= 0:
        return None
    return fv


# ============================================================
# VERDICT HELPER
# ============================================================

def _get_verdict(upside):
    """Same thresholds as dcf_model.py for consistency across the app."""
    if upside > UNDERVALUED_THRESHOLD:
        return {"label": "Undervalued",   "emoji": "🟢", "color": "#10B981"}
    elif upside > OVERVALUED_THRESHOLD:
        return {"label": "Fairly Valued", "emoji": "🟡", "color": "#F59E0B"}
    else:
        return {"label": "Overvalued",    "emoji": "🔴", "color": "#EF4444"}


# ============================================================
# TEST BLOCK — chains all 4 files end-to-end
# ============================================================

if __name__ == "__main__":

    from data_fetcher       import get_stock_data
    from assumptions_engine import get_assumptions
    from dcf_model          import run_dcf
    from valuation_metrics  import run_valuation_metrics

    for ticker in ["AAPL", "RELIANCE.NS", "HDFCBANK.NS"]:
        print("\n" + "=" * 55)
        print(f"COMPOSITE SCORE — {ticker}")
        print("=" * 55)

        data = get_stock_data(ticker)
        if "error" in data:
            print(f"ERROR: {data['error']}")
            continue

        assumptions = get_assumptions(data)
        dcf         = run_dcf(data, assumptions)
        metrics     = run_valuation_metrics(data)
        composite   = run_composite(dcf, metrics, data)

        if "error" in composite:
            print(f"Composite Error: {composite['error']}")
            continue

        sym  = "₹" if data["meta"]["is_indian"] else "$"
        curr = data["price_data"]["current_price"]

        print(f"\nCompany Type:   {composite['company_type']}")
        print(f"Current Price:  {sym}{curr:,.2f}")
        print(f"Composite FV:   {sym}{composite['fair_value_per_share']:,.2f}")
        print(f"Upside:         {composite['upside_downside']:+.2%}")
        print(f"Verdict:        {composite['verdict_emoji']} {composite['verdict']}")
        print(f"Methods Used:   {composite['methods_used']}")

        print(f"\nBreakdown:")
        for method, detail in composite["weight_breakdown"].items():
            fv  = detail["fair_value"]
            w   = detail["weight"]
            fv_str = f"{sym}{fv:,.2f}" if fv else "N/A (excluded)"
            print(f"  {method:<12}  FV: {fv_str:<18}  Weight: {w:.0%}")