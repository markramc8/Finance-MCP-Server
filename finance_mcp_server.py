# server.py (local version without Auth)
import os
import sys
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("finance_weather", stateless_http=True, port=4010)

# API Keys
twelve_data_api_key = os.getenv("TWELVE_DATA_API_KEY", "")

# --- WEATHER TOOLS ---
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"

async def make_nws_request(url: str) -> dict[str, Any] | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=headers, timeout=30.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

def format_alert(feature: dict) -> str:
    props = feature["properties"]
    return (
        f"\nEvent: {props.get('event','Unknown')}\n"
        f"Area: {props.get('areaDesc','Unknown')}\n"
        f"Severity: {props.get('severity','Unknown')}\n"
        f"Description: {props.get('description','No description available')}\n"
        f"Instructions: {props.get('instruction','No specific instructions')}\n"
    )

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state (two-letter code)."""
    data = await make_nws_request(f"{NWS_API_BASE}/alerts/active/area/{state.upper()}")
    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts."
    features = data["features"]
    if not features:
        return "No active alerts."
    return "\n---\n".join(format_alert(f) for f in features)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location."""
    pt = await make_nws_request(f"{NWS_API_BASE}/points/{latitude},{longitude}")
    if not pt:
        return "Unable to fetch point data."
    forecast_url = pt["properties"]["forecast"]
    fx = await make_nws_request(forecast_url)
    if not fx:
        return "Unable to fetch forecast."
    periods = fx["properties"]["periods"]
    return "\n---\n".join(
        f"{p['name']}: {p['temperature']}°{p['temperatureUnit']}, "
        f"Wind {p['windSpeed']} {p['windDirection']}, {p['detailedForecast']}"
        for p in periods[:5]
    )

# --- FINANCE TOOLS USING TWELVE DATA ---

@mcp.tool()
async def get_stock_quote(symbol: str) -> str:
    """Latest price, percent change, and volume."""
    url = "https://api.twelvedata.com/quote"
    params = {"symbol": symbol.upper(), "apikey": twelve_data_api_key}
    async with httpx.AsyncClient() as client:
        data = (await client.get(url, params=params)).json()
    if data.get("close"):
        return (
            f"{symbol.upper()}: ${data['close']} "
            f"({data.get('percent_change','N/A')}%), "
            f"Vol: {data.get('volume','N/A')}, "
            f"H/L: {data.get('high','N/A')}/{data.get('low','N/A')}"
        )
    return f"Error: {data.get('message','Unknown')}"

@mcp.tool()
async def get_stock_performance(symbol: str, days: int) -> str:
    """Percent change, high/low over past N days."""
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol.upper(), "interval": "1day", "outputsize": days, "apikey": twelve_data_api_key}
    async with httpx.AsyncClient() as client:
        data = (await client.get(url, params=params)).json()
    vals = data.get("values", [])
    if len(vals) < days:
        return "Insufficient data."
    closes = [float(v["close"]) for v in vals]
    pct = (closes[0] - closes[-1]) / closes[-1] * 100
    high = max(float(v["high"]) for v in vals)
    low = min(float(v["low"]) for v in vals)
    return f"{symbol.upper()} changed {pct:.2f}% over {days}d. High: {high}, Low: {low}"

@mcp.tool()
async def get_volatility(symbol: str, days: int = 30) -> str:
    """Stddev and trend."""
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol.upper(), "interval": "1day", "outputsize": days, "apikey": twelve_data_api_key}
    async with httpx.AsyncClient() as client:
        vals = (await client.get(url, params=params)).json().get("values", [])
    if len(vals) < days:
        return "Insufficient data."
    closes = [float(v["close"]) for v in vals]
    import statistics
    stdev = statistics.pstdev(closes)
    trend = "upward" if closes[0] > closes[-1] else "downward"
    return f"{symbol.upper()} trend: {trend}, volatility: {stdev:.2f}"

# --- FASTAPI APP SETUP ---

app = FastAPI(title="MCP Finance & Weather (Local)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Mount MCP at /mcp
app.mount("/mcp", mcp.streamable_http_app)

if __name__ == "__main__":
    import uvicorn
    print("Starting MCP locally on http://127.0.0.1:4010 …", file=sys.stderr, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=4010)
