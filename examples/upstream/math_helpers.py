def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average using the standard ``2/(period+1)`` smoother.

    The seed is the simple average of the first ``period`` values; subsequent
    bars update the EMA as ``ema = price * alpha + ema_prev * (1 - alpha)``.

    Returns ``None`` if there are fewer than ``period`` values.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    ema_value = seed
    for v in values[period:]:
        ema_value = v * alpha + ema_value * (1 - alpha)
    return ema_value
