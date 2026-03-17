"""
HazardLookupService
Real seismic data from USGS ASCE 7-22 Design Maps API.
Wind speed uses ASCE 7-22 regional CA estimates (ATC API no longer publicly accessible).
"""
import httpx
import asyncio
from typing import Dict, Any

USGS_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"


def _sdc(sds: float, sd1: float) -> str:
    """ASCE 7 Table 11.6-1 Risk Cat II"""
    if sds >= 0.50 or sd1 >= 0.20:  return "D"
    if sds >= 0.33 or sd1 >= 0.133: return "C"
    if sds >= 0.167 or sd1 >= 0.067: return "B"
    return "A"


class HazardLookupService:

    async def get_seismic(self, lat: float, lon: float) -> Dict[str, Any]:
        try:
            params = {"latitude": lat, "longitude": lon,
                      "riskCategory": "II", "siteClass": "D", "title": "Petronus"}
            async with httpx.AsyncClient(timeout=7) as client:
                resp = await client.get(USGS_URL, params=params)
                resp.raise_for_status()
                # USGS ASCE 7-22 response: {"request": {...}, "response": {"data": {...}, "metadata": {...}}}
                out = resp.json().get("response", {}).get("data", {})

            sds = float(out.get("sds", 0) or 0)
            sd1 = float(out.get("sd1", 0) or 0)
            ss  = float(out.get("ss",  0) or 0)
            s1  = float(out.get("s1",  0) or 0)
            sdc = _sdc(sds, sd1)

            return {
                "sdc": sdc,
                "sds": round(sds, 3), "sd1": round(sd1, 3),
                "ss":  round(ss,  3), "s1":  round(s1,  3),
                "site_class": "D",
                "source": "USGS ASCE 7-22",
                "note": "Ss=%.3fg S1=%.3fg SDS=%.3fg SD1=%.3fg SDC %s" % (ss, s1, sds, sd1, sdc),
            }
        except Exception as e:
            return {
                "sdc": "D", "sds": 1.0, "sd1": 0.6, "ss": 1.5, "s1": 0.9,
                "site_class": "D", "source": "fallback",
                "note": "USGS unavailable — conservative CA default SDC D (err: %s)" % str(e)[:80],
            }

    async def get_wind(self, lat: float, lon: float) -> Dict[str, Any]:
        """ASCE 7-22 wind speed estimate for California by region."""
        vult = self._wind_ca_regional(lat, lon)
        return {
            "vult_mph": vult,
            "vasd_mph": round(vult / 1.265, 1),
            "exposure_category": "B",
            "source": "ASCE 7-22 CA regional",
            "note": "Vult=%.0f mph (ASCE 7-22 Risk Cat II Exposure B — CA regional estimate)" % vult,
        }

    async def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """Fetch real-time weather from wttr.in (free, no API key)."""
        try:
            url = f"https://wttr.in/{lat},{lon}?format=j1"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
                data = resp.json()
            cur = data["current_condition"][0]
            weather_desc = cur.get("weatherDesc", [{}])[0].get("value", "Unknown")
            return {
                "temp_f": float(cur.get("temp_F", 0)),
                "temp_c": float(cur.get("temp_C", 0)),
                "wind_mph": float(cur.get("windspeedMiles", 0)),
                "wind_dir": cur.get("winddir16Point", ""),
                "humidity_pct": float(cur.get("humidity", 0)),
                "description": weather_desc,
                "visibility_miles": float(cur.get("visibility", 0)),
                "source": "wttr.in real-time",
            }
        except Exception as e:
            return {"wind_mph": 0, "temp_f": 0, "description": "Unavailable", "source": f"error: {str(e)[:60]}"}

    async def get_all(self, lat: float, lon: float) -> Dict[str, Any]:
        seismic, wind, weather = await asyncio.gather(
            self.get_seismic(lat, lon),
            self.get_wind(lat, lon),
            self.get_current_weather(lat, lon),
        )
        return {"seismic": seismic, "wind": wind, "current_weather": weather}

    def _wind_ca_regional(self, lat: float, lon: float) -> float:
        """
        ASCE 7-22 Vult estimates for California regions.
        Coastal: 110 mph, High desert/inland empire: 130 mph,
        Bay Area/Sacramento: 115 mph, Northern CA coast: 120 mph.
        """
        # High desert / Coachella / Inland Empire
        if lon > -116.5 and lat < 34.5:
            return 130.0
        # San Bernardino / Riverside mountains
        if lon > -117.5 and lat > 33.8 and lat < 34.5:
            return 125.0
        # CA coast (within ~30 miles of coast)
        if lon < -120.5:
            return 110.0
        if lon < -121.5:
            return 110.0
        # Northern CA inland / Sierra foothills
        if lat > 38.5:
            return 120.0
        # SoCal coast (LA, SD)
        if lat < 34.5 and lon < -117.5:
            return 110.0
        # Default Central Valley / general CA
        return 115.0
