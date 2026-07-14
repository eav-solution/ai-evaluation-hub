# RunReport chart labels — design

**Date:** 2026-07-14
**File touched:** `frontend/components/RunReport.tsx`

## Problem

Charts in the run report are confusing because axis labels are stripped. Users
see anonymous bars and an unreadable radar, and must hover to learn which metric
each mark represents.

Root cause (current code):

- `Mean by metric` bar chart — `<XAxis dataKey="metric_key" tick={false} />`
  (line 166) hides metric names. Bars are unlabeled.
- `Metric profile` radar — `<PolarAngleAxis dataKey="metric_key" tick={false} />`
  (line 191) hides axis labels around the radar.
- `Score distribution` histogram — no axis titles.

User confirmed the dominant pain is **missing labels**. Chart-type and
pooled-distribution concerns are out of scope for this change.

## Design

### 1. Mean by metric → horizontal bar

Convert the bar chart to a horizontal layout so long metric keys read straight
without truncation and scale from 2 to ~10 metrics.

- `BarChart` gains `layout="vertical"` and a left `margin` (~120px) for labels.
- `XAxis` becomes `type="number"` with `domain={[0, 1]}`.
- `YAxis` becomes `type="category"` `dataKey="metric_key"` with ticks shown
  (remove `tick={false}`).
- Bar keeps `dataKey="mean"`.

If a metric key is very long it may still overflow the margin. Mitigation:
prefer a shorter display label from the metric catalog (`metricsByKey`) when a
name is available; otherwise rely on the widened margin.

### 2. Metric profile (radar)

- Remove `tick={false}` on `PolarAngleAxis` so metric names render around the
  radar.
- Keep the existing `run.summaries.length > 2` gate — radar is only meaningful
  with 3+ axes.

### 3. Score distribution

- Add axis labels: X = "Score range", Y = "Count".
- Keep the current all-metric pooling logic unchanged.

## Out of scope

- Summary cards, row-results table, data flow — unchanged.
- Per-metric split of the score distribution.
- Replacing radar/histogram with different chart types.

## Testing

- Run with 1 metric: bar labeled, radar hidden (gate), histogram labeled.
- Run with 2 metrics: bar labeled, radar hidden, histogram labeled.
- Run with 4+ metrics: bar labeled, radar labels visible and readable.
- Long metric key (e.g. `answer_relevancy`): label fits or truncates cleanly.
