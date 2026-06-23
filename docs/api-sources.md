# API Sources

## Open-Meteo Air Quality API

Endpoint:

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

The script requests one past day and one forecast day, then selects the latest
hourly row with usable values.

## Open-Meteo Forecast API

Endpoint:

```text
https://api.open-meteo.com/v1/forecast
```

Requested current fields:

```text
temperature_2m
relative_humidity_2m
weather_code
cloud_cover
pressure_msl
wind_speed_10m
wind_gusts_10m
```

Requested hourly field:

```text
precipitation_probability
```

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
Open-Meteo responses.

## Operational Notes

- Open-Meteo does not require an API key.
- Air quality and weather values can have different source update times.
- Open-Meteo values are estimates from forecast/model grids.
- District values should be described as coordinate-based estimates, not
  readings from physical sensors in every district.
