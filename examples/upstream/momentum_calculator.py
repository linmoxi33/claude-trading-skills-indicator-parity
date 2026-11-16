def _ema(values: list[float], span: int = 3) -> list[float]:
    """Calculate Exponential Moving Average.

    Args:
        values: List of float values
        span: EMA span (default 3)

    Returns:
        List of EMA values, same length as input. Empty list if input is empty.
    """
    if not values:
        return []
    if len(values) == 1:
        return [values[0]]

    alpha = 2.0 / (span + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        ema_val = alpha * values[i] + (1 - alpha) * result[-1]
        result.append(ema_val)
    return result
