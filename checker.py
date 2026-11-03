"""Run by GitHub Actions every 5 minutes."""
import json
import os
from datetime import datetime, timezone

import requests
import yfinance as yf

TOPIC = os.environ["NTFY_TOPIC"]


def get_price(ticker):
    try:
        h = yf.Ticker(ticker).history(period="1d", interval="1m")
        return float(h["Close"].iloc[-1])
    except Exception as e:
        print(f"price fetch failed for {ticker}: {e}")
        return None


def notify(title, msg):
    requests.post(
        f"https://ntfy.sh/{TOPIC}",
        data=msg.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
        timeout=15,
    )


with open("alerts.json") as f:
    data = json.load(f)

changed = False
for a in data["alerts"]:
    if not a.get("active", True):
        continue
    p = get_price(a["ticker"])
    if p is None:
        continue
    hit = p >= a["target"] if a["condition"] == "above" else p <= a["target"]
    print(f"{a['pair']}: {p:.5f} (alert {a['condition']} {a['target']})  hit={hit}")
    if hit:
        msg = f"{a['pair']} is {p:.5f} ({a['condition']} {a['target']:.5f})"
        if a.get("note"):
            msg += f"\n{a['note']}"
        notify(f"Forex alert: {a['pair']}", msg)
        a["active"] = False
        a["triggered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        changed = True

if changed:
    with open("alerts.json", "w") as f:
        json.dump(data, f, indent=2)
