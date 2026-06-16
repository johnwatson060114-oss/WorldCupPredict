# Betting Data Debug Handoff

This note summarizes the current issue for debugging the WorldCupPredict betting pages.

## Current Symptoms

- The live home page shows: `次日暂无可用比赛`.
- The `今日方案` page keeps the navigation visible, but has no match cards.
- The `我的投注` page can open, but the selected match date shows `暂无比赛`.
- The betting ticket panel says: `历史快照未归档“胜平负”赔率，无法生成真实票面。`
- Yesterday's matches may still appear as `未开售`.

## Main Diagnosis

The UI and ticket-page layout are already present. The blocker is the data pipeline.

The app is not receiving usable match and odds data for the target date, so the ticket UI can only render an empty shell.

## Files And Interfaces To Check

### Daily Forecast

Check:

```text
public/data/daily-forecast.json
```

Important fields:

- `targetDate`
- `status`
- `statusMessage`
- `matches`
- `portfolios`

Expected problem:

- `matches` is probably `[]`.
- `statusMessage` likely contains `目标日期没有可用比赛种子数据`.
- The target date may be `2026-06-17`.

Live URL:

```text
https://johnwatson060114-oss.github.io/WorldCupPredict/data/daily-forecast.json
```

### Historical Odds Snapshots

Check:

```text
public/data/history/2026-06-15.json
public/data/history/2026-06-16.json
public/data/history/2026-06-17.json
```

Live URL pattern:

```text
https://johnwatson060114-oss.github.io/WorldCupPredict/data/history/YYYY-MM-DD.json
```

Important content:

- Match list for the selected date.
- `胜平负` odds.
- `让球胜平负` odds.
- `比分` odds.
- `总进球数` odds.
- `半全场` odds.

Expected problem:

- The file exists but does not contain archived odds for the selected play type.
- Or the match list exists, but the frontend cannot map the selected date/play type to the stored data shape.

## Code Entry Points

### App Shell And Forecast Page

```text
src/App.tsx
```

Check:

- How `daily-forecast.json` is loaded.
- How empty `matches` is handled.
- Whether the empty forecast state blocks only `今日方案`, not the whole app.

### Personal Betting Page

```text
src/pages/PersonalBetPage.tsx
```

Check:

- Which historical snapshot is loaded for `比赛日期`.
- How it maps snapshot matches into the ticket selector.
- How play types are matched to odds fields.
- Why `胜平负` becomes `历史快照未归档`.
- Why a date with no odds becomes `暂无比赛` instead of showing matches with unavailable odds.

### Pass Type Calculation

```text
src/lib/pass-types.ts
```

Check:

- Pass type definitions.
- Bet count calculation.
- Ticket amount calculation.
- Whether empty selections are handled safely.

### Data Generation / Deployment

Check likely generation scripts:

```text
scripts/
pipeline/
manual-data/
.github/workflows/daily-pages.yml
```

Search terms:

```text
daily-forecast
history
targetDate
matches
statusMessage
胜平负
未开售
```

## What Needs To Be Done

1. Fix `daily-forecast.json` generation.

   When real APIs fail or football-data.org has no World Cup schedule, fallback data should still provide usable fixed sample matches instead of `matches: []`.

2. Fix historical odds snapshots.

   Ensure `public/data/history/2026-06-17.json` contains real or sample matches and odds for at least `胜平负`.

3. Improve frontend fallback behavior.

   If a play type has no odds, the UI should still show the match and mark only that play type as `未开售` or `无赔率`.

   It should not collapse the whole date into `暂无比赛` when some match metadata exists.

4. Verify ticket generation.

   After data is present, the `我的投注` page should be able to:

   - Select a match.
   - Select play type odds.
   - Choose pass type such as `单关`, `2串1`, `3串1`.
   - Generate ticket preview with pass type, bet count, multiplier, amount, and theoretical max payout.

5. Build and publish.

   Run:

   ```powershell
   npm.cmd test -- --run
   npm.cmd run build
   ```

   Then push the fixed data/code to `main` and check GitHub Pages.

## Quick Verification Checklist

- `daily-forecast.json` has non-empty `matches`.
- `history/2026-06-17.json` has at least one match.
- That match has `胜平负` odds.
- `今日方案` shows match cards.
- `我的投注` for `2026/06/17` shows real matches instead of `暂无比赛`.
- Selecting `胜平负` odds creates a ticket preview.
- Missing play types show `未开售` only for that play type.

## One-Line Summary

The betting UI has been deployed, but the match and odds data are missing or not mapped correctly. Debug `public/data/daily-forecast.json`, `public/data/history/YYYY-MM-DD.json`, and the loader/mapping logic in `src/pages/PersonalBetPage.tsx`.
