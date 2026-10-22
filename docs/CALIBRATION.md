# Calibration

How the beach levels were checked against NOAA's Sargassum Inundation Risk (SIR), what the checks showed, and what changed. Done 13 October 2026 for the `sxm` region, and redone the same day after the switch to full-resolution AFAI (section 4). Section 5, on where the drift starts, was added on 22 October 2026. Every table below is the output of the full-resolution run:

```bash
python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11 --smoc
```

## Reference

[SIR v1.5](https://cwcgom.aoml.noaa.gov/SIR/) (NOAA AOML with USF) grades coastal segments every day from AFAI in a 50 to 100 km neighborhood, against a multi-day baseline: low, warning, medium, high. It is published as KMZ, one to two days behind, with a daily archive.

SIR is itself a satellite index, not observed landings. Agreement with it means agreement with NOAA's operational product, not proof of accuracy. Citizen sightings are the other planned reference; there were none yet.

Levels were matched one to one: low = 0, warning = 1, medium = 2, high = 3. Each beach takes the SIR level of its nearest segment. All 17 beaches lie within 0.3 km of a SIR segment.

## Data

```
SIR reports      8 July to 11 October 2026: 94 of 96 days (31 August and 6 September missing)
Our inputs       every second day of that period: 48 days
                 AFAI 7-day composite at full resolution, run through the same detection code as the daily job
                 miamicurrents of the same day, GFS wind for the following 7 days
                 for section 5: the seven daily AFAI images behind each composite (complete for all 48 days)
                 and GFS wind for the 6 days before each date
Samples          782 beach-days at day 0 (48 days x 17 beaches, minus missing SIR days)
```

SIR levels near Saint Martin over the period, in beach-days: low 75, warning 179, medium 475, high 869. Low and warning are rare, which makes the lower thresholds hard to pin down.

Agreement is measured with quadratic weighted kappa (1 is perfect, 0 is chance, below 0 is worse than chance), the usual score for ordered levels.

## Results

### 1. The particle cap distorted the counts

The daily job samples particles down to a cap (now 10,000). With many detections in the box, each particle stands for several seeds, so unweighted, the count near a beach fell as sargassum increased elsewhere:

| Date | Detections | Counts deflated by |
|---|---|---|
| 8 July | 16,052 | 2.3x |
| 20 July | 30,716 | 4.8x |
| 1 August | 25,015 | 3.8x |
| 18 September | 9,079 | 1.2x |

Fixed: counts are now weighted by the seeds each particle stands for (`risk.site_risk(..., weight)`). All results below use these weighted counts.

### 2. Day 0 agrees with SIR only at a large radius

Thresholds were searched exhaustively for each radius, on day 0 (detections only, no drift). Held-out scores fit on alternate dates and score on the others:

| Radius | Best thresholds (Low, Moderate, High) | Kappa, fitted days | Kappa, held out |
|---|---|---|---|
| 10 km (old setting) | 1, 2, 16 | 0.06 | 0.08 and 0.02 |
| 20 km | 1, 2, 47 | 0.20 | 0.14 and 0.11 |
| 30 km | 1, 4, 65 | 0.27 | 0.17 and 0.10 |
| 50 km | 44, 107, 159 | 0.44 | 0.42 and 0.28 |

The old setting (10 km, thresholds 1, 3, 8) scored -0.02 in the first run. At beach scale our detections carry no signal that SIR recognizes: AFAI is masked or skipped right against the coast, and SIR looks 50 to 100 km out. At 50 km the agreement is moderate, but every beach on the island then gets nearly the same level.

The region's fallback thresholds are the 50 km fit: 44, 107, 159. The Low threshold is the least stable one, because SIR rarely says low or warning here.

### 3. The drift forecast does not beat persistence

Day k of a forecast made on date D, scored against SIR on D + k (50 km, cap corrected, thresholds 44, 107, 159). Persistence means carrying SIR on D forward unchanged.

| Kappa against SIR | Day 1 | Day 3 | Day 5 | Day 7 |
|---|---|---|---|---|
| Persistence | 0.57 | 0.30 | 0.24 | 0.20 |
| Drift, geostrophic currents, 2 % windage | 0.26 | 0.12 | 0.02 | -0.10 |
| Drift, SMOC currents (Open-Meteo), 2 % windage | 0.24 | 0.11 | 0.06 | -0.10 |
| Drift, SMOC currents, 1 % windage | 0.24 | -0.04 | 0.19 | 0.07 |

The backtest used analyzed wind and currents, not the forecasts available at the time, so the real drift skill is if anything lower. Total currents (SMOC) did not change the picture, so the currents stay as they are (see `DATA_SOURCES.md`).

### 4. Full resolution needed a higher particle cap

The first run read every second AFAI pixel (3 km cells), which drew each patch on the map as a scatter of round dots. The daily job now reads every pixel (0.015 degrees, about 1.6 km), and detections roughly quadrupled. Two things followed:

- **The particle cap.** With the cap still at 2,500, each particle stood for 9 to 19 seeds, the counts near a beach got noisy, and the best 50 km fit fell to 0.35 (held out 0.26 and 0.12). At 10,000 each particle stands for as many seeds as in the first run (the weights in section 1) and the fit is back to 0.44; with no cap at all it is also 0.44. The first run's best was 0.49 (held out 0.36 and 0.32), the same within the noise of 48 dates. The drift forecast scores a little lower on days 1 and 3 than in the first run (0.26 and 0.12, against 0.37 and 0.20) and a little higher on days 5 and 7; it still trails persistence at every lead time.
- **Coastal glare.** Flagged pixels 1.5 to 3 km from land the product masked had twice the offshore signal, on lee shores too, and the old sampling had skipped them. The glare rule now reaches about 3 km at any resolution (`detect.GLARE_DEG`).

### 5. Drifting each patch from the day it was seen does not help

The 7-day composite keeps each pixel's highest value of the week, so most detections were seen days before the image date (on 19 October 2026, 60% were seen 3 to 6 days before). The drift forecast starts them all on the image date, so a moving mat is counted several times along its track. The test: date each detection from the seven daily images behind the composite (the newest day with the composite's value), let its particles drift from that day to the image date with that week's GFS wind and the date's currents, then forecast as before.

