# Attribution and Terms

This page records what the Google Maps Platform terms actually say about
storing and displaying Air Quality API data, and what the dashboard must
display. Quotes are verbatim from the sources named. This is a developer's
reading of public documentation, not legal advice.

## Status: the Google Air Quality API is switched OFF

As of **November 12, 2026** the pipeline does not call Google. `GOOGLE_AQ_ENABLED`
defaults to `false`; with it unset the script never calls the Air Quality API
even when `GOOGLE_MAPS_API_KEY` is present, and records
`air_quality_pipeline_runs.google_status = 'disabled'`. Air quality comes from
Open-Meteo CAMS.

The reason is the non-Google map restriction below. Turning the switch on is an
explicit decision to accept a particular reading of that clause; it is not a
default the code will drift into.

## Sources

- Google Maps Platform Terms of Service,
  <https://cloud.google.com/maps-platform/terms>,
  last modified **August 26, 2026**.
- Google Maps Platform Service Specific Terms,
  <https://cloud.google.com/maps-platform/terms/maps-service-terms>,
  last modified **October 28, 2026**.
- Google Maps Platform Services list (the definition of "Google Maps Core
  Services"), <https://cloud.google.com/maps-platform/terms/maps-services/>,
  last modified **October 28, 2026**.
- Policies and attributions for Air Quality API,
  <https://developers.google.com/maps/documentation/air-quality/policies>,
  page last updated **2026-11-09 UTC**, read **2026-11-12**.

## The non-Google map restriction

This is the blocker. Terms of Service, **Section 3.2.3(e)**, verbatim:

> **(e) No Use With Non-Google Maps.** To avoid quality issues and/or brand
> confusion, Customer will not use the Google Maps Core Services with or near a
> non-Google Map in a Customer Application. For example, Customer will not (i)
> display or use Places content on a non-Google Map, (ii) display Street View
> imagery and non-Google Maps on the same screen, or (iii) link a Google Map to
> non-Google Maps Content or a non-Google Map.

The Air Quality API is in scope. ToS definitions:

> "Services" and "Google Maps Core Services" means the services described at
> https://cloud.google.com/maps-platform/terms/maps-services/.

and that list names **Air Quality API** on its face.

The Air Quality policies page says the same thing in its summary callout:

> Air Quality API results displayed on a map must be shown on a Google Map, and
> Google attribution is required when displaying this data without a Google Map.

**What this means here.** `/air-quality` renders the 18 districts on a custom
Three.js map (see [map-visualization.md](map-visualization.md)). Putting
Google-sourced AQI values on that map is the exact shape of 3.2.3(e)(i). The
clause reaches "with or near", so moving the numbers into a side panel on the
same screen as the Three.js map does not obviously escape it either.

Note also that Service Specific Terms Section 2 contains **no** "Use without a
Google Map" clause for the Air Quality API. Several other services in the same
document (Directions API, Geocoding API, Geolocation API) carry an explicit
"Customer may use Google Maps Content from the ... in Customer Applications
without a corresponding Google Map." Its absence from the Air Quality section
is conspicuous.

### The one inconsistency worth knowing about

The policies page is not self-consistent on this. The summary callout says
results on a map "must be shown on a Google Map", but the same page's
attribution section plainly contemplates the no-Google-Map case:

> You don't need to add extra attribution if the Content is shown on a Google
> Map where the attribution is already visible.

That sentence only makes sense if displaying Content *without* a Google Map is
permitted, attribution being the price. So the page reads as "non-map display
without a Google Map is fine; **map** display is not". That is consistent with
3.2.3(e), which is about maps rather than about data display in general, and it
is the reading this document proceeds on: a chart, a table or a district card
is not a map; the Three.js district map is.

### Options, if you want Google back

1. **Leave it off.** CAMS is coarse (~25–45 km) but unrestricted. This is the
   current state.
2. **Swap the basemap for a Google Map** on `/air-quality` (Maps JavaScript
   API). Removes the conflict, costs the custom visual and adds Maps SDK
   billing.
3. **Keep Google off the map.** Google values feed only the 24-hour chart and
   the district detail panel, the Three.js map shows CAMS. Possible, but the
   two sources would disagree on screen, and "near a non-Google Map" is doing
   unpredictable work in that sentence.
4. **Ask Google.** The policies page points at
   <https://cloud.google.com/contact> for custom licensing, and says plainly
   that support engineers cannot grant exceptions.

Options 2 and 3 are judgement calls on an unsettled clause. Option 1 needs no
judgement, which is why it is the default.

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

None of this is live today — Google is switched off, so the dashboard currently
needs only the Open-Meteo credit below. This section is what must be built
*before* `GOOGLE_AQ_ENABLED` is ever set to `true`.

### The two required strings

From the Air Quality API policies page, "Other attribution requirements":

> If you use data or display imagery from the Air Quality API, you must include
> the following attribution on or next to the data or imagery used, or with
> attribution to other third parties:
>
> "Source: Includes air quality data from Google"

So, for **unmodified** Google values (the AQI number, a pollutant
concentration), verbatim and exactly:

```text
Source: Includes air quality data from Google
```

From "Attribution when creating new content using data from Environment APIs":

> In some instances, you may use data from Google Maps Platform Environment
> APIs to create entirely new content. In these cases, spell out "Includes data
> from Google Maps" following the same visual guidelines as Text attribution.

> Right: A custom score that aggregates content from Google Maps and other
> sources or interprets Google Maps environmental API content is attributed
> with "Includes data from Google Maps" following text attribution guidelines.

So, for **derived** values — this repo's `status` / `risk_level` bucket and its
`recommendation` sentence, both computed by our own thresholds — verbatim and
exactly:

```text
Includes data from Google Maps
```

### The logo requirement

Text alone is not the default. From "Google Maps logo and text attribution":

> Attribution should take the form of the Google Maps logo whenever possible.
> In cases where space is limited, the text Google Maps is acceptable.
> It must always be clear to end users which content is provided by Google Maps.

The logo files come from the page's "Download the Google Maps attribution
assets" link. Requirements, verbatim:

> Don't modify the logo in any way.
> Maintain the aspect ratio of the logo to prevent distortion.
> Use the outlined logo on a busy background, like a map or image.
> Use the non-outlined logo on a plain background, like a solid color or subtle gradient.

> Minimum logo height: 16dp
> Maximum logo height: 19dp
> Minimum logo clear space: 10dp on left, right and top, 5dp on the bottom

> Maintain an accessible contrast between the logo and the background.
> Include an accessibility label with the text Google Maps.

If the logo does not fit, the spelled-out text has its own rules:

> Don't change the capitalization of Google Maps
> Don't wrap Google Maps onto multiple lines
> Don't localize Google Maps into another language.
> Prevent browsers from translating Google Maps by using the HTML attribute translate="no".

That last one matters here: `/air-quality` has a Vietnamese locale, and the
string must not be translated. The page's own CSS:

```css
@import url('https://fonts.googleapis.com/css2?family=Roboto&display=swap');
.GMP-attribution {
  font-family: Roboto, Sans-Serif;
  font-style: normal;
  font-weight: 400;
  font-size: 1rem;
  letter-spacing: normal;
  white-space: nowrap;
  color: #5e5e5e;
}
```

### Flag: the page contradicts itself on logo vs text

Three statements on the same page prescribe three different things for the
same case — displaying an unmodified Google AQI value:

1. "Other attribution requirements": you **must** include the sentence
   `Source: Includes air quality data from Google`.
2. "Attribution when creating new content...": "If displaying Air Quality,
   Pollen, Solar, or Weather API data **as is, without any modifications, use
   the Google Maps logo or text attribution**" — that is, the logo, or the two
   words `Google Maps`. Not the sentence in (1).
3. "Google Maps logo and text attribution": "Attribution should take the form
   of the Google Maps **logo whenever possible**."

And a fourth wrinkle on the wording itself. The page carries this note:

> The following updated attribution requirements now use "Google Maps" instead
> of only "Google". We acknowledge that your existing implementations may use
> the attribution of "Google," in alignment with prior guidance, and you may
> continue using "Google" as an attribution for now. For new implementations,
> use "Google Maps" as described in this section.

Yet the mandatory Air Quality string in (1) still reads "from **Google**", not
"from Google Maps" — the migration the note announces has not reached it.

**How to resolve it:** satisfy all of them at once rather than picking. Show
the Google Maps logo (or the text `Google Maps` where the logo will not fit)
**and** the `Source: Includes air quality data from Google` sentence, in the
same visual container as the value. Over-attributing costs a line of UI;
under-attributing is the breach. Keep the mandated sentence byte-exact as
published, including "Google" rather than "Google Maps", since it is quoted as
a required string.

### Placement rules

From "Visual requirements", verbatim:

> Position attribution near the top or bottom of the content, and within the
> same visual container. For a single line of content, attribution can be
> positioned to the right or left.

> Visually distinguish Google Maps Platform Content from other content by using
> UI cues such as a border, background color, shadow, or sufficient whitespace.

> Don't misrepresent Google Maps by attributing it with non-Google Maps
> Platform content.

> Verify that the attribution is always visible and legible. Never remove,
> hide, obscure, or modify it.

That third rule is the one that bites a mixed dashboard: the Open-Meteo weather
panel must not sit inside the Google-attributed container, or the attribution
would be claiming Google supplied the temperature.

### One more obligation

From the policies page summary:

> Applications using the Air Quality API must provide publicly accessible Terms
> of Use and a Privacy Policy that align with Google's requirements, including
> referencing Google's Terms of Service and Privacy Policy.

khangdo.dev would need both pages, referencing Google's, before the switch goes
on.

### What this means for `/air-quality`

The dashboard shows two things that are not raw Google values: a `status` /
`risk_level` bucket and a `recommendation` sentence, both computed by this
repo's own thresholds. That is an interpretation layered on Google's AQI, which
is why the second string exists. Show both, in the footer of whichever
container holds the values — but not the Three.js map, which must not carry
Google values at all while 3.2.3(e) stands:

```text
[Google Maps logo]  Source: Includes air quality data from Google · Includes data from Google Maps
```

Keep the computed `recommendation` sentence visually separate from the AQI
value, so it does not read as something Google said, and label the bucket as
this project's own index (see
[Permitted use](#permitted-use-read-this-before-shipping) below).

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

### How to label the risk buckets

2.1(b) is the clause this dashboard fits under, and `risk_level` is literally a
customer-built environmental risk index over Google's data. So the risk buckets
are not a liability — they are what makes the (b) reading available. Two
consequences for the labelling:

1. **Don't present the bucket as Google's classification.** Google's `usa_epa`
   index returns its own `category` string ("Moderate air quality" and so on),
   which this pipeline does not store. Ours is computed by `aqi_status()` from
   our own thresholds. Labelling ours as Google's would misattribute it *and*
   undercut the (b) reading, whose whole point is that the index is the
   customer's.
2. **Keep the health recommendation clearly ours.** It is advice, not data.
   Attributing it to Google would be wrong on the facts as well as on the
   policy.

The "Section 2 contains no 'Use without a Google Map' clause for Air Quality"
point is covered under
[The non-Google map restriction](#the-non-google-map-restriction) above, which
is the clause actually keeping the switch off.

## Open-Meteo

Open-Meteo data is published under CC BY 4.0 and requires attribution, which
the line above provides. The underlying CAMS global model is a Copernicus
Atmosphere Monitoring Service product; crediting CAMS alongside Open-Meteo is
the conventional practice.

## Cost

See [google-cloud-setup.md](google-cloud-setup.md) for the free tier, the
planned call volume, the daily quota cap and the budget alert.
