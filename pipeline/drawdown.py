from __future__ import annotations

"""Drawdown-aware bet sizing for the three strategy portfolios.

When a strategy's rolling bankroll drops below its initial stake, risk-of-ruin
increases non-linearly.  This module translates a drawdown ratio into
multiplicative adjustments that the portfolio builder and the frontend scaler
both apply so that losing strategies become more selective and bet smaller.

All protections are **continuous** — there are no binary gates that would
paradoxically silence a risk-taking strategy while a safer one still bets.

Core concept
------------
dr = current_bankroll / initial_bankroll   (always in (0, 1] for underwater)

- Stake sizes shrink with **dr²** (quadratic): at 75 % capital you bet ~56 %
  of baseline, not 75 %.
- Edge thresholds rise with **1/dr**: at 75 % capital you need 33 % higher
  expected return to justify the same bet.
- Max single-ticket slots shrink with **dr**: fewer positions → less exposure.
"""

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

STAKE_EXPONENT = 2.0          # quadratic scaling: stake ∝ dr^2
EDGE_MAX_MULTIPLIER = 3.0     # edge requirement ceiling (at deep drawdown)
EDGE_DR_FLOOR = 0.1           # floor for edge-multiplier denominator
STAKE_MULT_FLOOR = 0.01       # absolute floor on the stake multiplier


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def drawdown_ratio(bankroll: float, initial_bankroll: float = 200.0) -> float:
    """Current bankroll as a fraction of initial.  Clamped to ≥ 0.001."""
    return max(0.001, bankroll / max(initial_bankroll, 1.0))


def stake_multiplier(dr: float) -> float:
    """Quadratic scaling factor for individual ticket stakes.

    At dr = 1.0  → 1.00   (full baseline)
    At dr = 0.75 → 0.56   (56 % of baseline — not 75 %)
    At dr = 0.50 → 0.25   (25 % of baseline)
    """
    return max(STAKE_MULT_FLOOR, min(1.0, dr ** STAKE_EXPONENT))


def edge_multiplier(dr: float) -> float:
    """Factor to multiply strategy min_edge by when underwater.

    At dr = 1.0  → 1.00   (unchanged)
    At dr = 0.75 → 1.33   (need 33 % higher edge)
    At dr = 0.50 → 2.00   (need double the edge)
    At dr = 0.10 → 3.00   (capped — even in deep drawdown, don't go infinite)
    """
    return max(1.0, min(EDGE_MAX_MULTIPLIER, 1.0 / max(dr, EDGE_DR_FLOOR)))


def adjusted_max_singles(base_max_singles: int, dr: float) -> int:
    """Reduce max single-ticket slots when underwater.

    Conservative (max 2): at dr=0.75 → 1 slot; at dr=1.0 → 2 slots.
    Aggressive (max 4):  at dr=0.75 → 3 slots; at dr=0.50 → 2 slots.
    """
    return max(1, int(base_max_singles * dr))
