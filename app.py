import base64
import html
import json
import uuid
from datetime import datetime, timezone

import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

st.set_page_config(page_title="FX Alerts", page_icon="💱", layout="centered")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.stApp { font-family: 'Inter', sans-serif;
  background:
    radial-gradient(900px 500px at 8% -8%, rgba(60,90,200,.35) 0%, transparent 60%),
    radial-gradient(800px 450px at 100% 0%, rgba(130,70,200,.28) 0%, transparent 55%),
    #0b0f19; }
.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 760px; }
#MainMenu, footer { visibility: hidden; }

.brand { font-size: 1.7rem; font-weight: 800; letter-spacing: -.5px;
  background: linear-gradient(90deg, #8fb0ff, #c08bff); -webkit-background-clip: text;
  -webkit-text-fill-color: transparent; margin-bottom: .6rem; }

.hero { background: linear-gradient(135deg, rgba(108,140,255,.18), rgba(192,139,255,.10));
  border: 1px solid rgba(255,255,255,.10); border-radius: 22px; padding: 18px 20px; margin: 10px 0 14px 0;
  box-shadow: 0 10px 30px rgba(0,0,0,.35); }
.hero-top { display: flex; justify-content: space-between; align-items: center; }
.hero-pair { font-weight: 700; font-size: 1rem; color: #aab4d0; letter-spacing: .5px; }
.hero-price { font-size: 2.5rem; font-weight: 800; letter-spacing: -1px; color: #f4f7ff; margin-top: 2px; }
.hero-sub { font-size: .78rem; color: #7f8aa8; margin-top: 2px; }

.chip { padding: 4px 11px; border-radius: 999px; font-size: .8rem; font-weight: 700; }
.chip.up { background: rgba(38,166,154,.18); color: #3ddbc6; }
.chip.down { background: rgba(239,83,80,.18); color: #ff7b78; }

[data-testid="stVerticalBlockBorderWrapper"] { background: rgba(255,255,255,.035);
  border: 1px solid rgba(255,255,255,.08) !important; border-radius: 18px !important; }

.a-top { display: flex; align-items: center; gap: 8px; }
.a-pair { font-weight: 700; font-size: 1.05rem; color: #eef2ff; }
.badge { padding: 2px 9px; border-radius: 8px; font-size: .68rem; font-weight: 800; letter-spacing: .6px; }
.badge.up { background: rgba(38,166,154,.18); color: #3ddbc6; }
.badge.down { background: rgba(239,83,80,.18); color: #ff7b78; }
.a-target { font-size: 1.55rem; font-weight: 800; color: #f4f7ff; margin-top: 4px; letter-spacing: -.5px; }
.a-meta { font-size: .8rem; color: #8a95b3; margin-top: 2px; }
.a-note { font-size: .8rem; color: #aab4d0; margin-top: 6px; font-style: italic; }
.done { font-size: .9rem; color: #c9d2ea; }
.done small { color: #7f8aa8; }

.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs button[data-baseweb="tab"] { border-radius: 12px; padding: 8px 14px; font-weight: 600; }
button[data-testid="stBaseButton-primary"] { background: linear-gradient(90deg, #5b7cff, #a06bff);
  border: 0; border-radius: 14px; font-weight: 700; padding: .6rem 1rem; }
button[data-testid="stBaseButton-secondary"] { border-radius: 12px; }
.section { font-weight: 700; color: #aab4d0; font-size: .85rem; letter-spacing: .8px;
  text-transform: uppercase; margin: 14px 0 6px 2px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

CCY = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "INR", "SGD",
       "HKD", "CNY", "ZAR", "TRY", "MXN", "NOK", "SEK", "DKK", "PLN", "THB",
       "AED", "SAR", "KRW", "BRL"]

PAIRS = {f"{b}/{q}": f"{b}{q}=X" for b in CCY for q in CCY if b != q}
PAIRS.update({
    "Gold (futures)": "GC=F",
    "Silver (futures)": "SI=F",
    "Crude oil (futures)": "CL=F",
})

REPO = st.secrets["GITHUB_REPO"]
TOKEN = st.secrets["GITHUB_TOKEN"]
BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
NTFY_TOPIC = st.secrets.get("NTFY_TOPIC", "")
PASSWORD = st.secrets.get("APP_PASSWORD", "")

API = f"https://api.github.com/repos/{REPO}/contents/alerts.json"
HEAD = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


# ---------- password gate ----------
if PASSWORD:
    if st.session_state.get("ok") != True:
        st.markdown('<div class="brand">💱 FX Alerts</div>', unsafe_allow_html=True)
        pw = st.text_input("Password", type="password")
        if pw == PASSWORD:
            st.session_state["ok"] = True
            st.rerun()
        st.stop()


# ---------- storage ----------
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
def quote(ticker):
    try:
        h = yf.Ticker(ticker).history(period="1d", interval="1m")
        return float(h["Close"].iloc[-1]), float(h["Open"].iloc[0])
    except Exception:
        return None


def price(ticker):
    q = quote(ticker)
    return q[0] if q else None


# ---------- charts ----------
TF_CFG = {
    "1m": ("5d", "1m"), "5m": ("5d", "5m"), "15m": ("5d", "15m"),
    "1h": ("1mo", "60m"), "4h": ("3mo", "60m"), "1D": ("6mo", "1d"),
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


def make_chart(df, alerts, preview_target, cur):
    fig = go.Figure(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color="#3ddbc6", decreasing_line_color="#ff7b78",
        increasing_fillcolor="#3ddbc6", decreasing_fillcolor="#ff7b78",
    ))
    for a in alerts:
        color = "#3ddbc6" if a["condition"] == "above" else "#ff7b78"
        fig.add_hline(y=a["target"], line_dash="dash", line_color=color, line_width=1.3,
                      annotation_text=f"{a['condition']} {a['target']:.5f}",
                      annotation_position="top left", annotation_font_color=color)
    if preview_target:
        fig.add_hline(y=preview_target, line_dash="dot", line_color="#f5c518", line_width=1.5,
                      annotation_text=f"new {preview_target:.5f}",
                      annotation_position="bottom left", annotation_font_color="#f5c518")
    fig.update_layout(
        template="plotly_dark", height=420, margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False, showlegend=False, dragmode="pan",
        font=dict(family="Inter, sans-serif", color="#aab4d0"),
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor="rgba(255,255,255,.05)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,.06)", side="right")
    return fig


def tv_symbol(ticker):
    special = {"GC=F": "OANDA:XAUUSD", "SI=F": "OANDA:XAGUSD", "CL=F": "TVC:USOIL"}
    if ticker in special:
        return special[ticker]
    if ticker.endswith("=X"):
        core = ticker[:-2]
        if len(core) == 3:
            core = "USD" + core
        return "FX:" + core
    return ticker


def tv_chart(symbol, interval="15", height=460):
    html_code = f"""
    <div style="height:{height}px;width:100%;border-radius:16px;overflow:hidden">
      <div id="tv_chart" style="height:{height}px;width:100%"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>
        new TradingView.widget({{
          "autosize": true, "symbol": "{symbol}", "interval": "{interval}",
          "timezone": "Etc/UTC", "theme": "dark", "style": "1", "locale": "en",
          "allow_symbol_change": true, "hide_side_toolbar": false,
          "container_id": "tv_chart"
        }});
      </script>
    </div>
    """
    components.html(html_code, height=height)


# ---------- UI helpers ----------
def alert_card_html(a, now):
    above = a["condition"] == "above"
    cls = "up" if above else "down"
    label = "ABOVE" if above else "BELOW"
    meta = ""
    if now:
        d = (a["target"] - now) / now * 100
        passed = (d <= 0) if above else (d >= 0)
        away = "⚡ reached, fires on next check" if passed else f"{abs(d):.2f}% away"
        meta = f"now {now:.5f} · {away}"
    note = f'<div class="a-note">{html.escape(a["note"])}</div>' if a.get("note") else ""
    return (f'<div class="a-top"><span class="a-pair">{html.escape(a["pair"])}</span>'
            f'<span class="badge {cls}">{label}</span></div>'
            f'<div class="a-target">{a["target"]:.5f}</div>'
            f'<div class="a-meta">{meta}</div>{note}')


# ---------- page ----------
st.markdown('<div class="brand">💱 FX Alerts</div>', unsafe_allow_html=True)

data, sha = load()
active = [a for a in data["alerts"] if a.get("active", True)]
done = [a for a in data["alerts"] if not a.get("active", True)]

pair = st.selectbox("Pair", list(PAIRS) + ["Custom..."], label_visibility="collapsed")
if pair == "Custom...":
    ticker = st.text_input("Yahoo Finance ticker", "EURNOK=X").strip().upper()
    pair = ticker
else:
    ticker = PAIRS[pair]

q = quote(ticker)
cur = q[0] if q else None
if q:
    chg = (q[0] - q[1]) / q[1] * 100
    cls = "up" if chg >= 0 else "down"
    arrow = "▲" if chg >= 0 else "▼"
    st.markdown(
        f'<div class="hero"><div class="hero-top"><span class="hero-pair">{html.escape(pair)}</span>'
        f'<span class="chip {cls}">{arrow} {chg:+.2f}%</span></div>'
        f'<div class="hero-price">{q[0]:.5f}</div>'
        f'<div class="hero-sub">Live price · refreshes every 30 seconds</div></div>',
        unsafe_allow_html=True)
else:
    st.warning("Price not available for this ticker.")

target_default = float(cur or 1.0)
target = st.session_state.get(f"target_{ticker}", target_default)

# ----- chart -----
with st.container(border=True):
    if st.toggle("📈 Chart", value=True):
        try:
            mode = st.radio("Chart type", ["Candles", "TradingView"], horizontal=True,
                            label_visibility="collapsed")
            tf = st.radio("Timeframe", list(TF_CFG), index=2, horizontal=True,
                          label_visibility="collapsed")
            if mode == "TradingView":
                tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1D": "D"}
                tv_chart(tv_symbol(ticker), tf_map[tf])
            else:
                df = candles(ticker, tf)
                if df is None:
                    st.warning("No chart data for this timeframe. Try another one.")
                else:
                    my_alerts = [a for a in active if a["ticker"] == ticker]
                    st.plotly_chart(make_chart(df, my_alerts, target, cur),
                                    use_container_width=True, config={"displaylogo": False})
                    st.caption("Green dashed = alert above · red dashed = alert below · "
                               "yellow dotted = new alert you're setting")
        except Exception as e:
            st.error(f"Chart failed: {e!r}")

# ----- tabs -----
tab_new, tab_active, tab_done = st.tabs(
    ["➕ New alert", f"🔔 Active ({len(active)})", f"✅ Triggered ({len(done)})"])

with tab_new:
    cond = st.radio("Notify me when price goes", ["above", "below"], horizontal=True)
    target = st.number_input("Target price", value=target_default, format="%.5f",
                             step=0.0001, key=f"target_{ticker}")
    if cur and target:
        d = (target - cur) / cur * 100
        st.caption(f"{abs(d):.2f}% {'above' if d >= 0 else 'below'} the current price")
    note = st.text_input("Note (optional)", placeholder="e.g. breakout level")

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

with tab_active:
    if not active:
        st.info("No active alerts yet. Create one in the first tab.")
    for a in active:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(alert_card_html(a, price(a["ticker"])), unsafe_allow_html=True)
            if c2.button("🗑", key="d" + a["id"]):
                data["alerts"] = [x for x in data["alerts"] if x["id"] != a["id"]]
                save(data, sha, f"Delete alert {a['id']}")
                st.rerun()

with tab_done:
    if not done:
        st.info("Nothing triggered yet.")
    for a in done:
        with st.container(border=True):
            when = a.get("triggered_at", "").replace("T", " ").replace("+00:00", " UTC")
            st.markdown(
                f'<div class="done">✅ <b>{html.escape(a["pair"])}</b> {a["condition"]} '
                f'<b>{a["target"]:.5f}</b><br><small>{when}</small></div>',
                unsafe_allow_html=True)
    if done and st.button("Clear triggered"):
        data["alerts"] = active
        save(data, sha, "Clear triggered alerts")
        st.rerun()

with st.expander("⚙️ Settings"):
    if NTFY_TOPIC:
        if st.button("Send test notification"):
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data="Test from FX Alerts".encode(),
                          headers={"Title": "FX Alerts test"}, timeout=10)
            st.success("Sent")
    st.caption("Alerts are checked by GitHub Actions and delivered through ntfy.")
