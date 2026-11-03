import base64
import json
import uuid
from datetime import datetime, timezone

import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Forex Alerts", page_icon="💱", layout="centered")

PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "USD/INR": "INR=X", "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X",
    "USD/CHF": "CHF=X", "NZD/USD": "NZDUSD=X", "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X", "Gold (GC=F)": "GC=F",
}

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
    r.raise_for_status()
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
    r.raise_for_status()


@st.cache_data(ttl=30)
def price(ticker):
    try:
        h = yf.Ticker(ticker).history(period="1d", interval="1m")
        return float(h["Close"].iloc[-1])
    except Exception:
        return None


# ---------- UI ----------
st.title("💱 Forex Alerts")

data, sha = load()

with st.expander("➕ New alert", expanded=True):
    pair = st.selectbox("Pair", list(PAIRS))
    cur = price(PAIRS[pair])
    if cur:
        st.caption(f"Current price: **{cur:.5f}**")
    cond = st.radio("Notify me when price goes", ["above", "below"], horizontal=True)
    target = st.number_input("Target price", value=float(cur or 1.0), format="%.5f", step=0.0001)
    note = st.text_input("Note (optional)")
    if st.button("Create alert", type="primary", use_container_width=True):
        data["alerts"].append({
            "id": uuid.uuid4().hex[:8],
            "pair": pair,
            "ticker": PAIRS[pair],
            "condition": cond,
            "target": target,
            "note": note,
            "active": True,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        save(data, sha, f"Add alert {pair} {cond} {target}")
        st.success("Alert created")
        st.rerun()

st.subheader("Active alerts")
active = [a for a in data["alerts"] if a.get("active", True)]
if not active:
    st.info("No active alerts.")
for a in active:
    c1, c2 = st.columns([4, 1])
    now = price(a["ticker"])
    c1.markdown(
        f"**{a['pair']}** {a['condition']} **{a['target']:.5f}**  \n"
        f"now: {now:.5f}" if now else f"**{a['pair']}** {a['condition']} **{a['target']:.5f}**"
    )
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
