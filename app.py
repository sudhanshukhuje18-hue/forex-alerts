import streamlit as st

st.title("Hello, it works")
st.write("Step 1: Streamlit is running")

try:
    import plotly
    st.write("Step 2: plotly OK")
    import yfinance as yf
    st.write("Step 3: yfinance OK")
    h = yf.Ticker("EURUSD=X").history(period="1d", interval="1m")
    st.write(f"Step 4: got {len(h)} price rows")
    st.write("Step 5: secrets found:", list(st.secrets.keys()))
except Exception as e:
    st.error(f"Failed: {e!r}")
