#!/usr/bin/env python3
"""Fetch district-level Ho Chi Minh City air quality and weather data.

Data sources:
- Google Air Quality API (history:lookup only) - primary air quality, ~500 m grid
- Open-Meteo Air Quality API (CAMS global) - air quality fallback, ~25-45 km grid
- Open-Meteo Forecast API - weather

The script writes hourly history into ``air_quality_hourly`` and
``weather_hourly`` and keeps ``district_air_weather_latest`` in sync with the
newest stored hour. It expects credentials through environment variables or a
local .env.

Licensing note
--------------
Google Maps Platform Service Specific Terms, Table 2.2.1 (Air Quality API
Caching Permissions), last modified October 28, 2026:

* "Current conditions values / Hourly forecast values" may be cached for
  "One hour, after which Customer must delete the cached Google Maps Content".
* "Historic values for a specific location and given time range" may be cached
  "Until the Agreement is terminated".

This script therefore calls ``history:lookup`` exclusively and never
``currentConditions:lookup`` or ``forecast:lookup``. Everything persisted from
Google is a historic value for a specific location and time range.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests


MIN_PYTHON = (3, 11)
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GOOGLE_AIR_QUALITY_HISTORY_URL = "https://airquality.googleapis.com/v1/history:lookup"

REQUEST_TIMEOUT = (10, 45)
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = [2, 5, 10]
BATCH_SIZE = 6
BATCH_DELAY_SECONDS = 0.25
DEFAULT_CITY_TIMEZONE = "Asia/Bangkok"
UPSERT_CHUNK_SIZE = 500

# Google is called every N hours. Each call asks for GOOGLE_HISTORY_HOURS hours,
# so consecutive runs cover every hour without gaps.
#   18 districts x (24 / 2) runs x 30 days = 6,480 calls/month.
# The window must be at least 2x the cadence to survive a missed cron run.
# A run at hour R stores hours R-1 .. R-GOOGLE_HISTORY_HOURS. If the run at R
# never fires, its hours have to be covered by its neighbours at R-2 and R+2:
#   window 2 -> R-1, R-2 lost      window 3 -> R-2 lost
#   window 4 -> nothing lost (R+2 covers R-1, R-2; R-2 covers R-3, R-4)
# GitHub Actions cron is best-effort, so 4 it is.
#
# The window does not change the price. The Air Quality API free tier is 10,000
# calls/month across every method and history is billed per response page;
# GOOGLE_PAGE_SIZE >= GOOGLE_HISTORY_HOURS keeps the response to a single page
# and nextPageToken is never followed, so one district-run is always exactly
# one billed call whatever the window.
GOOGLE_RUN_EVERY_HOURS = 2
GOOGLE_HISTORY_HOURS = 4
GOOGLE_PAGE_SIZE = GOOGLE_HISTORY_HOURS
GOOGLE_REGION_CODE = "VN"
GOOGLE_LOCAL_AQI_CODE = "usa_epa"
GOOGLE_REQUEST_TIMEOUT = (10, 30)
GOOGLE_CALL_DELAY_SECONDS = 0.1

SOURCE_GOOGLE = "google_aq"
SOURCE_CAMS = "open_meteo_cams"

# The reference "Reported pollutants" table spells fine particulate matter
# ``p25`` while the local-AQI pages use ``pm25``. Accept both.
GOOGLE_POLLUTANT_CODES = {
    "pm25": "pm25",
    "p25": "pm25",
    "pm10": "pm10",
    "no2": "no2",
    "o3": "o3",
}

# Google reports NO2 and O3 in ppb; CAMS reports ug/m3. Both are stored as
# ug/m3 so the two sources share a column. Molar volume 24.45 L/mol at 25 C and
# 1013.25 hPa: ug/m3 = ppb * molecular_weight / 24.45.
PPB_TO_UG_PER_M3 = {
    "no2": 46.0055 / 24.45,
    "o3": 48.00 / 24.45,
}

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

WEATHER_HOURLY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "precipitation_probability",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_gusts_10m",
]

# Subset of WEATHER_HOURLY_FIELDS persisted to weather_hourly.
WEATHER_HISTORY_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_gusts_10m",
    "weather_code",
]

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

API_REQUESTS_ATTEMPTED = 0
GOOGLE_API_CALLS = 0
_SECRETS: list[str] = []


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        _SECRETS.append(value)


def scrub(text: str) -> str:
    """Remove credentials from anything written to logs or the database."""
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


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


def parse_open_meteo_time(value: str, timezone_name: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    city_timezone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=city_timezone)
    return parsed.astimezone(city_timezone)


def local_open_meteo_time_to_timestamptz(value: str, timezone_name: str) -> str:
    return parse_open_meteo_time(value, timezone_name).isoformat()


def parse_rfc3339(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def floor_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def request_json(url: str, params: dict[str, Any]) -> Any:
    global API_REQUESTS_ATTEMPTED

    max_attempts = len(RETRY_BACKOFF_SECONDS) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            API_REQUESTS_ATTEMPTED += 1
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code in RETRY_STATUS_CODES:
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt == max_attempts:
                raise
            sleep_before_retry(attempt, exc, "Open-Meteo")
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in RETRY_STATUS_CODES or attempt == max_attempts:
                raise
            sleep_before_retry(attempt, exc, "Open-Meteo")

    raise RuntimeError("Open-Meteo request failed after retries")


def sleep_before_retry(attempt: int, exc: Exception, source: str) -> None:
    base_delay = RETRY_BACKOFF_SECONDS[attempt - 1]
    delay = base_delay + random.uniform(0, 0.5)
    print(
        f"Transient {source} request error on attempt {attempt}; "
        f"retrying in {delay:.1f}s ({exc.__class__.__name__}).",
        file=sys.stderr,
    )
    time.sleep(delay)


def normalize_batch_response(response_json: Any, expected_count: int, source: str) -> list[dict[str, Any]]:
    if isinstance(response_json, list):
        responses = response_json
    elif isinstance(response_json, dict):
        responses = [response_json]
    else:
        raise RuntimeError(f"{source} response had unexpected type: {type(response_json).__name__}")

    if len(responses) != expected_count:
        raise RuntimeError(
            f"{source} response count mismatch: expected {expected_count}, got {len(responses)}"
        )

    invalid_indexes = [
        index for index, response in enumerate(responses) if not isinstance(response, dict)
    ]
    if invalid_indexes:
        raise RuntimeError(f"{source} response included non-object items at indexes {invalid_indexes}")

    return responses


def selected_hourly_index(
    payload: dict[str, Any],
    fields: list[str],
    timezone_name: str,
    now: datetime,
) -> int:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise RuntimeError("Open-Meteo hourly response did not include time values")

    city_timezone = ZoneInfo(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=city_timezone)
    else:
        now = now.astimezone(city_timezone)

    latest_past_index: int | None = None
    latest_past_time: datetime | None = None
    closest_index: int | None = None
    closest_time: datetime | None = None
    closest_distance: float | None = None

    for index, raw_time in enumerate(times):
        has_value = any(
            index < len(hourly.get(field) or [])
            and (hourly.get(field) or [])[index] is not None
            for field in fields
        )
        if not has_value:
            continue

        try:
            observed_time = parse_open_meteo_time(str(raw_time), timezone_name)
        except ValueError:
            continue

        if observed_time <= now and (
            latest_past_time is None or observed_time > latest_past_time
        ):
            latest_past_index = index
            latest_past_time = observed_time

        distance = abs((observed_time - now).total_seconds())
        if closest_distance is None or distance < closest_distance or (
            distance == closest_distance
            and closest_time is not None
            and observed_time < closest_time
        ):
            closest_index = index
            closest_time = observed_time
            closest_distance = distance

    if latest_past_index is not None:
        return latest_past_index
    if closest_index is not None:
        return closest_index

    raise RuntimeError("Open-Meteo hourly response did not include usable values near current time")


def current_hourly_row(
    payload: dict[str, Any],
    fields: list[str],
    timezone_name: str,
    now: datetime,
) -> dict[str, Any]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    selected_index = selected_hourly_index(payload, fields, timezone_name, now)

    if selected_index >= len(times):
        raise RuntimeError("Open-Meteo hourly response did not include usable values")

    row: dict[str, Any] = {"time": times[selected_index]}
    for field in fields:
        values = hourly.get(field) or []
        row[field] = values[selected_index] if selected_index < len(values) else None
    return row


def iter_past_hourly_rows(
    payload: dict[str, Any],
    fields: list[str],
    timezone_name: str,
    now: datetime,
) -> Iterable[tuple[datetime, dict[str, Any]]]:
    """Yield every hourly row at or before the current hour.

    Open-Meteo returns forecast hours alongside past ones. Future rows are
    skipped so the history tables only ever hold observed/analysed hours.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    cutoff = floor_to_hour(now.astimezone(ZoneInfo(timezone_name)))

    for index, raw_time in enumerate(times):
        try:
            observed_at = parse_open_meteo_time(str(raw_time), timezone_name)
        except ValueError:
            continue
        if observed_at > cutoff:
            continue

        values = {}
        for field in fields:
            column = hourly.get(field) or []
            values[field] = column[index] if index < len(column) else None
        if all(value is None for value in values.values()):
            continue

        yield observed_at, values


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

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
        written = 0
        for start in range(0, len(rows), UPSERT_CHUNK_SIZE):
            chunk = rows[start : start + UPSERT_CHUNK_SIZE]
            self.request(
                "POST",
                table,
                body=chunk,
                params={"on_conflict": on_conflict},
                prefer="resolution=merge-duplicates,return=minimal",
            )
            written += len(chunk)
        return written


