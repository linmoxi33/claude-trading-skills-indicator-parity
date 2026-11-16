def _calculate_ema(prices: list[float], period: int) -> float:
    """Calculate EMA from chronological price list."""
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0

    sma = sum(prices[:period]) / period
    ema = sma
    k = 2 / (period + 1)
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema
