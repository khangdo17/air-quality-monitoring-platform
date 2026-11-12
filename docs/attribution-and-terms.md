# Attribution and Terms

This page records what the Google Maps Platform terms actually say about
storing and displaying Air Quality API data, and what the dashboard must
display. Quotes are verbatim from the sources named. This is a developer's
reading of public documentation, not legal advice.

## Sources

- Google Maps Platform Service Specific Terms,
  <https://cloud.google.com/maps-platform/terms/maps-service-terms>,
  last modified **October 28, 2026**.
- Policies and attributions for Air Quality API,
  <https://developers.google.com/maps/documentation/air-quality/policies>.

## Caching and storage

Service Specific Terms, **Section 2.2 (Caching)**:

> Customer may temporarily cache the applicable Google Maps Content from the
> Air Quality API for the applicable Caching Period pursuant to Table 2.2.1
> (Air Quality API Caching Permissions).

**Table 2.2.1 (Air Quality API Caching Permissions)**, verbatim:

| Google Maps Content | Caching Period |
| --- | --- |
| Current conditions values<br>Hourly forecast values | One hour, after which Customer must delete the cached Google Maps Content |
| Historic values for a specific location and given time range | Until the Agreement is terminated |

This is the entire basis for the pipeline's design:

- `currentConditions:lookup` and `forecast:lookup` are **never called**. Their
  values could only be held for an hour, which is useless for a 24-hour chart
  and would require a deletion job to stay compliant.
- `history:lookup` returns "historic values for a specific location and given
  time range", which may be stored **until the Agreement is terminated**. Every
  `source = 'google_aq'` row in `air_quality_hourly` comes from that endpoint.

The 30-day retention in
`supabase/migrations/20261111120100_hourly_history_retention.sql` is therefore
a storage choice, not a licensing obligation.

**What to do if you stop using the Air Quality API.** "Until the Agreement is
terminated" is the limit. If the Google Maps Platform agreement ends, delete
the Google-sourced rows:

```sql
delete from air_quality_hourly where source = 'google_aq';
update district_air_weather_latest
   set air_quality_source = null
 where air_quality_source = 'google_aq';
```

## Attribution the dashboard must show

From the Air Quality API policies page:

> If you use data or display imagery from the Air Quality API, you must include
> the following attribution on or next to the data or imagery used, or with
> attribution to other third parties.

The required string, verbatim:

```text
Source: Includes air quality data from Google
```

Where a value is an aggregate of Google content with other sources, or an
interpretation of it, the policies page directs you to use:

```text
Includes data from Google Maps
```

Placement rules from the same page:

> Position attribution near the top or bottom of the content, and within the
> same visual container.

> Verify that the attribution is always visible and legible. Never remove,
> hide, obscure, or modify it.

### What this means for `/air-quality`

The dashboard shows two things that are not raw Google values: a `status` /
`risk_level` bucket and a `recommendation` sentence, both computed by this
repo's own thresholds. That is an interpretation layered on Google's AQI, which
is why the second string exists. The safe approach is to show both, for example
in the footer of the map and of the district detail card:

```text
Source: Includes air quality data from Google · Includes data from Google Maps
```

If you would rather show one line, show `Source: Includes air quality data from
Google` next to the AQI value itself and keep the computed recommendation
visually separate from it, so the recommendation does not read as something
Google said.

### Attribution must follow the source

`district_air_weather_latest.air_quality_source` exists for this. It is
`google_aq` or `open_meteo_cams`, and the dashboard should switch its
attribution line on that value rather than hard-coding Google. Showing the
Google attribution over CAMS values would be inaccurate; showing no Google
attribution over Google values would breach the policy.

When the source is `open_meteo_cams`, attribute Open-Meteo and CAMS instead:

```text
Air quality data by Open-Meteo (CC BY 4.0), based on CAMS global
```

Weather always comes from Open-Meteo, so the weather panel needs the Open-Meteo
attribution regardless of which air quality source is live.

## Permitted use: read this before shipping

Service Specific Terms, **Section 2.1 (Permitted Use)**, verbatim:

> Customer may only use the data retrieved from Air Quality API in (a) air
> quality based routing solutions developed by Customer, and (b) Customer
> environmental risk indices and correlational research.

This clause is narrower than "display air quality on a map". A district-level
dashboard that buckets AQI into risk levels and shows a health recommendation
is plausibly "(b) Customer environmental risk indices", and that is the reading
this project proceeds on. It is a judgement call, not a certainty, and it is
worth a look before the dashboard is promoted as a portfolio piece.

Note also that Section 2 contains **no** "Use without a Google Map" clause.
Several other services in the same document (Directions API, Geocoding API,
Geolocation API) carry an explicit "Customer may use Google Maps Content from
the ... in Customer Applications without a corresponding Google Map." The Air
Quality section does not. Whether that absence means anything for a dashboard
rendered on a non-Google map is not something these pages settle.

## Open-Meteo

Open-Meteo data is published under CC BY 4.0 and requires attribution, which
the line above provides. The underlying CAMS global model is a Copernicus
Atmosphere Monitoring Service product; crediting CAMS alongside Open-Meteo is
the conventional practice.

## Cost

See [google-cloud-setup.md](google-cloud-setup.md) for the free tier, the
planned call volume, the daily quota cap and the budget alert.
