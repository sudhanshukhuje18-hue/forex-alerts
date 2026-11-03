"""Run by GitHub Actions. Looks at all 1-minute candles since each alert was created."""
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

TOPIC = os.environ["NTFY_TOPIC"]


def get_range(ticker, created):
    """Return (last_price, high, low) of all candles since the alert was created."""
    try:
        h = yf.Ticker(ticker).history(period="5d", interval="1m")
    except Exception as e:
        print(f"  price fetch failed for {ticker}: {e}")
        return None
    if h is None or h.empty:
        print(f"  no price data returned for {ticker}")
        return None
    last = float(h["Close"].iloc[-1])
    recent = h[h.index >= pd.Timestamp(created)]
    if recent.empty:
        recent = h.tail(1)
    return last, float(recent["High"].max()), float(recent["Low"].min())


def notify(title, msg):
    r = requests.post(
        f"https://ntfy.sh/{TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
        timeout=15,
    )
    print(f"  ntfy response: {r.status_code}")
    return r.ok


with open("alerts.json") as f:
    data = json.load(f)

active = [a for a in data["alerts"] if a.get("active", True)]
print(f"{len(active)} active alert(s)")

changed = False
for a in active:
    print(f"{a['pair']} {a['condition']} {a['target']}")
    created = a.get("created", "2000-01-01T00:00:00+00:00")
    res = get_range(a["ticker"], created)
    if res is None:
        continue
    last, high, low = res
    hit = high >= a["target"] if a["condition"] == "above" else low <= a["target"]
    print(f"  last={last:.5f} high={high:.5f} low={low:.5f} hit={hit}")
    if hit:
        msg = f"{a['pair']} touched {a['target']:.5f} ({a['condition']}). Now {last:.5f}"
        if a.get("note"):
            msg += f"\n{a['note']}"
        if notify(f"Forex alert: {a['pair']}", msg):
            a["active"] = False
            a["triggered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            changed = True

if changed:
    with open("alerts.json", "w") as f:
        json.dump(data, f, indent=2)
