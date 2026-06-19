# Total Goals Model Adoption Policy

## Current Production Rule

- The current `hierarchical_poisson[half_life_days=730,rho=0,shrinkage=24,tournament_tier=1]` model remains the primary production model.
- The optimized candidate selected from 2018 and 2022 World Cup validation runs in shadow mode.
- Daily reports should show both model lines: exact total-goals bucket accuracy, strongest adjacent two-bucket accuracy, average log loss, and prediction distribution.
- Do not switch models because of one matchday or a small-sample swing.

## Switch Gates

Switch from the current model to the candidate only when all gates pass on settled 2026 World Cup matches:

- At least 24 settled 2026 matches.
- Candidate exact bucket accuracy is at least 8 percentage points higher.
- Candidate has at least 3 more exact hits.
- Candidate average total-goals log loss improves by at least 0.02.
- Candidate core two-bucket accuracy is not more than 5 percentage points worse.

## Decision Labels

- `observe`: sample is still too small; keep both lines.
- `keep`: sample is large enough, but candidate has not shown a stable advantage.
- `switch`: candidate clears every gate and becomes the new production model.

## Manual Result Intake

When the public CSV source is behind live results, add confirmed new matches to:

`artifacts/total-goals-backtest/manual_2026_results.csv`

The script deduplicates against the public CSV by date, home team, and away team.

## Daily Run Mode

Run the script normally for daily tracking; it compares the current production model with the locked shadow candidate. Use `TOTAL_GOALS_FULL_GRID=1` only when deliberately reselecting the candidate from the full 2018 and 2022 validation grid.
