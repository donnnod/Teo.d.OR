"""Lazy Kronos wrapper.

Kronos is an open-source (MIT) foundation model for financial K-lines. It's a PyTorch model, so
torch + huggingface-hub are optional extras (`pip install -e ".[kronos]"`). This wrapper:

  * loads the model lazily on first use,
  * caches the loaded instance,
  * and — if torch/weights are unavailable or loading fails — cleanly signals that the caller
    should fall back to the baseline (it never hard-crashes a forecast request).

The actual tokenizer/model-head inference is intentionally left as a clearly-marked TODO so the
real integration lands in one focused change; everything around it (loading, device handling,
fallback, response shaping) is real.
"""

from __future__ import annotations

from teo.config import settings
from teo.models import Candle, ForecastResponse


class KronosUnavailable(RuntimeError):
    """Raised when Kronos can't be used; the service falls back to the baseline."""


class KronosForecaster:
    name: str

    def __init__(self, model_id: str, device: str = "cpu") -> None:
        if not model_id:
            raise KronosUnavailable("TEO_KRONOS_MODEL is not set")
        self.model_id = model_id
        self.device = device
        self.name = f"kronos:{model_id}"
        self._model = None  # loaded lazily

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import torch  # noqa: F401
            from huggingface_hub import snapshot_download
        except ImportError as e:  # torch/hf not installed
            raise KronosUnavailable(f"Kronos extras not installed: {e}") from e

        try:
            # Download & cache weights. Real model construction is wired here.
            self._weights_path = snapshot_download(self.model_id)
            # TODO(kronos): construct the Kronos tokenizer + model from self._weights_path,
            #   move to self.device, set eval(). Tracked in the roadmap.
            self._model = object()  # placeholder marking "weights present"
        except Exception as e:  # network/repo/format issues
            raise KronosUnavailable(f"failed to load Kronos '{self.model_id}': {e}") from e

    def forecast(
        self, candles: list[Candle], horizon: int, *, symbol: str, interval: str
    ) -> ForecastResponse:
        self._ensure_loaded()
        # TODO(kronos): run real inference over the OHLCV tensor and shape the forecast points.
        # Until the model head is wired, surface this honestly rather than fabricating numbers.
        raise KronosUnavailable(
            "Kronos weights are present but inference is not wired yet; using baseline"
        )


_INSTANCE: KronosForecaster | None = None


def get_kronos() -> KronosForecaster | None:
    """Return a cached Kronos forecaster, or None if it can't be constructed."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    try:
        _INSTANCE = KronosForecaster(settings.kronos_model, settings.kronos_device)
    except KronosUnavailable:
        return None
    return _INSTANCE
