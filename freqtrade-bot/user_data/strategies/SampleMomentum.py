# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
"""
SampleMomentum — a STARTER strategy for learning, not a profit guarantee.

Logic (deliberately simple and readable):
  Entry (long):  RSI recovering from oversold  AND  fast EMA above slow EMA
                 AND  price above the slow EMA  (trend filter)
  Exit:          RSI overbought  OR  fast EMA crosses back below slow EMA
  Risk:          hard stoploss + ROI ladder + optional trailing stop

Edit the numbers, backtest, and hyperopt before trusting it with anything.
Docs: https://www.freqtrade.io/en/stable/strategy-customization/
"""
from datetime import datetime  # noqa: F401

import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import (
    IStrategy,
    IntParameter,
    DecimalParameter,
)


class SampleMomentum(IStrategy):
    INTERFACE_VERSION = 3

    # This strategy trades long-only on spot.
    can_short = False

    # Candle timeframe. Must match config "timeframe".
    timeframe = "5m"

    # Only act on new, closed candles.
    process_only_new_candles = True

    # --- Risk management -------------------------------------------------
    # ROI ladder: minutes -> minimum profit to take. Exits at 3% now,
    # relaxing to break-even after 4 hours.
    minimal_roi = {
        "0": 0.03,
        "60": 0.02,
        "120": 0.01,
        "240": 0.0,
    }

    # Hard stop: exit a losing trade at -8%.
    stoploss = -0.08

    # Trailing stop: lock in profit once a trade runs up.
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    # Need enough candles for the slow EMA to be valid.
    startup_candle_count = 200

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # --- Hyperopt-tunable parameters ------------------------------------
    # Run `freqtrade hyperopt` to search these. Defaults are sane starters.
    buy_rsi = IntParameter(20, 40, default=30, space="buy", optimize=True)
    sell_rsi = IntParameter(60, 85, default=70, space="sell", optimize=True)
    ema_fast = IntParameter(8, 30, default=12, space="buy", optimize=True)
    ema_slow = IntParameter(40, 120, default=50, space="buy", optimize=True)
    min_volume_factor = DecimalParameter(
        0.5, 3.0, default=1.0, decimals=1, space="buy", optimize=True
    )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.ema_fast.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.ema_slow.value))

        # Rolling volume average, used as a liquidity/interest filter.
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=30).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # RSI turning up out of oversold
                (qtpylib.crossed_above(dataframe["rsi"], self.buy_rsi.value))
                # uptrend: fast EMA above slow EMA
                & (dataframe["ema_fast"] > dataframe["ema_slow"])
                # price confirms trend
                & (dataframe["close"] > dataframe["ema_slow"])
                # enough volume
                & (dataframe["volume"] > dataframe["volume_mean"] * self.min_volume_factor.value)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # overbought, or trend flips down
                (qtpylib.crossed_above(dataframe["rsi"], self.sell_rsi.value))
                | (qtpylib.crossed_below(dataframe["ema_fast"], dataframe["ema_slow"]))
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1
        return dataframe
