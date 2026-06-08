# app.py
# Main Streamlit UI — the entry point for the entire application.
# Run with: streamlit run app.py
#
# Layout:
#   1. Search bar
#   2. Company snapshot cards
#   3. Financial metrics cards
#   4. Football field chart (Plotly)
#   5. Individual valuation cards (DCF, P/E, EV/EBITDA, 52W)
#   6. Composite verdict
#   7. Collapsible assumptions panel with sliders + recalculate

import streamlit as st
import plotly.graph_objects as go

from data_fetcher       import get_stock_data
from assumptions_engine import get_assumptions
from dcf_model          import run_dcf
from valuation_metrics  import run_valuation_metrics
from composite_score    import run_composite

# ============================================================
# PAGE CONFIG — must be the first Streamlit call
# ============================================================

st.set_page_config(
    page_title  = "Stock Valuation Dashboard",
    page_icon   = "📊",
    layout      = "wide",
    initial_sidebar_state = "collapsed",
)

# ============================================================
# CUSTOM CSS — clean, dark, finance-terminal aesthetic
# ============================================================

st.markdown("""
<style>
    /* ── Base ── */
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif;
        background-color: #0d0d0f;
        color: #e8e8ea;
    }

    /* ── Hide Streamlit chrome ── */
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 2rem 3rem 4rem 3rem; max-width: 1400px; }

    /* ── Title ── */
    .dash-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.1rem;
        font-weight: 600;
        letter-spacing: 0.15em;
        color: #6ee7b7;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
    }
    .dash-subtitle {
        font-size: 0.8rem;
        color: #555;
        letter-spacing: 0.05em;
        margin-bottom: 2rem;
    }

    /* ── Metric cards ── */
    .card {
        background: #16161a;
        border: 1px solid #242428;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        height: 100%;
    }
    .card-label {
        font-size: 0.68rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #555;
        margin-bottom: 0.4rem;
    }
    .card-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.15rem;
        font-weight: 600;
        color: #e8e8ea;
    }
    .card-sub {
        font-size: 0.72rem;
        color: #555;
        margin-top: 0.2rem;
    }

    /* ── Valuation method cards ── */
    .val-card {
        background: #16161a;
        border: 1px solid #242428;
        border-radius: 8px;
        padding: 1.2rem;
        text-align: center;
        height: 100%;
    }
    .val-method {
        font-size: 0.68rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #555;
        margin-bottom: 0.6rem;
    }
    .val-price {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.4rem;
        font-weight: 600;
        color: #e8e8ea;
        margin-bottom: 0.3rem;
    }
    .val-upside-pos { color: #6ee7b7; font-size: 0.85rem; font-weight: 600; }
    .val-upside-neg { color: #f87171; font-size: 0.85rem; font-weight: 600; }
    .val-upside-neu { color: #fbbf24; font-size: 0.85rem; font-weight: 600; }
    .val-verdict    { font-size: 0.75rem; color: #888; margin-top: 0.3rem; }
    .val-na         { color: #444; font-size: 0.8rem; padding: 1.5rem 0; }

    /* ── Composite verdict banner ── */
    .verdict-banner {
        background: #16161a;
        border: 1px solid #242428;
        border-radius: 10px;
        padding: 1.5rem 2rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 2rem;
        flex-wrap: wrap;
        margin: 1.5rem 0;
    }
    .verdict-item { text-align: center; }
    .verdict-big {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 2rem;
        font-weight: 700;
    }
    .verdict-tag-green { color: #6ee7b7; font-size: 1.1rem; font-weight: 700; letter-spacing: 0.05em; }
    .verdict-tag-red   { color: #f87171; font-size: 1.1rem; font-weight: 700; letter-spacing: 0.05em; }
    .verdict-tag-amber { color: #fbbf24; font-size: 1.1rem; font-weight: 700; letter-spacing: 0.05em; }

    /* ── Section headers ── */
    .section-head {
        font-size: 0.7rem;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: #444;
        border-bottom: 1px solid #242428;
        padding-bottom: 0.4rem;
        margin: 1.8rem 0 1rem 0;
    }

    /* ── Assumption sliders label ── */
    .assume-source {
        font-size: 0.7rem;
        color: #444;
        font-style: italic;
        margin-top: -0.5rem;
        margin-bottom: 0.8rem;
    }

    /* ── Streamlit widget overrides ── */
    div[data-testid="stSlider"] > div { padding-bottom: 0.2rem; }
    .stButton > button {
        background: #1e1e24;
        border: 1px solid #333;
        color: #e8e8ea;
        border-radius: 6px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        letter-spacing: 0.05em;
        padding: 0.4rem 1.2rem;
        transition: border-color 0.2s;
    }
    .stButton > button:hover { border-color: #6ee7b7; color: #6ee7b7; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# HELPER UTILITIES
# ============================================================

def fmt_currency(value, currency="USD", compact=True):
    """Format a number as a compact currency string (e.g. $1.23B)."""
    if value is None:
        return "N/A"
    symbol = "₹" if currency == "INR" else "$"
    if compact:
        if abs(value) >= 1e12:
            return f"{symbol}{value/1e12:.2f}T"
        elif abs(value) >= 1e9:
            return f"{symbol}{value/1e9:.2f}B"
        elif abs(value) >= 1e6:
            return f"{symbol}{value/1e6:.2f}M"
        else:
            return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.2f}"


def fmt_price(value, currency="USD"):
    """Format a share price."""
    if value is None:
        return "N/A"
    symbol = "₹" if currency == "INR" else "$"
    return f"{symbol}{value:,.2f}"


def fmt_pct(value, plus=True):
    """Format a ratio as percentage."""
    if value is None:
        return "N/A"
    prefix = "+" if (plus and value > 0) else ""
    return f"{prefix}{value:.2%}"


def fmt_number(value, decimals=2):
    """Format a plain number."""
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


def metric_card(label, value, sub=None):
    """Render a single metric card as HTML."""
    sub_html = f'<div class="card-sub">{sub}</div>' if sub else ""
    return f"""
    <div class="card">
        <div class="card-label">{label}</div>
        <div class="card-value">{value}</div>
        {sub_html}
    </div>
    """


def upside_class(upside):
    """Pick CSS class for upside/downside colouring."""
    if upside is None:
        return "val-upside-neu"
    if upside > 0.05:
        return "val-upside-pos"
    if upside < -0.05:
        return "val-upside-neg"
    return "val-upside-neu"


# ============================================================
# RUN ALL MODELS — cached so re-renders don't re-fetch
# ============================================================

@st.cache_data(show_spinner=False)
def fetch_and_run(ticker, overrides=None):
    """
    Fetches data and runs all valuation models.
    overrides — dict of assumption values edited by the user via sliders.
                If None, auto-calculated defaults are used.
    """
    data = get_stock_data(ticker)
    if "error" in data:
        return {"error": data["error"]}

    assumptions = get_assumptions(data)

    # Apply any user slider overrides on top of auto-calculated defaults
    if overrides:
        for key, val in overrides.items():
            if key in assumptions:
                assumptions[key]["value"] = val

    dcf_result     = run_dcf(data, assumptions)
    metrics_result = run_valuation_metrics(data)
    composite      = run_composite(dcf_result, metrics_result, data)

    return {
        "data":        data,
        "assumptions": assumptions,
        "dcf":         dcf_result,
        "metrics":     metrics_result,
        "composite":   composite,
    }


# ============================================================
# SESSION STATE INIT
# ============================================================

if "ticker"      not in st.session_state: st.session_state.ticker      = ""
if "results"     not in st.session_state: st.session_state.results     = None
if "overrides"   not in st.session_state: st.session_state.overrides   = None
if "show_assume" not in st.session_state: st.session_state.show_assume = False


# ============================================================
# HEADER
# ============================================================

st.markdown('<div class="dash-title">◈ Stock Valuation Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="dash-subtitle">DCF · P/E · EV/EBITDA · 52W · Composite Fair Value</div>', unsafe_allow_html=True)


# ============================================================
# SEARCH BAR
# ============================================================

col_input, col_btn, col_spacer = st.columns([3, 1, 6])

with col_input:
    ticker_input = st.text_input(
        label       = "ticker",
        placeholder = "e.g. AAPL or RELIANCE.NS",
        label_visibility = "collapsed",
        key         = "ticker_input_box",
    )

with col_btn:
    analyze_clicked = st.button("Analyze →", use_container_width=True)

if analyze_clicked and ticker_input.strip():
    st.session_state.ticker    = ticker_input.strip().upper()
    st.session_state.results   = None   # Clear cached results on new ticker
    st.session_state.overrides = None
    st.cache_data.clear()


# ============================================================
# MAIN DASHBOARD — only renders once a ticker is set
# ============================================================

if st.session_state.ticker:

    ticker = st.session_state.ticker

    # Run all models (with optional slider overrides)
    with st.spinner(f"Fetching data for {ticker}…"):
        results = fetch_and_run(ticker, st.session_state.overrides)

    if "error" in results:
        st.error(results["error"])
        st.stop()

    # Unpack
    data        = results["data"]
    assumptions = results["assumptions"]
    dcf         = results["dcf"]
    metrics     = results["metrics"]
    composite   = results["composite"]
    currency    = data["meta"]["currency"]
    info        = data["company_info"]
    price       = data["price_data"]
    income      = data["income_statement"]
    balance     = data["balance_sheet"]
    valuation   = data["valuation"]

    # ── Company name + sector ──────────────────────────────
    st.markdown(f"### {info['name']}  <span style='color:#555;font-size:0.9rem;font-weight:400'>{info['sector']} · {info['industry']}</span>", unsafe_allow_html=True)

    # ──────────────────────────────────────────────────────
    # ROW 1: Company snapshot
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Company Snapshot</div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    cards_row1 = [
        (c1, "Current Price",   fmt_price(price["current_price"], currency)),
        (c2, "Market Cap",      fmt_currency(price["market_cap"], currency)),
        (c3, "52W High",        fmt_price(price["week_52_high"], currency)),
        (c4, "52W Low",         fmt_price(price["week_52_low"], currency)),
        (c5, "Beta",            fmt_number(price["beta"])),
        (c6, "Div Yield",       fmt_pct(valuation["dividend_yield"], plus=False)),
        (c7, "Country",         info["country"]),
    ]
    for col, label, val in cards_row1:
        col.markdown(metric_card(label, val), unsafe_allow_html=True)

    # ──────────────────────────────────────────────────────
    # ROW 2: Financial metrics
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Financial Metrics (TTM)</div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    ebitda_margin = income["ebitda_margin"]
    net_margin    = income["net_margin"]
    roe           = balance["return_on_equity"]
    de            = balance["debt_to_equity"]
    fcf           = data["cash_flow"]["fcf_ttm"]

    cards_row2 = [
        (c1, "Revenue TTM",    fmt_currency(income["revenue_ttm"], currency)),
        (c2, "EBITDA TTM",     fmt_currency(income["ebitda_ttm"], currency)),
        (c3, "EBITDA Margin",  fmt_pct(ebitda_margin, plus=False)),
        (c4, "Net Margin",     fmt_pct(net_margin, plus=False)),
        (c5, "FCF TTM",        fmt_currency(fcf, currency)),
        (c6, "ROE",            fmt_pct(roe, plus=False)),
        (c7, "D/E Ratio",      fmt_number(de / 100 if de else None)),   # yfinance gives D/E * 100
    ]
    for col, label, val in cards_row2:
        col.markdown(metric_card(label, val), unsafe_allow_html=True)

    # ──────────────────────────────────────────────────────
    # ROW 3: Football Field Chart
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Football Field — Fair Value Ranges by Method</div>', unsafe_allow_html=True)

    current_price_val = price["current_price"]

    # Collect all methods that have a range
    ff_methods = []

    if "error" not in dcf:
        # DCF range: ±15% around fair value
        dcf_fv = dcf["fair_value_per_share"]
        ff_methods.append({
            "name":  "DCF",
            "low":   round(dcf_fv * 0.85, 2),
            "high":  round(dcf_fv * 1.15, 2),
            "point": dcf_fv,
            "color": "#6ee7b7",
        })

    pe = metrics["pe_comps"]
    if pe["available"]:
        ff_methods.append({
            "name":  "P/E Comps",
            "low":   pe["range_low"],
            "high":  pe["range_high"],
            "point": pe["fair_value_per_share"],
            "color": "#60a5fa",
        })

    ev = metrics["ev_ebitda"]
    if ev["available"]:
        ff_methods.append({
            "name":  "EV/EBITDA",
            "low":   ev["range_low"],
            "high":  ev["range_high"],
            "point": ev["fair_value_per_share"],
            "color": "#c084fc",
        })

    w52 = metrics["week_52"]
    if w52["available"]:
        ff_methods.append({
            "name":  "52-Week Range",
            "low":   w52["range_low"],
            "high":  w52["range_high"],
            "point": w52["midpoint"],
            "color": "#fb923c",
        })

    if ff_methods:
        fig = go.Figure()

        for i, m in enumerate(ff_methods):
            # Range bar (low → high)
            fig.add_trace(go.Bar(
                name        = m["name"],
                x           = [m["high"] - m["low"]],
                y           = [m["name"]],
                base        = [m["low"]],
                orientation = "h",
                marker_color = m["color"],
                marker_opacity = 0.25,
                showlegend  = False,
                hovertemplate = (
                    f"<b>{m['name']}</b><br>"
                    f"Range: {fmt_price(m['low'], currency)} – {fmt_price(m['high'], currency)}<br>"
                    f"Fair Value: {fmt_price(m['point'], currency)}"
                    "<extra></extra>"
                ),
            ))
            # Point estimate (diamond marker)
            fig.add_trace(go.Scatter(
                x    = [m["point"]],
                y    = [m["name"]],
                mode = "markers",
                marker = dict(symbol="diamond", size=12, color=m["color"]),
                showlegend = False,
                hoverinfo  = "skip",
            ))

        # Current price vertical line
        if current_price_val:
            fig.add_vline(
                x           = current_price_val,
                line_color  = "#f43f5e",
                line_width  = 2,
                line_dash   = "dot",
                annotation_text = f"Current {fmt_price(current_price_val, currency)}",
                annotation_font_color = "#f43f5e",
                annotation_font_size  = 11,
                annotation_position   = "top right",
            )

        fig.update_layout(
            height          = 260,
            plot_bgcolor    = "#16161a",
            paper_bgcolor   = "#0d0d0f",
            font_color      = "#888",
            font_family     = "IBM Plex Mono",
            margin          = dict(l=10, r=20, t=20, b=20),
            xaxis = dict(
                gridcolor   = "#242428",
                zerolinecolor = "#242428",
                tickprefix  = "₹" if currency == "INR" else "$",
            ),
            yaxis = dict(
                gridcolor   = "#242428",
            ),
            barmode = "overlay",
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data to render the football field chart.")

    # ──────────────────────────────────────────────────────
    # ROW 4: Composite Verdict Banner
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Composite Verdict</div>', unsafe_allow_html=True)

    if "error" not in composite:
        comp_fv     = composite["fair_value_per_share"]
        comp_up     = composite["upside_downside"]
        comp_verd   = composite["verdict"]

        # Pick colour class for verdict tag
        if comp_verd == "Undervalued":
            tag_class = "verdict-tag-green"
        elif comp_verd == "Overvalued":
            tag_class = "verdict-tag-red"
        else:
            tag_class = "verdict-tag-amber"

        up_sign  = "+" if comp_up > 0 else ""
        up_color = "#6ee7b7" if comp_up > 0 else "#f87171"

        st.markdown(f"""
        <div class="verdict-banner">
            <div class="verdict-item">
                <div class="card-label">Composite Fair Value</div>
                <div class="verdict-big">{fmt_price(comp_fv, currency)}</div>
            </div>
            <div class="verdict-item">
                <div class="card-label">Current Price</div>
                <div class="verdict-big">{fmt_price(current_price_val, currency)}</div>
            </div>
            <div class="verdict-item">
                <div class="card-label">Implied Upside</div>
                <div class="verdict-big" style="color:{up_color}">{up_sign}{comp_up:.1%}</div>
            </div>
            <div class="verdict-item">
                <div class="card-label">Verdict</div>
                <div class="{tag_class}">{composite['verdict_emoji']} {comp_verd}</div>
            </div>
            <div class="verdict-item">
                <div class="card-label">Methods Used</div>
                <div class="card-value" style="font-size:0.9rem">{composite['methods_used']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning(f"Composite score unavailable: {composite['error']}")

    # ──────────────────────────────────────────────────────
    # ROW 5: Individual valuation cards
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Individual Valuation Methods</div>', unsafe_allow_html=True)

    col_dcf, col_pe, col_ev, col_52 = st.columns(4)

    # Helper to render a valuation card
    def val_card_html(method_name, result, currency):
        if result is None or not result.get("available", True):
            reason = result.get("reason", "Unavailable") if result else "Unavailable"
            return f"""
            <div class="val-card">
                <div class="val-method">{method_name}</div>
                <div class="val-na">⚠ {reason}</div>
            </div>
            """
        if "error" in result:
            return f"""
            <div class="val-card">
                <div class="val-method">{method_name}</div>
                <div class="val-na">⚠ {result['error']}</div>
            </div>
            """

        fv    = result.get("fair_value_per_share")
        up    = result.get("upside_downside")
        verd  = result.get("verdict", "")
        emoji = result.get("verdict_emoji", "")

        up_str   = fmt_pct(up) if up is not None else "N/A"
        css_cls  = upside_class(up)

        return f"""
        <div class="val-card">
            <div class="val-method">{method_name}</div>
            <div class="val-price">{fmt_price(fv, currency)}</div>
            <div class="{css_cls}">{up_str}</div>
            <div class="val-verdict">{emoji} {verd}</div>
        </div>
        """

    # DCF card — result shape is slightly different (no "available" key, uses "error")
    with col_dcf:
        st.markdown(val_card_html("DCF", dcf, currency), unsafe_allow_html=True)

    with col_pe:
        st.markdown(val_card_html("P/E Comps", metrics["pe_comps"], currency), unsafe_allow_html=True)

    with col_ev:
        st.markdown(val_card_html("EV / EBITDA", metrics["ev_ebitda"], currency), unsafe_allow_html=True)

    # 52-week card is slightly different — it shows signal, not a fair value verdict
    with col_52:
        w = metrics["week_52"]
        if w.get("available"):
            pos_bar_pct = int(w["position_pct"] * 100)
            st.markdown(f"""
            <div class="val-card">
                <div class="val-method">52-Week Range</div>
                <div class="val-price">{pos_bar_pct}% of Range</div>
                <div class="{upside_class(None)}" style="color:{w['signal_color']}">{w['signal_emoji']} {w['signal']}</div>
                <div class="val-verdict" style="font-size:0.65rem;margin-top:0.5rem">{w['signal_note']}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(val_card_html("52-Week Range", w, currency), unsafe_allow_html=True)

    # ──────────────────────────────────────────────────────
    # ROW 6: Collapsible Assumptions Panel
    # ──────────────────────────────────────────────────────
    st.markdown('<div class="section-head">DCF Assumptions</div>', unsafe_allow_html=True)

    with st.expander("✦ Edit Assumptions", expanded=st.session_state.show_assume):

        st.caption("Auto-calculated from real data. Adjust sliders and hit Recalculate to see how the DCF changes.")

        a = assumptions  # shorthand

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            new_growth = st.slider(
                "Revenue Growth Rate",
                min_value = a["revenue_growth"]["min"],
                max_value = a["revenue_growth"]["max"],
                value     = float(a["revenue_growth"]["value"]),
                step      = 0.005,
                format    = "%.1f%%",
                key       = "sl_growth",
            )
            st.markdown(f'<div class="assume-source">{a["revenue_growth"]["source"]}</div>', unsafe_allow_html=True)

            new_fcf = st.slider(
                "FCF Margin",
                min_value = a["fcf_margin"]["min"],
                max_value = a["fcf_margin"]["max"],
                value     = float(a["fcf_margin"]["value"]),
                step      = 0.005,
                format    = "%.1f%%",
                key       = "sl_fcf",
            )
            st.markdown(f'<div class="assume-source">{a["fcf_margin"]["source"]}</div>', unsafe_allow_html=True)

        with col_b:
            new_wacc = st.slider(
                "WACC (Discount Rate)",
                min_value = a["wacc"]["min"],
                max_value = a["wacc"]["max"],
                value     = float(a["wacc"]["value"]),
                step      = 0.005,
                format    = "%.1f%%",
                key       = "sl_wacc",
            )
            st.markdown(f'<div class="assume-source">{a["wacc"]["source"]}</div>', unsafe_allow_html=True)

            new_terminal = st.slider(
                "Terminal Growth Rate",
                min_value = a["terminal_growth"]["min"],
                max_value = a["terminal_growth"]["max"],
                value     = float(a["terminal_growth"]["value"]),
                step      = 0.005,
                format    = "%.1f%%",
                key       = "sl_terminal",
            )
            st.markdown(f'<div class="assume-source">{a["terminal_growth"]["source"]}</div>', unsafe_allow_html=True)

        with col_c:
            new_years = st.select_slider(
                "Projection Years",
                options = [5, 7, 10],
                value   = int(a["projection_years"]["value"]),
                key     = "sl_years",
            )
            st.markdown('<div class="assume-source">Forecast horizon for FCF projections</div>', unsafe_allow_html=True)

            new_tax = st.slider(
                "Tax Rate",
                min_value = a["tax_rate"]["min"],
                max_value = a["tax_rate"]["max"],
                value     = float(a["tax_rate"]["value"]),
                step      = 0.005,
                format    = "%.1f%%",
                key       = "sl_tax",
            )
            st.markdown(f'<div class="assume-source">{a["tax_rate"]["source"]}</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        btn_col1, btn_col2, _ = st.columns([1, 1, 5])

        with btn_col1:
            if st.button("⟳ Recalculate", key="btn_recalc"):
                # Store overrides in session state and clear the cache so
                # the next render picks up the new assumptions
                st.session_state.overrides = {
                    "revenue_growth":  new_growth,
                    "fcf_margin":      new_fcf,
                    "wacc":            new_wacc,
                    "terminal_growth": new_terminal,
                    "projection_years": new_years,
                    "tax_rate":        new_tax,
                }
                st.session_state.show_assume = True
                st.cache_data.clear()
                st.rerun()

        with btn_col2:
            if st.button("↺ Reset to Defaults", key="btn_reset"):
                st.session_state.overrides   = None
                st.session_state.show_assume = True
                st.cache_data.clear()
                st.rerun()

    # ──────────────────────────────────────────────────────
    # ROW 7: DCF year-by-year breakdown (collapsed)
    # ──────────────────────────────────────────────────────
    if "error" not in dcf and dcf.get("yearly_projections"):
        with st.expander("📅 DCF Year-by-Year Projections"):
            proj = dcf["yearly_projections"]
            col_headers = st.columns(len(proj) + 1)
            col_headers[0].markdown("**Metric**")
            for i, p in enumerate(proj):
                col_headers[i + 1].markdown(f"**Year {p['year']}**")

            row_fcf = st.columns(len(proj) + 1)
            row_fcf[0].markdown("Projected FCF")
            for i, p in enumerate(proj):
                row_fcf[i + 1].markdown(fmt_currency(p["projected_fcf"], currency))

            row_pv = st.columns(len(proj) + 1)
            row_pv[0].markdown("Present Value")
            for i, p in enumerate(proj):
                row_pv[i + 1].markdown(fmt_currency(p["present_value"], currency))

            st.markdown("---")
            col_summary = st.columns(3)
            col_summary[0].metric("PV of Cash Flows",  fmt_currency(dcf["pv_of_cashflows"],   currency))
            col_summary[1].metric("Terminal Value PV", fmt_currency(dcf["terminal_value_pv"],  currency))
            col_summary[2].metric("TV as % of Total",  f"{dcf['tv_as_pct_of_total']}%")

# ──────────────────────────────────────────────────────
# EMPTY STATE — before any ticker is entered
# ──────────────────────────────────────────────────────
else:
    st.markdown("""
    <div style="text-align:center;padding:5rem 0;color:#333;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:3rem;margin-bottom:1rem;">◈</div>
        <div style="font-size:0.85rem;letter-spacing:0.1em;text-transform:uppercase;">
            Enter a ticker symbol above to begin
        </div>
        <div style="font-size:0.75rem;margin-top:0.5rem;color:#2a2a2a">
            US stocks: AAPL, MSFT, TSLA &nbsp;·&nbsp; Indian stocks: RELIANCE.NS, INFY.NS, HDFCBANK.NS
        </div>
    </div>
    """, unsafe_allow_html=True)