Against SIR, as in section 3 (day 0 is the image date, scored against SIR on that date):

| Kappa against SIR | Day 0 | Day 1 | Day 3 | Day 5 | Day 7 |
|---|---|---|---|---|---|
| Persistence | | 0.57 | 0.30 | 0.24 | 0.20 |
| Drift from the image date, as now (thresholds 44, 107, 159) | 0.44 | 0.26 | 0.12 | 0.02 | -0.10 |
| Drift from the day seen, same thresholds | 0.32 | 0.08 | -0.02 | -0.05 | -0.06 |
| Drift from the day seen, thresholds fitted to it (56, 177, 194) | 0.45 | 0.25 | 0.15 | 0.05 | 0.05 |

Both sets of thresholds were fitted on the same 48 days. With its own thresholds the new start ties the current drift on day 1 and does a little better on later days, but it stays well below persistence at every lead time.

Against the satellite itself: does a patch seen earlier in the week, drifted to the image date, end up nearer the sargassum in that date's own daily image than where it was seen? Share of particles within 5 km of a detection in that image, for the 258,266 particles that every way below leaves afloat on the image date, over the 48 days:

| Seen before the image date | 1 day | 2 days | 3 days | 4 days | 5 days | 6 days | All |
|---|---|---|---|---|---|---|---|
| Where seen, not moved | 32% | 23% | 17% | 16% | 21% | 16% | 22% |
| Drifted as the model does | 31% | 24% | 18% | 16% | 22% | 17% | 22% |
| Same, without the random spread | 32% | 24% | 18% | 15% | 22% | 17% | 22% |
| Currents only, no random spread | 31% | 23% | 16% | 15% | 21% | 16% | 21% |
| Wind only, no random spread | 33% | 25% | 18% | 16% | 23% | 17% | 23% |
| Backward, no random spread (a check) | 27% | 20% | 15% | 13% | 19% | 16% | 19% |

Our currents and wind bring the patches no closer to where sargassum is seen next than leaving them in place. Wind alone comes out a point higher and currents alone a point lower, too little to act on from one season. The test can tell a wrong drift: run backward, the share falls to 19%. What limits the forecast is the drift itself, not the day it starts.

## What changed

Chosen by the owner after these results:

- **Beach levels are NOAA SIR.** Each beach shows the latest SIR level of its nearest segment for every day of the outlook, the approach that beat our forecast at every lead time (`pipeline/sir.py`, `run.beach_levels`).
- **Days 4 to 7 are drawn fainter** on the site and marked "less certain": persistence skill falls from 0.57 on day 1 to 0.20 on day 7.
- **Level names follow NOAA**: Low, Warning, Medium, High. SIR's lowest level means low risk, not "no sargassum".
- **Every patch still starts drifting on the image date** (22 October 2026, section 5): starting each from the day it was seen did no better, so the daily job stays as it was. The map draws the detections seen 3 to 6 days before the image date in gray instead.
- **The drift model stays as context and fallback.** Detections and drift remain on the map. Where SIR has no level for a beach, or the report cannot be fetched, the model's own levels are shown: particles within 50 km, 44 or more is Warning, 107 Medium, 159 High (`regions/sxm.json`, `risk`). `latest.json` keeps both (`risk` shown, `model`, `count`, `source`).

## Limits

- One season (July to October 2026), heavy for sargassum. Other seasons may differ.
- The 17 beaches are strongly correlated (SIR usually gives the whole island one level), so the effective sample is closer to 48 dates than 782 beach-days.
- Differences between beaches cannot be checked against SIR.
- Persistence cannot show sargassum on its way in; a beach stays at its level until the next SIR report.

## Repeating it

```bash
python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11          # SIR, day 0, forecast
python -m pipeline.calibrate --region sxm --start 2026-07-08 --end 2026-10-11 --smoc   # plus SMOC currents
```

`pipeline/calibrate.py` uses the same code as the daily job (detection, seeding, drift, weighted counts) and caches each day's download under `.cache/calibrate/<region>/`. The first run downloads about 900 MB from NOAA (one SIR report and one daily AFAI image per day, and every second day an AFAI composite, currents and two weeks of GFS wind) and can take an hour or more, depending on the servers; with the cache it runs in about 8 minutes. When the region's AFAI settings change, the cached detections are redone and the currents and wind are kept. `--step` sets how often our inputs are used, `--radii` the radii to fit.

Repeat when citizen sightings exist, and at the start of each season.
