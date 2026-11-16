    def _calculate_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
        """Calculate RSI using Wilder's smoothing method."""
        if prices is None or len(prices) < period + 1:
            return None

        deltas = prices.diff()

        gains = deltas.where(deltas > 0, 0.0)
        losses = (-deltas).where(deltas < 0, 0.0)

        first_avg_gain = gains.iloc[1 : period + 1].mean()
        first_avg_loss = losses.iloc[1 : period + 1].mean()

        avg_gain = first_avg_gain
        avg_loss = first_avg_loss

        for i in range(period + 1, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)
