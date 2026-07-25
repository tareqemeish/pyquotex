"""Quotex 5-second digit bot configuration."""
import os

# Credentials
EMAIL = os.getenv("QUOTEX_EMAIL", "your-email@example.com")
PASSWORD = os.getenv("QUOTEX_PASSWORD", "your-password")

# Account
DEMO_ACCOUNT = True  # Set to False for REAL trading

# Trading
ASSET = "EURUSD_otc"  # Asset to trade
STAKE = 1.0  # Trade amount in USD
DIGIT_POSITION = 3  # Digit position from right (0-indexed)
EXPIRY_TIME = 5  # ALWAYS 5 seconds (TIMER mode)

# Risk Management
TAKE_PROFIT = 10.0  # Take profit in USD (or 0 to disable)
STOP_LOSS = 5.0  # Stop loss in USD (or 0 to disable)
MAX_CONSECUTIVE_LOSSES = 5  # Max consecutive losses before cooldown
COOLDOWN_SECONDS = 0  # Cooldown after max losses (0 = disabled)

# Logging
LOG_FILE = "trades.csv"
DEBUG = False

# Server sync
RECONNECT_TIMEOUT = 30  # Reconnection timeout in seconds
