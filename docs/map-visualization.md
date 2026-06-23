# Map Visualization

The production dashboard at https://www.khangdo.dev/air-quality includes an
interactive Ho Chi Minh City air quality map.

## Modes

### Marker Mode

Marker mode displays one marker for each configured district coordinate. Each
marker shows the AQI value and uses the standard AQI color bucket:

| AQI | Status | Color intent |
| --- | --- | --- |
| 0-50 | Good | Green |
| 51-100 | Moderate | Yellow |
| 101-150 | Sensitive | Orange |
| 151-200 | Unhealthy | Red |
| 201+ | Very Unhealthy | Purple |

Clicking a marker updates the selected district detail card.

### District Map Mode

The private portfolio frontend is prepared to render GeoJSON district
boundaries from:

```text
src/data/hcm-districts.geojson
```

That file is intentionally not included in this public pipeline repo. If the
GeoJSON is missing or district names cannot be matched, the dashboard
automatically falls back to marker mode.

## Detail Card

The selected district detail card shows:

- District name
- Description
- AQI status
- PM2.5 and PM10
- Temperature
- Humidity
- Wind speed
- Updated timestamp
- Health recommendation

## Data Caveat

District-level values are estimated using coordinate-based forecast grid data,
not physical sensors in every district. This caveat is visible in the dashboard
so users understand the data source and precision.
