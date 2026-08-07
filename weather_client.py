"""
Client for the National Weather Service API.

Responsibilities:
- Resolve locations into latitude/longitude
- Resolve coordinates into NWS grid points
- Fetch forecasts and active alerts
- Normalize responses into weather_documents records
"""

import hashlib
import os
import requests
from datetime import datetime, timezone


_NWS_BASE_URL = os.environ.get(
    "NWS_BASE_URL",
    "https://api.weather.gov"
)

_GEOCODE_URL = "https://nominatim.openstreetmap.org/search"

_DEFAULT_TIMEOUT = 30


class WeatherClient:
    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT
    ):
        self.base_url = _NWS_BASE_URL.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update(
            {"User-Agent": "Weather-Intelligence-Homework"}
        )

    def get(self, path: str, params=None):
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def geocode_location(self,location: str):
        response = requests.get(_GEOCODE_URL,
            params={
                "q": location,
                "format": "json",
                "limit": 1
            },
            headers={
                "User-Agent": "Weather-Intelligence-Homework"
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            raise ValueError(
                f"Unable to geocode {location}"
            )

        return {
            "lat": float(results[0]["lat"]),
            "lon": float(results[0]["lon"])
        }

    def get_points(self, lat, lon):
        return self.get(
            f"/points/{lat},{lon}"
        )

    def get_forecast(self, grid_id, grid_x,grid_y):
        return self.get(
            f"/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast"
        )



    def get_alerts(self, state):
        return self.get(
            "/alerts/active",
            params={
                "area": state
            }
        )

    def normalize_forecast(self, location, forecast):
        documents = []
        properties = forecast["properties"]
        issued_at = properties.get(
            "updateTime"
        )

        for period in properties.get("periods",[]):
            stable_id = hashlib.sha256(
                (
                    f"{location}-"
                    f"{issued_at}-"
                    f"{period['number']}"
                ).encode()
            ).hexdigest()


            documents.append(
                {
                    "id": stable_id,
                    "location": location,
                    "source_type": "forecast",
                    "headline": period.get("name"),
                    "narrative_text": period.get(
                        "detailedForecast",
                        ""
                    ),
                    "issued_at": issued_at,
                    "payload": period,
                    "synced_at": datetime.now(
                        timezone.utc
                    )
                }
            )


        return documents

    def normalize_alerts(self, location,alerts):
        documents = []
        for feature in alerts.get(
            "features",[]):
            props = feature.get("properties",{})
            narrative = (props.get("description","") + "\n\n" + props.get("instruction","")
            )

            documents.append(
                {
                    "id": props.get("id"),
                    "location": location,
                    "source_type": "alert",
                    "headline": props.get("event"),
                    "narrative_text": narrative,
                    "issued_at": props.get("effective"),
                    "payload": props,
                    "synced_at": datetime.now(timezone.utc
                    )
                }
            )
        return documents

    def fetch_location(self,location):
        documents = []
        coords = self.geocode_location(location)
        points = self.get_points(coords["lat"],coords["lon"])
        props = points["properties"]
        forecast = self.get_forecast(props["gridId"], props["gridX"], props["gridY"])
        documents.extend(self.normalize_forecast(location, forecast))
        state = location.split(",")[-1].strip()
        alerts = self.get_alerts(state)
        documents.extend(self.normalize_alerts(location, alerts))
        return documents

    def fetch_locations(self, locations, limit=50):
        documents = []
        for location in locations:
            docs = self.fetch_location(location)
            documents.extend(docs)
            if len(documents) >= limit:
                break
        return documents[:limit]