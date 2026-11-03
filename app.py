import base64
import json
import uuid
from datetime import datetime, timezone

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

st.set_page_config(page_title="Forex Alerts", page_icon="💱", layout="centered")

CCY = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "INR", "SGD",
       "HKD", "CNY", "ZAR", "TRY", "MXN", "NOK", "SEK", "DKK", "PLN", "THB",
       "AED", "SAR", "KRW", "BRL"]

PAIRS = {f"{b}/{q}": f"{b}{q}=X" for b in CCY for q in CCY if b != q}
PAIRS.update({
    "Gold (futures)": "GC=F",
    "Silver (futures)": "SI=F",
    "Crude oil (futures)": "CL=F",
})

REPO = st.secrets["GITHUB_REPO"]          # e.g. "yourname/forex-alerts"
TOKEN = st.secrets["GITHUB_TOKEN"]
BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
NTFY_TOPIC = st.secrets.get("NTFY_TOPIC", "")
PASSWORD = st.secrets.get("APP_PASSWORD", "")

API = f"https://api.github.com/repos/{REPO}/contents/alerts.json"
HEAD = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


# ---------- simple password gate ----------
if PASSWORD:
    if st.session_state.get("ok") != True:
        pw = st.text_input("Password", type="password")
        if pw == PASSWORD:
            st.session_state["ok"] = True
            st.rerun()
        st.stop()


# ---------- storage (alerts.json in the GitHub repo) ----------
def load():
    r = requests.get(API, headers=HEAD, params={"ref": BRANCH}, timeout=20)
    if not r.ok:
        st.error(f"GitHub error {r.status_code} while loading: {r.text}")
        st.stop()
    j = r.json()
    return json.loads(base64.b64decode(j["content"])), j["sha"]


def save(data, sha, msg):
    body = {
        "message": msg,
        "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        "sha": sha,
        "branch": BRANCH,
    }
    r = requests.put(API, headers=HEAD, json=body, timeout=20)
    if not r.ok:
        st.error(f"GitHub error {r.status_code}: {r.text}")
        st.stop()


@st.cache_data(ttl=30)
def price(ticker):
    try:
        h = yf.Ticker(ticker).history(period="1d", interval="1m")
        return float(h["Close"].iloc[-1])
    except Exception:
        return None


# ---------- candlestick chart with alert levels ----------
TF_CFG = {
    "1m": ("5d", "1m"),
    "5m": ("5d", "5m"),
    "15m": ("5d", "15m"),
    "1h": ("1mo", "60m"),
    "4h": ("3mo", "60m"),   # built from 1h candles
    "1D": ("6mo", "1d"),
}


@st.cache_data(ttl=60)
def candles(ticker, tf):
    period, interval = TF_CFG[tf]
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close"]]
    if tf == "4h":
        df = df.resample("4h").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        ).dropna()
    return df.tail(250)


