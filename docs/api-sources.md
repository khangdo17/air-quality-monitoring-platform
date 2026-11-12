# API Sources

## Summary

| Source | Used for | Resolution | Update frequency | Called |
| --- | --- | --- | --- | --- |
| Google Air Quality API (`history:lookup`) | Primary air quality | ~500 m | Hourly | Even hours, 18 calls/run |
| Open-Meteo Air Quality API (CAMS global) | Air quality fallback, plus SO2/CO/UV | ~25-45 km, 3-hourly steps | Twice daily | Every run, 1 batched call per 6 districts |
| Open-Meteo Forecast API | Weather | ~1-11 km | Hourly | Every run, 1 batched call per 6 districts |

The resolution difference is the reason for the migration. On a 25-45 km CAMS
grid, all 18 Ho Chi Minh City districts fall into roughly one or two cells, so
their air quality values are nearly identical and a district-level map is not
really showing district-level variation. At ~500 m, Google's values differ
across districts in a way the map can honestly display.

## Google Air Quality API

```text
POST https://airquality.googleapis.com/v1/history:lookup
```

The key is sent in the `X-Goog-Api-Key` header, not as a `?key=` query
parameter, so it never appears in a request URL or in error text.

**Only the history endpoint is called.** `currentConditions:lookup` and
`forecast:lookup` are never used, because their values may not be stored. See
[attribution-and-terms.md](attribution-and-terms.md).

Request body per district:

```json
{
  "location": { "latitude": 10.7757, "longitude": 106.7004 },
  "hours": 4,
  "pageSize": 4,
  "universalAqi": false,
  "extraComputations": ["LOCAL_AQI", "POLLUTANT_CONCENTRATION"],
  "customLocalAqis": [{ "regionCode": "VN", "aqi": "usa_epa" }],
  "languageCode": "en"
}
```

- `hours: 4` with a run every 2 hours covers all 24 hours twice over. The
  window is double the cadence on purpose: if one scheduled run never fires,
  the runs either side still cover every hour it would have stored. A 2-hour
  window would lose 2 hours and a 3-hour window would lose 1.
- `customLocalAqis` requests the US EPA index (`usa_epa`) for a Vietnamese
  location, which keeps the dashboard's AQI scale unchanged from the previous
  Open-Meteo `us_aqi` field. `universalAqi` is off because the dashboard does
  not display Google's universal index.
- `pageSize: 4` keeps the response to a single page: the default page size is
  72 and the maximum is 168, so a 4-hour window is never split. History is
  billed per page and the script never follows `nextPageToken`, so one
  district-run is exactly one billable call whatever the window size.

Values read from each `hoursInfo[]` entry:

| Response path | Stored as |
| --- | --- |
| `dateTime` | `air_quality_hourly.observed_at` |
| `indexes[code = "usa_epa"].aqi` | `aqi` |
| `pollutants[code = "pm25"].concentration` | `pm25` |
| `pollutants[code = "pm10"].concentration` | `pm10` |
| `pollutants[code = "no2"].concentration` | `no2` |
| `pollutants[code = "o3"].concentration` | `o3` |

Two documentation details worth knowing:

- The reference "Reported pollutants" table spells fine particulate matter
  `p25`, while the local-AQI pages use `pm25`. The parser accepts both.
- Google returns **NO2 and O3 in ppb**, and PM2.5/PM10 in µg/m³. Open-Meteo
  CAMS returns everything in µg/m³. The script converts ppb to µg/m³ using the
  unit named in `concentration.units`, so a column means the same thing for
  both sources. See [data-model.md](data-model.md) for the conversion.

## Open-Meteo Air Quality API (CAMS global)

```text
https://air-quality-api.open-meteo.com/v1/air-quality
```

Requested hourly fields:

```text
pm10
pm2_5
carbon_monoxide
nitrogen_dioxide
sulphur_dioxide
ozone
us_aqi
uv_index
```

Called on every run, with `past_days=1` and `forecast_days=1`, for two reasons:

1. It is the fallback when Google is unavailable, fails, or has no key
   configured. Those rows are written with `source = 'open_meteo_cams'`.
2. It supplies `so2`, `co` and `uv_index` for
   `district_air_weather_latest`. Those three are not part of the hourly
   history tables and are not requested from Google.

CAMS global is a ~25-45 km model grid published on 3-hourly steps and updated
roughly twice a day. Requesting it more often than hourly returns the same
numbers.

## Open-Meteo Forecast API

```text
https://api.open-meteo.com/v1/forecast
```

Requested hourly fields:

```text
temperature_2m
apparent_temperature
relative_humidity_2m
precipitation
rain
precipitation_probability
weather_code
cloud_cover
pressure_msl
wind_speed_10m
wind_gusts_10m
```

Called every hour with `past_days=1`. Every returned hour **at or before the
current hour** is written to `weather_hourly`; forecast hours are skipped so
the table holds only observed/analysed values and the 24-hour chart never
silently mixes in a forecast.

`cloud_cover` and `pressure_msl` are fetched for
`district_air_weather_latest` only and are not stored hourly.

## District Coordinates

The ingestion script includes 18 configured Ho Chi Minh City district
coordinates:

- Bình Tân
- Quận 8
- Quận 6
- Tân Bình
- Quận 11
- Tân Phú
- Gò Vấp
- Quận 5
- Quận 12
- Quận 4
- Quận 10
- Bình Chánh
- Quận 1
- Bình Thạnh
- Hóc Môn
- Thủ Đức
- Quận 7
- Phú Nhuận

Timezone:

```text
Asia/Bangkok
```

`Asia/Bangkok` is UTC+7 and works for Ho Chi Minh City timestamps in
Open-Meteo responses. Google returns RFC 3339 UTC timestamps, which are stored
as-is; both land in the same `timestamptz` column and compare correctly.

## Operational Notes

- Open-Meteo requires no API key. Google requires a key and enabled billing.
- Air quality and weather values can have different source update times.
- Open-Meteo values are estimates from forecast/model grids.
- Google's values are also modelled, blended from multiple inputs; ~500 m
  resolution is not the same as a physical monitor in every district.
- District values should be described as coordinate-based estimates, not
  readings from physical sensors in every district.
