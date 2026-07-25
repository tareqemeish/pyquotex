# Quotex 5-Second Digit Trading Bot

A complete, single-file trading bot for Quotex that trades based on digit extraction and comparison.

## Features

✅ **5-Second TIMER Trades** - Uses `optionType=100` for true 5-second expiry
✅ **Digit Strategy** - Compares price digits every 5 seconds
✅ **Live Dashboard** - Real-time Rich terminal display
✅ **CSV Logging** - All trades logged with full details
✅ **Auto-Reconnect** - Handles connection drops gracefully
✅ **Risk Management** - Take profit, stop loss, consecutive loss cooldown
✅ **Server Sync** - Precise timing with Quotex server clock

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Configuration

Edit `config.py`:

```python
# Credentials
EMAIL = "your-email@example.com"
PASSWORD = "your-password"

# Trading
ASSET = "EURUSD_otc"          # Asset to trade
STAKE = 1.0                   # Trade amount in USD
DIGIT_POSITION = 3            # Digit position from right
DEMO_ACCOUNT = True           # True for demo, False for real

# Risk Management
TAKE_PROFIT = 10.0            # Take profit in USD (0 = disabled)
STOP_LOSS = 5.0               # Stop loss in USD (0 = disabled)
MAX_CONSECUTIVE_LOSSES = 5    # Max consecutive losses before cooldown
COOLDOWN_SECONDS = 0          # Cooldown after losses (0 = disabled)
```

## Usage

```bash
python bot.py
```

## How It Works

### 5-Second Trading Cycle

```
T=0s: Candle opens
T=1-2s: Wait
T=3s: ⚡ EXACT MOMENT
  - Read live price
  - Extract digit at position 3
  - Compare with previous digit:
    * If increased: CALL ⬆️
    * If decreased: PUT ⬇️
    * If unchanged: SKIP
T=4s: Wait
T=5s: Trade closes, repeat
```

### Digit Extraction Example

Price: `1.23456`
Digit Position: `3`
Result: Extract digit `4` (position 3 from right)

## Dashboard

Live display shows:
- Connection status
- Current asset & balance
- Live price & digits
- Trading signal
- Statistics (wins, losses, P/L)
- Consecutive losses counter

## CSV Logging

All trades saved to `trades.csv`:

```csv
timestamp,asset,entry_price,previous_digit,current_digit,direction,amount,result,profit_loss,balance,trade_id
2026-07-25T10:30:15.000Z,EURUSD_otc,1.09876,5,6,call,1.0,WIN,+2.50,1234.56,67890
```

## Risk Management

### Take Profit
Bot stops when total profit reaches configured amount.

### Stop Loss
Bot stops when total loss exceeds configured amount.

### Consecutive Loss Cooldown
After N consecutive losses, bot enters cooldown period before trading again.

## PyQuotex Integration

Bot uses PyQuotex v1.1.0+ with:
- `time_mode="TIMER"` → Forces 5-second TIMER trades (optionType=100)
- `duration=5` → Exact 5-second expiry
- Event-driven order confirmation
- WebSocket real-time price streaming
- Server time synchronization

## File Structure

```
.
├── bot.py           # Complete bot (all logic in one file)
├── config.py        # Configuration only
├── requirements.txt # Dependencies
├── trades.csv       # Generated trade log
└── README.md        # This file
```

## Requirements

- Python 3.12+
- Quotex account (demo or real)
- PyQuotex 1.1.0+
- Rich for terminal UI

## Warnings

⚠️ **This bot trades real money on Quotex. Use at your own risk.**

- Start with DEMO account
- Test thoroughly
- Use small stakes
- Monitor continuously
- Understand binary options risks

## Troubleshooting

### Connection Failed
- Check email/password in `config.py`
- Verify internet connection
- Check Quotex account status

### No Price Data
- Ensure asset is open for trading
- Try different asset (e.g., `EURUSD` instead of `EURUSD_otc`)
- Check WebSocket connection in logs

### Trades Not Placing
- Verify balance is sufficient
- Check asset is available
- Review bot logs for errors

## Support

For issues:
1. Check `config.py` settings
2. Review bot console output
3. Check `trades.csv` for trade history
4. Enable `DEBUG = True` in config.py for detailed logging

---

**Happy Trading! 📈**