def make_chart(df, alerts, preview_target):
    fig = go.Figure(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        hoverinfo="skip",
    ))

    # invisible grid of points: tapping anywhere on the chart selects the nearest price level
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    pad = (hi - lo) * 0.1 or hi * 0.001
    n = 120
    levels = [lo - pad + i * (hi - lo + 2 * pad) / (n - 1) for i in range(n)]
    xs = list(df.index[:: max(1, len(df) // 20)])
    gx = [x for x in xs for _ in levels]
    gy = levels * len(xs)
    fig.add_trace(go.Scatter(
        x=gx, y=gy, mode="markers",
        marker=dict(size=14, opacity=0.01, color="white"),
        hovertemplate="%{y:.5f}<extra></extra>", showlegend=False,
    ))

    for a in alerts:
        color = "#26a69a" if a["condition"] == "above" else "#ef5350"
        fig.add_hline(
            y=a["target"], line_dash="dash", line_color=color, line_width=1.5,
            annotation_text=f"{a['condition']} {a['target']:.5f}",
            annotation_position="top left", annotation_font_color=color,
        )
    if preview_target:
        fig.add_hline(
            y=preview_target, line_dash="dot", line_color="#f5c518", line_width=1.5,
            annotation_text=f"new {preview_target:.5f}",
            annotation_position="bottom left", annotation_font_color="#f5c518",
        )
    fig.update_layout(
        template="plotly_dark", height=450, margin=dict(l=0, r=0, t=10, b=0),
        xaxis_rangeslider_visible=False, showlegend=False,
        dragmode="pan", clickmode="event+select",
        hovermode="closest", hoverdistance=-1,
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])  # hide weekends
    return fig


# ---------- TradingView chart ----------
def tv_symbol(ticker):
    special = {"GC=F": "OANDA:XAUUSD", "SI=F": "OANDA:XAGUSD", "CL=F": "TVC:USOIL"}
    if ticker in special:
        return special[ticker]
    if ticker.endswith("=X"):
        core = ticker[:-2]
        if len(core) == 3:          # Yahoo writes USD pairs like JPY=X
            core = "USD" + core
        return "FX:" + core
    return ticker


def tv_chart(symbol, interval="15", height=480):
    html = f"""
    <div style="height:{height}px;width:100%">
      <div id="tv_chart" style="height:{height}px;width:100%"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{symbol}",
          "interval": "{interval}",
          "timezone": "Etc/UTC",
          "theme": "dark",
          "style": "1",
          "locale": "en",
          "allow_symbol_change": true,
          "hide_side_toolbar": false,
          "container_id": "tv_chart"
        }});
      </script>
    </div>
    """
    components.html(html, height=height)


# ---------- UI ----------
st.title("💱 Forex Alerts")

data, sha = load()
active = [a for a in data["alerts"] if a.get("active", True)]

# 1) choose pair
pair = st.selectbox("Pair (tap and type to search)", list(PAIRS) + ["Custom..."])
if pair == "Custom...":
    ticker = st.text_input("Yahoo Finance ticker", "EURNOK=X").strip().upper()
    pair = ticker
else:
    ticker = PAIRS[pair]

cur = price(ticker)
if cur:
    st.caption(f"Current price: **{cur:.5f}**")
else:
    st.caption("Current price not available for this ticker.")

# reset the form values when the pair changes
if st.session_state.get("last_ticker") != ticker:
    st.session_state["last_ticker"] = ticker
    st.session_state["target"] = float(cur or 1.0)
    st.session_state["cond"] = "above"
    st.session_state["last_click"] = None

# 2) chart (tap a level to fill the alert form below)
if st.toggle("📈 Show chart", value=True):
    mode = st.radio("Chart type", ["Candles (tap to set alert)", "TradingView"], horizontal=True)
    tf = st.radio("Timeframe", list(TF_CFG), index=2, horizontal=True)

    if mode == "TradingView":
        tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1D": "D"}
        tv_chart(tv_symbol(ticker), tf_map[tf])
        st.caption("Tapping doesn't set alerts on the TradingView chart. Switch to Candles for that.")
    else:
        df = candles(ticker, tf)
        if df is None:
            st.warning("No chart data for this ticker and timeframe. Try another timeframe.")
        else:
            my_alerts = [a for a in active if a["ticker"] == ticker]
            fig = make_chart(df, my_alerts, st.session_state["target"])
            event = st.plotly_chart(
                fig, use_container_width=True, key=f"chart_{ticker}_{tf}",
                on_select="rerun", selection_mode="points",
                config={"displaylogo": False},
            )
            pts = ((event or {}).get("selection") or {}).get("points") or []
            if pts:
                y = float(pts[-1]["y"])
                click_id = (ticker, tf, round(y, 8))
                if st.session_state.get("last_click") != click_id:
                    st.session_state["last_click"] = click_id
                    st.session_state["target"] = round(y, 5)
                    st.session_state["cond"] = "above" if (cur and y > cur) else "below"
                    st.rerun()
            st.caption("Tap the chart to pick a price. Green dashed = alert above, "
                       "red dashed = alert below, yellow dotted = your new alert.")

# 3) create alert
st.subheader("Create alert")
cond = st.radio("Notify me when price goes", ["above", "below"], horizontal=True, key="cond")
target = st.number_input("Target price", format="%.5f", step=0.0001, key="target")
note = st.text_input("Note (optional)")

if st.button("Create alert", type="primary", use_container_width=True):
    if not cur:
        st.error("Can't find a price for this ticker. Check the spelling.")
    else:
        data["alerts"].append({
            "id": uuid.uuid4().hex[:8],
            "pair": pair,
            "ticker": ticker,
            "condition": cond,
            "target": target,
            "note": note,
            "active": True,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        save(data, sha, f"Add alert {pair} {cond} {target}")
        st.success("Alert created")
        st.rerun()

# ---------- alert lists ----------
st.subheader("Active alerts")
if not active:
    st.info("No active alerts.")
for a in active:
    c1, c2 = st.columns([4, 1])
    now = price(a["ticker"])
    line = f"**{a['pair']}** {a['condition']} **{a['target']:.5f}**"
    if now:
        line += f"  \nnow: {now:.5f}"
    c1.markdown(line)
    if a.get("note"):
        c1.caption(a["note"])
    if c2.button("🗑", key="d" + a["id"]):
        data["alerts"] = [x for x in data["alerts"] if x["id"] != a["id"]]
        save(data, sha, f"Delete alert {a['id']}")
        st.rerun()

done = [a for a in data["alerts"] if not a.get("active", True)]
if done:
    with st.expander(f"Triggered ({len(done)})"):
        for a in done:
            st.write(f"✅ {a['pair']} {a['condition']} {a['target']:.5f} — {a.get('triggered_at', '')}")
        if st.button("Clear triggered"):
            data["alerts"] = active
            save(data, sha, "Clear triggered alerts")
            st.rerun()

st.divider()
if NTFY_TOPIC:
    if st.button("Send test notification"):
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data="Test from Forex Alerts".encode(),
                      headers={"Title": "Forex Alerts test"}, timeout=10)
        st.success("Sent")
