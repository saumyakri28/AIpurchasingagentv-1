"""Frozen clock for deterministic seeds and evals."""

from datetime import date, datetime

# Every fixture world, eval, and demo treats this as "today" unless overridden in YAML.
FROZEN_TODAY = date(2026, 9, 15)
FROZEN_NOW = datetime(2026, 9, 15, 8, 0, 0)
DEFAULT_RANDOM_SEED = 42
HISTORY_DAYS = 120
FORECAST_HORIZON_DAYS = 56
