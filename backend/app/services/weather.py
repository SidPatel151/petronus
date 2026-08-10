"""
weather.py — Live weather at a lat/lon via Open-Meteo (free, no API key).
Runs in parallel with other site context calls.
"""
import httpx
from typing import Dict, Any, Optional

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → human label (subset)
_WMO_LABELS: Dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}


async def get_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Fetch current weather conditions at lat/lon.
    Returns None on any failure — never blocks generation.
    """
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(_OPEN_METEO, params={
                "latitude":  lat,
                "longitude": lon,
                "current":   "temperature_2m,relative_humidity_2m,precipitation,"
                             "weather_code,wind_speed_10m,wind_direction_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit":  "mph",
                "timezone":  "auto",
            })
        if resp.status_code != 200:
            return None
        data   = resp.json()
        cur    = data.get("current", {})
        code   = cur.get("weather_code", 0)
        temp_f = cur.get("temperature_2m")
        return {
            "temp_f":       round(temp_f, 1) if temp_f is not None else None,
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_mph":     cur.get("wind_speed_10m"),
            "wind_dir_deg": cur.get("wind_direction_10m"),
            "precip_in":    round(cur.get("precipitation", 0) * 0.03937, 3),
            "condition":    _WMO_LABELS.get(code, f"Code {code}"),
            "wmo_code":     code,
            "timezone":     data.get("timezone", ""),
            "source":       "Open-Meteo",
        }
    except Exception:
        return None


def climate_zone_hint(temp_f: Optional[float], humidity_pct: Optional[int]) -> str:
    """
    Very rough HVAC climate hint from current conditions.
    Used to nudge AI room program toward appropriate HVAC sizing.
    """
    if temp_f is None:
        return "unknown"
    if temp_f >= 85 and (humidity_pct or 0) >= 60:
        return "hot-humid"
    if temp_f >= 85:
        return "hot-dry"
    if temp_f <= 35:
        return "cold"
    if temp_f <= 55:
        return "mixed-cool"
    return "mild"