def format_coordinate_list(districts: list[dict[str, Any]], key: str) -> str:
    return ",".join(f"{district[key]:.6f}" for district in districts)


def fetch_batch_payloads(
    districts: list[dict[str, Any]],
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_count = len(districts)
    latitudes = format_coordinate_list(districts, "latitude")
    longitudes = format_coordinate_list(districts, "longitude")

    air_quality = request_json(
        AIR_QUALITY_URL,
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "hourly": ",".join(AIR_QUALITY_FIELDS),
            "timezone": timezone_name,
            "forecast_days": 1,
            "past_days": 1,
        },
    )
    weather = request_json(
        WEATHER_URL,
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "hourly": ",".join(WEATHER_HOURLY_FIELDS),
            "timezone": timezone_name,
            "forecast_days": 1,
            "past_days": 1,
        },
    )

    return (
        normalize_batch_response(air_quality, expected_count, "air quality"),
        normalize_batch_response(weather, expected_count, "weather"),
    )


# --------------------------------------------------------------------------- #
# Google Air Quality API (history:lookup only)
# --------------------------------------------------------------------------- #


def google_history_request(api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST history:lookup with retries. Counts every attempt as a billed call."""
    global GOOGLE_API_CALLS

    max_attempts = len(RETRY_BACKOFF_SECONDS) + 1
    headers = {
        "Content-Type": "application/json",
        # Header form keeps the key out of request URLs and error strings.
        "X-Goog-Api-Key": api_key,
    }

    for attempt in range(1, max_attempts + 1):
        try:
            GOOGLE_API_CALLS += 1
            response = requests.post(
                GOOGLE_AIR_QUALITY_HISTORY_URL,
                headers=headers,
                json=body,
                timeout=GOOGLE_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"Google history response had unexpected type: {type(payload).__name__}"
                )
            return payload
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt == max_attempts:
                raise RuntimeError(f"Google history request failed: {exc.__class__.__name__}") from None
            sleep_before_retry(attempt, exc, "Google Air Quality")
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            detail = ""
            if exc.response is not None:
                detail = scrub(exc.response.text or "")[:300]
            if status_code not in RETRY_STATUS_CODES or attempt == max_attempts:
                raise RuntimeError(
                    f"Google history request failed with HTTP {status_code}: {detail}"
                ) from None
            sleep_before_retry(attempt, exc, "Google Air Quality")

    raise RuntimeError("Google history request failed after retries")


def google_concentration_to_ug_per_m3(code: str, concentration: dict[str, Any]) -> float | None:
    value = concentration.get("value")
    if value is None:
        return None

    units = str(concentration.get("units") or "").upper()
    if units == "PARTS_PER_BILLION":
        factor = PPB_TO_UG_PER_M3.get(code)
        if factor is None:
            # Unknown pollutant in ppb: no defensible conversion, drop it.
            return None
        return round(float(value) * factor, 3)
    if units in {"MICROGRAMS_PER_CUBIC_METER", ""}:
        return round(float(value), 3)
    return None


def parse_google_hour(district_name: str, hour_info: dict[str, Any]) -> dict[str, Any] | None:
    raw_time = hour_info.get("dateTime")
    if not raw_time:
        return None
    try:
        observed_at = parse_rfc3339(str(raw_time))
    except ValueError:
        return None

    us_aqi: int | None = None
    for index in hour_info.get("indexes") or []:
        if not isinstance(index, dict):
            continue
        if index.get("code") == GOOGLE_LOCAL_AQI_CODE:
            raw_aqi = index.get("aqi")
            us_aqi = int(raw_aqi) if isinstance(raw_aqi, (int, float)) else None
            break

    row: dict[str, Any] = {
        "district": district_name,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "source": SOURCE_GOOGLE,
        "aqi": us_aqi,
        "pm25": None,
        "pm10": None,
        "no2": None,
        "o3": None,
    }

    for pollutant in hour_info.get("pollutants") or []:
        if not isinstance(pollutant, dict):
            continue
        code = str(pollutant.get("code") or "").lower()
        column = GOOGLE_POLLUTANT_CODES.get(code)
        if column is None:
            continue
        concentration = pollutant.get("concentration")
        if not isinstance(concentration, dict):
            continue
        row[column] = google_concentration_to_ug_per_m3(code, concentration)

    if us_aqi is None and row["pm25"] is not None:
        row["aqi"] = calculate_us_aqi_from_pm25(row["pm25"])

    if all(row[field] is None for field in ("aqi", "pm25", "pm10", "no2", "o3")):
        return None

    return row


def fetch_google_history(district: dict[str, Any], api_key: str) -> list[dict[str, Any]]:
    """Return up to GOOGLE_HISTORY_HOURS hourly rows for one district.

    Exactly one request per district: nextPageToken is deliberately ignored so a
    run can never cost more calls than planned.
    """
    body = {
        "location": {
            "latitude": district["latitude"],
            "longitude": district["longitude"],
        },
        "hours": GOOGLE_HISTORY_HOURS,
        "pageSize": GOOGLE_PAGE_SIZE,
        "universalAqi": False,
        "extraComputations": ["LOCAL_AQI", "POLLUTANT_CONCENTRATION"],
        "customLocalAqis": [
            {"regionCode": GOOGLE_REGION_CODE, "aqi": GOOGLE_LOCAL_AQI_CODE}
        ],
        "languageCode": "en",
    }

    payload = google_history_request(api_key, body)
    hours_info = payload.get("hoursInfo")
    if not isinstance(hours_info, list) or not hours_info:
        raise RuntimeError("Google history response did not include hoursInfo")

    rows = []
    for hour_info in hours_info:
        if not isinstance(hour_info, dict):
            continue
        row = parse_google_hour(district["district"], hour_info)
        if row is not None:
            rows.append(row)

    if not rows:
        raise RuntimeError("Google history response did not include usable hourly values")

    return rows


# --------------------------------------------------------------------------- #
# Row builders
# --------------------------------------------------------------------------- #


def build_cams_hourly_rows(
    district: dict[str, Any],
    payload: dict[str, Any],
    timezone_name: str,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = []
    for observed_at, values in iter_past_hourly_rows(
        payload, AIR_QUALITY_FIELDS, timezone_name, now
    ):
        us_aqi = values.get("us_aqi")
        if us_aqi is None:
            us_aqi = calculate_us_aqi_from_pm25(values.get("pm2_5"))
        rows.append(
            {
                "district": district["district"],
                "observed_at": observed_at.isoformat(),
                "source": SOURCE_CAMS,
                "aqi": int(us_aqi) if us_aqi is not None else None,
                "pm25": values.get("pm2_5"),
                "pm10": values.get("pm10"),
                "no2": values.get("nitrogen_dioxide"),
                "o3": values.get("ozone"),
            }
        )
    return rows


def build_weather_hourly_rows(
    district: dict[str, Any],
    payload: dict[str, Any],
    timezone_name: str,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = []
    for observed_at, values in iter_past_hourly_rows(
        payload, WEATHER_HISTORY_FIELDS, timezone_name, now
    ):
        weather_code = values.get("weather_code")
        rows.append(
            {
                "district": district["district"],
                "observed_at": observed_at.isoformat(),
                "temperature": values.get("temperature_2m"),
                "apparent_temperature": values.get("apparent_temperature"),
                "humidity": values.get("relative_humidity_2m"),
                "precipitation": values.get("precipitation"),
                "rain": values.get("rain"),
                "precipitation_probability": values.get("precipitation_probability"),
                "wind_speed": values.get("wind_speed_10m"),
                "wind_gust": values.get("wind_gusts_10m"),
                "weather_code": int(weather_code) if weather_code is not None else None,
            }
        )
    return rows


def newest_air_quality_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Newest stored hour for one district, preferring the Google source."""
    if not rows:
        return None

    def sort_key(row: dict[str, Any]) -> tuple[datetime, int]:
        return (
            parse_rfc3339(row["observed_at"]),
            1 if row["source"] == SOURCE_GOOGLE else 0,
        )

    return max(rows, key=sort_key)


def build_latest_row(
    district: dict[str, Any],
    air_quality_row: dict[str, Any] | None,
    cams_payload: dict[str, Any],
    weather_payload: dict[str, Any],
    timezone_name: str,
    now: datetime,
) -> dict[str, Any]:
    weather_row = current_hourly_row(weather_payload, WEATHER_HOURLY_FIELDS, timezone_name, now)

    # so2, co and uv_index are not part of the hourly history tables; they come
    # from the Open-Meteo CAMS payload, which is fetched on every run.
    try:
        cams_row = current_hourly_row(cams_payload, AIR_QUALITY_FIELDS, timezone_name, now)
    except RuntimeError:
        cams_row = {}

    if air_quality_row is not None:
        aqi = air_quality_row.get("aqi")
        pm25 = air_quality_row.get("pm25")
        pm10 = air_quality_row.get("pm10")
        no2 = air_quality_row.get("no2")
        o3 = air_quality_row.get("o3")
        measured_at = air_quality_row["observed_at"]
        source = air_quality_row["source"]
    else:
        aqi = cams_row.get("us_aqi") or calculate_us_aqi_from_pm25(cams_row.get("pm2_5"))
        pm25 = cams_row.get("pm2_5")
        pm10 = cams_row.get("pm10")
        no2 = cams_row.get("nitrogen_dioxide")
        o3 = cams_row.get("ozone")
        measured_at = (
            local_open_meteo_time_to_timestamptz(cams_row["time"], timezone_name)
            if cams_row.get("time")
            else None
        )
        source = SOURCE_CAMS

    status, risk_level, recommendation = aqi_status(aqi)

    return {
        "district": district["district"],
        "city": "Ho Chi Minh City",
        "latitude": district["latitude"],
        "longitude": district["longitude"],
        "aqi": aqi,
        "pm25": pm25,
        "pm10": pm10,
        "no2": no2,
        "o3": o3,
        "so2": cams_row.get("sulphur_dioxide"),
        "co": cams_row.get("carbon_monoxide"),
        "uv_index": cams_row.get("uv_index"),
        "temperature": weather_row.get("temperature_2m"),
        "humidity": weather_row.get("relative_humidity_2m"),
        "precipitation_probability": weather_row.get("precipitation_probability"),
        "wind_speed": weather_row.get("wind_speed_10m"),
        "wind_gust": weather_row.get("wind_gusts_10m"),
        "pressure": weather_row.get("pressure_msl"),
        "cloud_cover": weather_row.get("cloud_cover"),
        "weather_condition": weather_condition(weather_row.get("weather_code")),
        "status": status,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "air_quality_source": source,
        "measured_at": measured_at,
        "updated_at": utc_now_iso(),
    }


def collect_open_meteo_payloads(
    timezone_name: str,
    failures: list[dict[str, str]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Fetch CAMS air quality and weather payloads for every district."""
    payloads: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for batch_start in range(0, len(HCM_DISTRICTS), BATCH_SIZE):
        district_batch = HCM_DISTRICTS[batch_start : batch_start + BATCH_SIZE]
        batch_names = ", ".join(district["district"] for district in district_batch)
        try:
            air_quality_payloads, weather_payloads = fetch_batch_payloads(
                district_batch, timezone_name
            )
            for district, air_quality, weather in zip(
                district_batch, air_quality_payloads, weather_payloads, strict=True
            ):
                payloads[district["district"]] = (air_quality, weather)
        except Exception as batch_exc:  # noqa: BLE001 - batch fallback preserves data availability.
            print(
                f"Batch request failed for [{batch_names}]; falling back to per-district requests "
                f"({scrub(str(batch_exc))}).",
                file=sys.stderr,
            )
            for district in district_batch:
                try:
                    air_quality_payloads, weather_payloads = fetch_batch_payloads(
                        [district], timezone_name
                    )
                    payloads[district["district"]] = (
                        air_quality_payloads[0],
                        weather_payloads[0],
                    )
                except Exception as exc:  # noqa: BLE001 - record per-district failures.
                    failures.append(
                        {
                            "district": district["district"],
                            "stage": "open_meteo",
                            "error": scrub(str(exc)),
                        }
                    )
        time.sleep(BATCH_DELAY_SECONDS)

    return payloads


def fetch_recent_stored_air_quality(
    supabase: SupabaseRestClient,
    lookback_hours: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    """Read back the most recent stored hours so the latest table reflects them.

    On hours when Google is not scheduled, nothing new is written to
    air_quality_hourly. Without this read-back the latest row would fall back to
    the coarse CAMS payload and overwrite the Google values, flipping the
    dashboard source every other hour.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    rows = supabase.request(
        "GET",
        "air_quality_hourly",
        params={
            "select": "district,observed_at,source,aqi,pm25,pm10,no2,o3",
            "observed_at": f"gte.{since}",
            "order": "observed_at.desc",
        },
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("district"):
            grouped.setdefault(row["district"], []).append(row)
    return grouped


def google_schedule_state(now: datetime, api_key: str | None) -> tuple[bool, bool, str]:
    """Return (configured, scheduled_now, mode)."""
    mode = (os.getenv("GOOGLE_AIR_QUALITY_MODE") or "auto").strip().lower()
    if mode not in {"auto", "always", "never"}:
        mode = "auto"

    configured = bool(api_key) and mode != "never"
    if not configured:
        return False, False, mode
    if mode == "always":
        return True, True, mode
    return True, now.hour % GOOGLE_RUN_EVERY_HOURS == 0, mode


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError("Python 3.11 or newer is required")

    started_monotonic = time.monotonic()
    load_dotenv()

    supabase_url = getenv_required("SUPABASE_URL")
    supabase_key = getenv_required("SUPABASE_SERVICE_ROLE_KEY")
    google_api_key = os.getenv("GOOGLE_MAPS_API_KEY") or None
    register_secret(supabase_key)
    register_secret(google_api_key)

    supabase = SupabaseRestClient(supabase_url, supabase_key)
    timezone_name = os.getenv("CITY_TIMEZONE", DEFAULT_CITY_TIMEZONE)
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

    failures: list[dict[str, str]] = []
    weather_rows: list[dict[str, Any]] = []
    air_quality_rows: list[dict[str, Any]] = []
    latest_rows: list[dict[str, Any]] = []
    google_status = "disabled"
    google_error: str | None = None

    try:
        now = datetime.now(ZoneInfo(timezone_name))
        google_configured, google_scheduled, google_mode = google_schedule_state(
            now, google_api_key
        )

        payloads = collect_open_meteo_payloads(timezone_name, failures)
        open_meteo_status = "success" if payloads and not failures else (
            "partial_success" if payloads else "failed"
        )

        # ------------------------------------------------------------------ #
        # Air quality: Google history first, Open-Meteo CAMS as the fallback.
        # ------------------------------------------------------------------ #
        google_rows_by_district: dict[str, list[dict[str, Any]]] = {}

        if google_scheduled and google_api_key:
            google_failures = 0
            for district in HCM_DISTRICTS:
                try:
                    rows = fetch_google_history(district, google_api_key)
                    google_rows_by_district[district["district"]] = rows
                except Exception as exc:  # noqa: BLE001 - per-district fallback to CAMS.
                    google_failures += 1
                    failures.append(
                        {
                            "district": district["district"],
                            "stage": "google_air_quality",
                            "error": scrub(str(exc)),
                        }
                    )
                time.sleep(GOOGLE_CALL_DELAY_SECONDS)

            if google_rows_by_district and google_failures == 0:
                google_status = "success"
            elif google_rows_by_district:
                google_status = "partial_success"
            else:
                google_status = "failed"
                google_error = "Google history returned no usable rows for any district"
        elif google_configured:
            google_status = "skipped"
        else:
            google_status = "disabled"

        for district in HCM_DISTRICTS:
            name = district["district"]
            payload_pair = payloads.get(name)
            district_air_rows = list(google_rows_by_district.get(name, []))

            if payload_pair is None:
                air_quality_rows.extend(district_air_rows)
                continue

            cams_payload, weather_payload = payload_pair

            try:
                weather_rows.extend(
                    build_weather_hourly_rows(district, weather_payload, timezone_name, now)
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {"district": name, "stage": "weather_hourly", "error": scrub(str(exc))}
                )

            # CAMS air quality is stored only as a fallback: when Google is not
            # configured at all, or when its call for this district failed.
            needs_cams_fallback = not district_air_rows and (
                not google_configured or google_status in {"failed", "partial_success"}
            )
            if needs_cams_fallback:
                try:
                    district_air_rows = build_cams_hourly_rows(
                        district, cams_payload, timezone_name, now
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {"district": name, "stage": "cams_hourly", "error": scrub(str(exc))}
                    )

            air_quality_rows.extend(district_air_rows)

        if not weather_rows and not air_quality_rows and not payloads:
            raise RuntimeError("No district rows were fetched successfully")

        if weather_rows:
            supabase.upsert("weather_hourly", weather_rows, "district,observed_at")
        if air_quality_rows:
            supabase.upsert(
                "air_quality_hourly", air_quality_rows, "district,observed_at,source"
            )

        # district_air_weather_latest is written from the newest stored hour.
        try:
            stored_air_quality = fetch_recent_stored_air_quality(supabase)
        except Exception as exc:  # noqa: BLE001 - fall back to this run's rows.
            print(
                f"Could not read back stored hourly rows ({scrub(str(exc))}); "
                "using this run's rows instead.",
                file=sys.stderr,
            )
            stored_air_quality = {}
            for row in air_quality_rows:
                stored_air_quality.setdefault(row["district"], []).append(row)

        for district in HCM_DISTRICTS:
            name = district["district"]
            payload_pair = payloads.get(name)
            if payload_pair is None:
                continue
            cams_payload, weather_payload = payload_pair
            try:
                latest_rows.append(
                    build_latest_row(
                        district,
                        newest_air_quality_row(stored_air_quality.get(name, [])),
                        cams_payload,
                        weather_payload,
                        timezone_name,
                        now,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {"district": name, "stage": "latest", "error": scrub(str(exc))}
                )

        if not latest_rows:
            raise RuntimeError("No district rows were fetched successfully")

        supabase.upsert("district_air_weather_latest", latest_rows, "district")

        # Reported from what the dashboard will actually display, which on an
        # unscheduled hour is the Google data stored by the previous run.
        displayed_sources = {row["air_quality_source"] for row in latest_rows}
        if displayed_sources == {SOURCE_GOOGLE}:
            air_quality_source = SOURCE_GOOGLE
        elif displayed_sources == {SOURCE_CAMS}:
            air_quality_source = SOURCE_CAMS
        elif displayed_sources:
            air_quality_source = "mixed"
        else:
            air_quality_source = None
        status = "success" if not failures else "partial_success"

        supabase.request(
            "PATCH",
            "air_quality_pipeline_runs",
            body={
                "status": status,
                "rows_processed": len(latest_rows),
                "rows_failed": len(failures),
                "error_message": json.dumps(failures, ensure_ascii=False) if failures else None,
                "air_quality_source": air_quality_source,
                "google_status": google_status,
                "google_api_calls": GOOGLE_API_CALLS,
                "open_meteo_status": open_meteo_status,
                "open_meteo_api_calls": API_REQUESTS_ATTEMPTED,
                "air_quality_rows": len(air_quality_rows),
                "weather_rows": len(weather_rows),
                "ended_at": utc_now_iso(),
            },
            params={"run_id": f"eq.{run_id}"},
            prefer="return=minimal",
        )

        print(
            json.dumps(
                {
                    "status": status,
                    "rows_processed": len(latest_rows),
                    "rows_failed": len(failures),
                    "failures": failures,
                    "air_quality_source": air_quality_source,
                    "google_mode": google_mode,
                    "google_status": google_status,
                    "google_error": google_error,
                    "google_api_calls": GOOGLE_API_CALLS,
                    "open_meteo_status": open_meteo_status,
                    "open_meteo_api_calls": API_REQUESTS_ATTEMPTED,
                    "air_quality_rows": len(air_quality_rows),
                    "weather_rows": len(weather_rows),
                    "batch_size": BATCH_SIZE,
                    "duration_seconds": round(time.monotonic() - started_monotonic, 2),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        if failures:
            failed_districts = ", ".join(
                f"{failure['district']}/{failure.get('stage', '?')}" for failure in failures
            )
            print(f"Partial success. Failed stages: {failed_districts}", file=sys.stderr)
        return 0 if latest_rows else 1
    except Exception as exc:
        message = scrub(str(exc))
        failure_details = failures or [{"district": "global", "stage": "pipeline", "error": message}]
        try:
            supabase.request(
                "PATCH",
                "air_quality_pipeline_runs",
                body={
                    "status": "failed",
                    "rows_processed": len(latest_rows),
                    "rows_failed": len(failure_details),
                    "error_message": message,
                    "google_status": google_status,
                    "google_api_calls": GOOGLE_API_CALLS,
                    "open_meteo_api_calls": API_REQUESTS_ATTEMPTED,
                    "air_quality_rows": len(air_quality_rows),
                    "weather_rows": len(weather_rows),
                    "ended_at": utc_now_iso(),
                },
                params={"run_id": f"eq.{run_id}"},
                prefer="return=minimal",
            )
        finally:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "rows_processed": len(latest_rows),
                        "rows_failed": len(failure_details),
                        "failures": failure_details,
                        "google_status": google_status,
                        "google_api_calls": GOOGLE_API_CALLS,
                        "open_meteo_api_calls": API_REQUESTS_ATTEMPTED,
                        "duration_seconds": round(time.monotonic() - started_monotonic, 2),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print(f"Pipeline failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
