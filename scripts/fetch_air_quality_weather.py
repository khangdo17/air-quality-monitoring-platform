#!/usr/bin/env python3
"""Fetch district-level Ho Chi Minh City air quality and weather data.

Data sources:
- Open-Meteo Air Quality API
- Open-Meteo Forecast API

The script writes latest rows into Supabase PostgreSQL through the REST API.
It expects Supabase credentials through environment variables or a local .env.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


MIN_PYTHON = (3, 11)
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = (10, 90)
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = [2, 5, 10]
DISTRICT_DELAY_SECONDS = 0.35

AIR_QUALITY_FIELDS = [
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "us_aqi",
    "uv_index",
]

WEATHER_CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_gusts_10m",
]

WEATHER_HOURLY_FIELDS = ["precipitation_probability"]

HCM_DISTRICTS = [
    {"district": "Bình Tân", "latitude": 10.7656, "longitude": 106.6030},
    {"district": "Quận 8", "latitude": 10.7245, "longitude": 106.6287},
    {"district": "Quận 6", "latitude": 10.7460, "longitude": 106.6357},
    {"district": "Tân Bình", "latitude": 10.8017, "longitude": 106.6520},
    {"district": "Quận 11", "latitude": 10.7629, "longitude": 106.6501},
    {"district": "Tân Phú", "latitude": 10.7901, "longitude": 106.6289},
    {"district": "Gò Vấp", "latitude": 10.8380, "longitude": 106.6653},
    {"district": "Quận 5", "latitude": 10.7540, "longitude": 106.6633},
    {"district": "Quận 12", "latitude": 10.8672, "longitude": 106.6413},
    {"district": "Quận 4", "latitude": 10.7578, "longitude": 106.7063},
    {"district": "Quận 10", "latitude": 10.7746, "longitude": 106.6679},
    {"district": "Bình Chánh", "latitude": 10.6874, "longitude": 106.5939},
    {"district": "Quận 1", "latitude": 10.7757, "longitude": 106.7004},
    {"district": "Bình Thạnh", "latitude": 10.8106, "longitude": 106.7091},
    {"district": "Hóc Môn", "latitude": 10.8835, "longitude": 106.5868},
    {"district": "Thủ Đức", "latitude": 10.8494, "longitude": 106.7537},
    {"district": "Quận 7", "latitude": 10.7380, "longitude": 106.7218},
    {"district": "Phú Nhuận", "latitude": 10.7992, "longitude": 106.6803},
]


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def getenv_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_open_meteo_time_to_timestamptz(value: str) -> str:
    if value.endswith("Z") or "+" in value[10:] or "-" in value[10:]:
        return value
    return f"{value}:00+07:00" if len(value) == 16 else f"{value}+07:00"


def request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    max_attempts = len(RETRY_BACKOFF_SECONDS) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code in RETRY_STATUS_CODES:
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt == max_attempts:
                raise
            sleep_before_retry(attempt, exc)
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in RETRY_STATUS_CODES or attempt == max_attempts:
                raise
            sleep_before_retry(attempt, exc)

    raise RuntimeError("Open-Meteo request failed after retries")


def sleep_before_retry(attempt: int, exc: Exception) -> None:
    base_delay = RETRY_BACKOFF_SECONDS[attempt - 1]
    delay = base_delay + random.uniform(0, 0.5)
    print(
        f"Transient Open-Meteo request error on attempt {attempt}; "
        f"retrying in {delay:.1f}s ({exc.__class__.__name__}).",
        file=sys.stderr,
    )
    time.sleep(delay)


def latest_hourly_row(payload: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise RuntimeError("Open-Meteo hourly response did not include time values")

    selected_index = None
    for index in range(len(times) - 1, -1, -1):
        if any(
            index < len(hourly.get(field) or [])
            and (hourly.get(field) or [])[index] is not None
            for field in fields
        ):
            selected_index = index
            break

    if selected_index is None:
        raise RuntimeError("Open-Meteo hourly response did not include usable values")

    row: dict[str, Any] = {"time": times[selected_index]}
    for field in fields:
        values = hourly.get(field) or []
        row[field] = values[selected_index] if selected_index < len(values) else None
    return row


def weather_condition(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code == 0:
        return "clear"
    if code in {1, 2, 3}:
        return "partly_cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "mixed"


def calculate_us_aqi_from_pm25(pm25: float | int | None) -> int | None:
    if pm25 is None:
        return None

    concentration = float(pm25)
    if concentration < 0:
        return None

    breakpoints = [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]

    for low_concentration, high_concentration, low_aqi, high_aqi in breakpoints:
        if low_concentration <= concentration <= high_concentration:
            return round(
                ((high_aqi - low_aqi) / (high_concentration - low_concentration))
                * (concentration - low_concentration)
                + low_aqi
            )

    return 500


def aqi_status(aqi: int | None) -> tuple[str, str, str]:
    if aqi is None:
        return (
            "pending",
            "unknown",
            "Waiting for fresh district-level estimate.",
        )
    if aqi <= 50:
        return ("Good", "low", "Good window for normal outdoor activity.")
    if aqi <= 100:
        return (
            "Moderate",
            "medium",
            "Acceptable conditions; sensitive groups should watch symptoms.",
        )
    if aqi <= 150:
        return (
            "Sensitive",
            "elevated",
            "Sensitive groups should reduce long outdoor exposure.",
        )
    if aqi <= 200:
        return (
            "Unhealthy",
            "high",
            "Limit outdoor exertion and consider a mask near traffic.",
        )
    return (
        "Very Unhealthy",
        "very_high",
        "Avoid prolonged outdoor activity and use indoor filtration where possible.",
    )


class SupabaseRestClient:
    def __init__(self, url: str, service_role_key: str) -> None:
        self.base_url = url.rstrip("/")
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        table: str,
        body: Any | None = None,
        params: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer

        response = requests.request(
            method,
            f"{self.base_url}/rest/v1/{table}",
            headers=headers,
            params=params,
            json=body,
            timeout=40,
        )
        response.raise_for_status()
        return response.json() if response.text else None


def build_district_observation(district: dict[str, Any], timezone_name: str) -> dict[str, Any]:
    latitude = district["latitude"]
    longitude = district["longitude"]

    air_quality = request_json(
        AIR_QUALITY_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(AIR_QUALITY_FIELDS),
            "timezone": timezone_name,
            "forecast_days": 1,
            "past_days": 1,
        },
    )
    weather = request_json(
        WEATHER_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(WEATHER_CURRENT_FIELDS),
            "hourly": ",".join(WEATHER_HOURLY_FIELDS),
            "timezone": timezone_name,
            "forecast_days": 1,
        },
    )

    air_row = latest_hourly_row(air_quality, AIR_QUALITY_FIELDS)
    weather_current = weather.get("current") or {}
    precipitation_row = latest_hourly_row(weather, WEATHER_HOURLY_FIELDS)
    pm25 = air_row.get("pm2_5")
    aqi = air_row.get("us_aqi")
    if aqi is None:
        aqi = calculate_us_aqi_from_pm25(pm25)
    status, risk_level, recommendation = aqi_status(aqi)

    return {
        "district": district["district"],
        "city": "Ho Chi Minh City",
        "latitude": latitude,
        "longitude": longitude,
        "aqi": aqi,
        "pm25": pm25,
        "pm10": air_row.get("pm10"),
        "no2": air_row.get("nitrogen_dioxide"),
        "o3": air_row.get("ozone"),
        "so2": air_row.get("sulphur_dioxide"),
        "co": air_row.get("carbon_monoxide"),
        "uv_index": air_row.get("uv_index"),
        "temperature": weather_current.get("temperature_2m"),
        "humidity": weather_current.get("relative_humidity_2m"),
        "precipitation_probability": precipitation_row.get("precipitation_probability"),
        "wind_speed": weather_current.get("wind_speed_10m"),
        "wind_gust": weather_current.get("wind_gusts_10m"),
        "pressure": weather_current.get("pressure_msl"),
        "cloud_cover": weather_current.get("cloud_cover"),
        "weather_condition": weather_condition(weather_current.get("weather_code")),
        "status": status,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "measured_at": local_open_meteo_time_to_timestamptz(air_row["time"]),
        "updated_at": utc_now_iso(),
    }


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError("Python 3.11 or newer is required")

    load_dotenv()

    supabase = SupabaseRestClient(
        getenv_required("SUPABASE_URL"),
        getenv_required("SUPABASE_SERVICE_ROLE_KEY"),
    )
    timezone_name = os.getenv("CITY_TIMEZONE", "Asia/Bangkok")
    run_id = str(uuid.uuid4())
    started_at = utc_now_iso()

    supabase.request(
        "POST",
        "air_quality_pipeline_runs",
        body={
            "run_id": run_id,
            "status": "running",
            "rows_processed": 0,
            "rows_failed": 0,
            "started_at": started_at,
        },
        prefer="return=minimal",
    )

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for district in HCM_DISTRICTS:
        try:
            rows.append(build_district_observation(district, timezone_name))
        except Exception as exc:  # noqa: BLE001 - record per-district failures for observability.
            failures.append({"district": district["district"], "error": str(exc)})
        time.sleep(DISTRICT_DELAY_SECONDS)

    try:
        if not rows:
            raise RuntimeError("No district rows were fetched successfully")

        supabase.request(
            "POST",
            "district_air_weather_latest",
            body=rows,
            params={"on_conflict": "district"},
            prefer="resolution=merge-duplicates,return=minimal",
        )

        status = "success" if not failures else "partial_success"
        supabase.request(
            "PATCH",
            "air_quality_pipeline_runs",
            body={
                "status": status,
                "rows_processed": len(rows),
                "rows_failed": len(failures),
                "error_message": json.dumps(failures, ensure_ascii=False) if failures else None,
                "ended_at": utc_now_iso(),
            },
            params={"run_id": f"eq.{run_id}"},
            prefer="return=minimal",
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "rows_processed": len(rows),
                    "rows_failed": len(failures),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        rows_processed = len(rows)
        if failures:
            failed_districts = ", ".join(failure["district"] for failure in failures)
            print(f"Partial success. Failed districts: {failed_districts}", file=sys.stderr)
        return 0 if rows_processed > 0 else 1
    except Exception as exc:
        supabase.request(
            "PATCH",
            "air_quality_pipeline_runs",
            body={
                "status": "failed",
                "rows_processed": len(rows),
                "rows_failed": len(failures) or len(HCM_DISTRICTS),
                "error_message": str(exc),
                "ended_at": utc_now_iso(),
            },
            params={"run_id": f"eq.{run_id}"},
            prefer="return=minimal",
        )
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
