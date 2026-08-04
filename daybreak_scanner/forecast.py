"""Optional TimesFM-based trend forecast, layered on top of the scanner.

Google's TimesFM (https://github.com/google-research/timesfm) is a pretrained
time-series foundation model. This module feeds it each qualifying
candidate's daily closes (the same bars already fetched for RVOL/ATR -- no
new API calls) and records the forecasted short-horizon trend as an
*additional, informational* field on Signal. It never gates qualification and
is never the qualification-decisive result of anything: the ATR-based
entry/stop/target rule (`daybreak_scanner.signals`) is unchanged and remains
the sole basis for the mechanical trade plan.

This module has NOT been exercised against the real `timesfm` package or real
model weights: this dev environment's network policy blocks both Hugging Face
Hub (where the checkpoint lives) and the lean CPU-only PyTorch wheel index, so
neither could be installed/verified here. `TimesFMForecaster` is written from
the published API surface but is unverified until run somewhere with normal
internet access. `timesfm`/`torch` are only imported lazily, inside
`TimesFMForecaster`, so the rest of daybreak_scanner works without them
installed at all -- this is strictly an opt-in extra (`pip install
'project-daybreak[forecast]'`), enabled per-run via `--with-forecast`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol

from daybreak_features.models import DailyBar

DEFAULT_HORIZON = 5
DEFAULT_CONTEXT_SESSIONS = 90


class Forecaster(Protocol):
    """A batched point forecaster: one call, many tickers.

    Implementations should raise ForecastError (not a bare exception) on
    failure so callers can degrade gracefully, matching the rest of the
    scanner's ScannerError convention.
    """

    def forecast(
        self, closes_by_ticker: Mapping[str, Sequence[Decimal]], *, horizon: int
    ) -> dict[str, tuple[Decimal, ...]]: ...


class ForecastError(RuntimeError):
    pass


def trend_pct(closes: Sequence[Decimal], point_forecast: Sequence[Decimal]) -> Decimal | None:
    """Percent change from the last real close to the forecast's final step.

    None if there's nothing to compare (empty context or empty forecast) --
    never a fabricated number.
    """
    if not closes or not point_forecast:
        return None
    last_real = closes[-1]
    if last_real == 0:
        return None
    return (point_forecast[-1] - last_real) / last_real * 100


def daily_closes_by_ticker(
    bars_by_ticker: Mapping[str, Sequence[DailyBar]],
    *,
    lookback_sessions: int = DEFAULT_CONTEXT_SESSIONS,
) -> dict[str, tuple[Decimal, ...]]:
    """The most recent `lookback_sessions` closes per ticker, oldest first --
    the shape TimesFM's `inputs` expects (one 1D series per ticker)."""
    result: dict[str, tuple[Decimal, ...]] = {}
    for ticker, bars in bars_by_ticker.items():
        ordered = sorted(bars, key=lambda bar: bar.session_date)[-lookback_sessions:]
        if ordered:
            result[ticker] = tuple(bar.close for bar in ordered)
    return result


class TimesFMForecaster:
    """Wraps google-research/timesfm's 2.5-200m checkpoint. Unverified -- see
    module docstring. Lazily imports timesfm/torch/numpy so importing this
    class (or this module) costs nothing without them installed; the actual
    import only happens on first `forecast()` call, and the loaded model is
    cached on the instance across calls."""

    def __init__(self, *, checkpoint: str = "google/timesfm-2.5-200m-pytorch") -> None:
        self._checkpoint = checkpoint
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is not None:
            return self._model
        try:
            import timesfm
        except ImportError as exc:
            raise ForecastError(
                "timesfm is not installed; install with pip install 'project-daybreak[forecast]'"
            ) from exc
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self._checkpoint)
        model.compile(
            timesfm.ForecastConfig(
                max_context=1024,
                max_horizon=256,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
            )
        )
        self._model = model
        return model

    def forecast(
        self, closes_by_ticker: Mapping[str, Sequence[Decimal]], *, horizon: int = DEFAULT_HORIZON
    ) -> dict[str, tuple[Decimal, ...]]:
        if not closes_by_ticker:
            return {}
        try:
            import numpy as np
        except ImportError as exc:
            raise ForecastError("numpy is not installed") from exc
        model = self._load()
        tickers = list(closes_by_ticker.keys())
        inputs = [np.array([float(value) for value in closes_by_ticker[t]]) for t in tickers]
        try:
            point_forecast, _quantile_forecast = model.forecast(  # type: ignore[attr-defined]
                horizon=horizon, inputs=inputs
            )
        except Exception as exc:  # pragma: no cover - real-model failure path, unverified here
            raise ForecastError(f"timesfm forecast call failed: {exc}") from exc
        return {
            ticker: tuple(Decimal(str(value)) for value in row)
            for ticker, row in zip(tickers, point_forecast, strict=True)
        }
