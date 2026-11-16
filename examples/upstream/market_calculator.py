def calculate_ema(prices: list[float], period: int = 50) -> float:
    """
    Calculate Exponential Moving Average

    Args:
        prices: List of prices (most recent first)
        period: EMA period (default 50)

    Returns:
        EMA value

    Formula: EMA = Price * k + EMA_prev * (1-k), where k = 2/(period+1)
    """
    if len(prices) < period:
        return sum(prices) / len(prices)  # Fallback to simple average

    # Reverse to oldest-first for calculation
    prices_reversed = prices[::-1]

    # Initialize with SMA
    sma = sum(prices_reversed[:period]) / period
    ema = sma

    # Calculate EMA
    k = 2 / (period + 1)
    for price in prices_reversed[period:]:
        ema = price * k + ema * (1 - k)

    return ema
