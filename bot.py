#!/usr/bin/env python3
"""Quotex 5-second digit trading bot - Complete single-file implementation.

Strategy:
- Every 5 seconds, at second 3 of the cycle, read the live price
- Extract a digit at configured position from the price
- Compare with previous digit:
  * If increased: CALL
  * If decreased: PUT
  * If unchanged: SKIP
- Execute 5-second TIMER trade immediately
- Log all trades to CSV
- Monitor balance, P/L, win rate
- Auto-reconnect on connection loss
"""

import asyncio
import csv
import logging
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

try:
    from pyquotex.stable_api import Quotex
    from pyquotex.utils.account_type import AccountType
except ImportError:
    print("ERROR: PyQuotex not installed. Run: pip install pyquotex rich")
    exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
except ImportError:
    print("ERROR: Rich not installed. Run: pip install rich")
    exit(1)

import config

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
console = Console()


class QuotexDigitBot:
    """5-second digit trading bot."""

    def __init__(self):
        self.client: Optional[Quotex] = None
        self.running = False
        self.connected = False

        # Trading state
        self.previous_digit: Optional[int] = None
        self.current_price: Optional[float] = None
        self.previous_price: Optional[float] = None

        # Statistics
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.consecutive_losses = 0
        self.current_profit = 0.0
        self.total_profit = 0.0
        self.balance = 0.0
        self.last_trade_id: Optional[str] = None
        self.last_trade_time = 0.0

    async def connect(self) -> bool:
        """Connect to Quotex."""
        try:
            console.print("[cyan]Connecting to Quotex...[/cyan]")
            self.client = Quotex(
                email=config.EMAIL,
                password=config.PASSWORD,
                lang="en",
            )

            is_demo = config.DEMO_ACCOUNT
            connected, reason = await self.client.connect()

            if not connected:
                console.print(f"[red]Connection failed: {reason}[/red]")
                return False

            console.print(f"[green]✓ Connected: {reason}[/green]")

            # Set account mode
            if is_demo:
                await self.client.set_account_mode("PRACTICE")
                console.print("[yellow]Using DEMO account[/yellow]")
            else:
                await self.client.set_account_mode("REAL")
                console.print("[red]Using REAL account[/red]")

            # Get balance
            self.balance = await self.client.get_balance()
            console.print(f"[cyan]Balance: ${self.balance:.2f}[/cyan]")

            self.connected = True
            return True

        except Exception as e:
            console.print(f"[red]Connection error: {e}[/red]")
            logger.error(f"Connection error: {e}", exc_info=True)
            return False

    async def close(self) -> None:
        """Close connection."""
        if self.client:
            try:
                await self.client.close()
                console.print("[cyan]Disconnected[/cyan]")
            except Exception as e:
                logger.error(f"Close error: {e}")

    def extract_digit(self, price: float) -> int:
        """Extract digit at configured position from price.

        Example: price=1.23456, digit_position=3
        Remove decimal: "123456"
        Index from right: position 3 = digit "4"
        """
        price_str = f"{price:.10f}".replace(".", "")
        digits = price_str.lstrip("0") or "0"

        if config.DIGIT_POSITION >= len(digits):
            digit = int(digits[-1])
        else:
            idx = len(digits) - 1 - config.DIGIT_POSITION
            digit = int(digits[idx]) if idx >= 0 else 0

        return digit % 10

    async def get_server_time_offset(self) -> float:
        """Get offset between local and server time in seconds."""
        try:
            if (
                hasattr(self.client.api, "timesync")
                and self.client.api.timesync
            ):
                server_ts = self.client.api.timesync.server_timestamp
                if server_ts:
                    local_ts = time.time()
                    offset = server_ts - local_ts
                    return offset
        except Exception as e:
            logger.debug(f"Failed to get time offset: {e}")
        return 0.0

    async def wait_until_exact_second(
        self, target_second: int, tolerance_ms: int = 50
    ) -> None:
        """Wait until exact second in 5-second cycle.

        5-second cycles: :00, :05, :10, :15, :20, :25, :30, etc.
        target_second: 0-4 (0=start, 3=price read, 4=end)
        """
        offset = await self.get_server_time_offset()

        while True:
            current_time = time.time() + offset
            current_second = int(current_time) % 5
            current_ms = int((current_time % 1) * 1000)

            if current_second == target_second and current_ms < tolerance_ms:
                break

            await asyncio.sleep(0.01)

    async def get_current_price(self) -> Optional[float]:
        """Get current live price from WebSocket."""
        try:
            # Try realtime price first
            if (
                hasattr(self.client.api, "realtime_price")
                and self.client.api.realtime_price
            ):
                prices = self.client.api.realtime_price.get(config.ASSET, [])
                if prices:
                    latest = prices[-1]
                    if isinstance(latest, dict) and "price" in latest:
                        return float(latest["price"])
                    elif isinstance(latest, (int, float)):
                        return float(latest)

            # Fallback: get candles
            candles = await self.client.get_candles(
                config.ASSET, time.time(), 1, 1
            )
            if candles and len(candles) > 0:
                candle = candles[-1]
                if isinstance(candle, dict) and "close" in candle:
                    return float(candle["close"])

        except Exception as e:
            logger.error(f"Failed to get price: {e}")

        return None

    async def place_5second_trade(
        self, direction: str, price: float
    ) -> Tuple[bool, Optional[str]]:
        """Place 5-second TIMER trade.

        Args:
            direction: "call" or "put"
            price: Entry price

        Returns:
            (success, trade_id)
        """
        try:
            # Ensure price stream is active
            await self.client.start_realtime_price(config.ASSET, 5)
            await self.client.get_server_time()

            # Apply settings
            await self.client.api.settings_apply(
                asset=config.ASSET,
                period=5,
                is_fast_option=False,
                end_time=int(time.time()) + 5,
            )

            # Place trade with TIMER mode (optionType=100)
            status, buy_info = await self.client.buy(
                amount=config.STAKE,
                asset=config.ASSET,
                direction=direction,
                duration=5,
                time_mode="TIMER",  # Key: Forces optionType=100 for 5-second trade
            )

            if status and isinstance(buy_info, dict):
                trade_id = buy_info.get("id")
                logger.info(
                    f"Trade placed: {direction.upper()} {config.ASSET} "
                    f"@ {price:.5f} | ID: {trade_id}"
                )
                return True, str(trade_id) if trade_id else None
            else:
                logger.error(f"Trade failed: {buy_info}")
                return False, None

        except Exception as e:
            logger.error(f"Trade error: {e}", exc_info=True)
            return False, None

    async def check_trade_result(
        self, trade_id: str
    ) -> Tuple[bool, float]:
        """Check if trade won.

        Returns:
            (is_win, profit)
        """
        try:
            win, profit = await self.client.check_win(trade_id, timeout=10)
            return win == "win", float(profit)
        except Exception as e:
            logger.error(f"Error checking trade: {e}")
            return False, 0.0

    async def update_balance(self) -> float:
        """Get current balance."""
        try:
            balance = await self.client.get_balance()
            return float(balance)
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return self.balance

    def log_trade(
        self,
        trade_id: Optional[str],
        direction: str,
        entry_price: float,
        prev_digit: int,
        curr_digit: int,
        result: Optional[str],
        profit_loss: float,
    ) -> None:
        """Log trade to CSV."""
        try:
            file_exists = Path(config.LOG_FILE).exists()
            with open(config.LOG_FILE, "a", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp",
                        "asset",
                        "entry_price",
                        "previous_digit",
                        "current_digit",
                        "direction",
                        "amount",
                        "result",
                        "profit_loss",
                        "balance",
                        "trade_id",
                    ],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "asset": config.ASSET,
                        "entry_price": f"{entry_price:.5f}",
                        "previous_digit": prev_digit,
                        "current_digit": curr_digit,
                        "direction": direction,
                        "amount": config.STAKE,
                        "result": result or "PENDING",
                        "profit_loss": f"{profit_loss:+.2f}",
                        "balance": f"{self.balance:.2f}",
                        "trade_id": trade_id or "",
                    }
                )
        except Exception as e:
            logger.error(f"Logging error: {e}")

    def build_dashboard(self) -> Panel:
        """Build live dashboard."""
        # Status
        status_text = Text()
        if self.connected:
            status_text.append("🟢 CONNECTED", style="green bold")
        else:
            status_text.append("🔴 DISCONNECTED", style="red bold")

        status_panel = Panel(
            status_text,
            title="[cyan]Connection[/cyan]",
            border_style="cyan",
            expand=False,
        )

        # Account info
        info_table = Table(show_header=False, box=None)
        info_table.add_row(
            "[cyan]Asset[/cyan]", f"[yellow]{config.ASSET}[/yellow]"
        )
        info_table.add_row(
            "[cyan]Balance[/cyan]", f"[green]${self.balance:.2f}[/green]"
        )
        info_table.add_row(
            "[cyan]Stake[/cyan]", f"[yellow]${config.STAKE}[/yellow]"
        )
        info_table.add_row(
            "[cyan]Expiry[/cyan]", f"[yellow]5s (TIMER)[/yellow]"
        )

        # Price data
        price_table = Table(show_header=False, box=None)
        current = self.current_price or 0.0
        previous = self.previous_price or 0.0
        current_digit = self.previous_digit or 0
        prev_digit = (
            self.extract_digit(previous) if previous > 0 else 0
        )

        price_table.add_row(
            "[cyan]Current Price[/cyan]", f"[yellow]{current:.5f}[/yellow]"
        )
        price_table.add_row(
            "[cyan]Previous Price[/cyan]", f"[yellow]{previous:.5f}[/yellow]"
        )
        price_table.add_row(
            f"[cyan]Current Digit (Pos {config.DIGIT_POSITION})[/cyan]",
            f"[yellow]{current_digit}[/yellow]",
        )
        price_table.add_row(
            f"[cyan]Previous Digit (Pos {config.DIGIT_POSITION})[/cyan]",
            f"[yellow]{prev_digit}[/yellow]",
        )

        # Signal
        if current_digit > prev_digit:
            signal_text = "[green]CALL ⬆️[/green]"
        elif current_digit < prev_digit:
            signal_text = "[red]PUT ⬇️[/red]"
        else:
            signal_text = "[yellow]SKIP ➡️[/yellow]"
        price_table.add_row("[cyan]Signal[/cyan]", signal_text)

        # Statistics
        stats_table = Table(show_header=False, box=None)
        stats_table.add_row(
            "[cyan]Total Trades[/cyan]", f"[yellow]{self.total_trades}[/yellow]"
        )
        stats_table.add_row(
            "[cyan]Wins[/cyan]", f"[green]{self.wins}[/green]"
        )
        stats_table.add_row(
            "[cyan]Losses[/cyan]", f"[red]{self.losses}[/red]"
        )
        win_rate = (
            (self.wins / self.total_trades * 100)
            if self.total_trades > 0
            else 0.0
        )
        stats_table.add_row(
            "[cyan]Win Rate[/cyan]", f"[yellow]{win_rate:.1f}%[/yellow]"
        )
        stats_table.add_row(
            "[cyan]Current P/L[/cyan]",
            f"[green]{self.current_profit:+.2f}[/green]"
            if self.current_profit >= 0
            else f"[red]{self.current_profit:+.2f}[/red]",
        )
        stats_table.add_row(
            "[cyan]Total P/L[/cyan]",
            f"[green]{self.total_profit:+.2f}[/green]"
            if self.total_profit >= 0
            else f"[red]{self.total_profit:+.2f}[/red]",
        )
        stats_table.add_row(
            "[cyan]Consecutive Losses[/cyan]",
            f"[yellow]{self.consecutive_losses}/{config.MAX_CONSECUTIVE_LOSSES}[/yellow]",
        )

        # Combine tables
        combined = Table.grid(padding=1)
        combined.add_row(status_panel)
        combined.add_row(info_table)
        combined.add_row(price_table)
        combined.add_row(stats_table)

        return Panel(
            combined,
            title="[bold cyan]🤖 Quotex 5-Second Digit Bot[/bold cyan]",
            border_style="cyan",
            expand=True,
        )

    async def trading_loop(self) -> None:
        """Main trading loop - runs every 5-second cycle."""
        logger.info("Trading loop started")

        while self.running:
            try:
                # Check connection
                if not self.connected:
                    logger.warning("Not connected, attempting reconnect...")
                    if not await self.connect():
                        await asyncio.sleep(config.RECONNECT_TIMEOUT)
                        continue

                # Wait until second 3 of 5-second cycle
                await self.wait_until_exact_second(
                    target_second=3, tolerance_ms=50
                )

                # Read price at exact second 3
                self.current_price = await self.get_current_price()
                if not self.current_price:
                    logger.warning("No price data")
                    await asyncio.sleep(2)
                    continue

                logger.debug(
                    f"Second 3 - Price: {self.current_price:.5f} | "
                    f"Time: {datetime.utcnow().isoformat()}"
                )

                # Extract current digit
                current_digit = self.extract_digit(self.current_price)

                # Initialize or generate signal
                if self.previous_digit is None:
                    logger.info(
                        f"First sample: digit={current_digit}, price={self.current_price:.5f}"
                    )
                    self.previous_digit = current_digit
                    self.previous_price = self.current_price
                    await asyncio.sleep(2)
                    continue

                # Determine signal
                direction = None
                if current_digit > self.previous_digit:
                    direction = "call"
                    logger.debug(
                        f"Signal: CALL ({self.previous_digit} → {current_digit})"
                    )
                elif current_digit < self.previous_digit:
                    direction = "put"
                    logger.debug(
                        f"Signal: PUT ({self.previous_digit} → {current_digit})"
                    )
                else:
                    logger.debug(
                        f"Signal: SKIP (digit unchanged: {current_digit})"
                    )

                # Check cooldown
                if (
                    config.COOLDOWN_SECONDS > 0
                    and self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES
                ):
                    elapsed = time.time() - self.last_trade_time
                    if elapsed < config.COOLDOWN_SECONDS:
                        logger.info(
                            f"Cooldown active ({elapsed:.0f}s / {config.COOLDOWN_SECONDS}s)"
                        )
                        await asyncio.sleep(2)
                        continue
                    else:
                        self.consecutive_losses = 0

                # Place trade if signal
                if direction:
                    success, trade_id = await self.place_5second_trade(
                        direction, self.current_price
                    )

                    if success:
                        self.last_trade_id = trade_id
                        self.last_trade_time = time.time()
                        self.total_trades += 1

                        # Log pending trade
                        self.log_trade(
                            trade_id,
                            direction,
                            self.current_price,
                            self.previous_digit,
                            current_digit,
                            None,
                            0.0,
                        )

                        # Wait for trade to close
                        await asyncio.sleep(5.5)

                        # Check result
                        if trade_id:
                            is_win, profit = await self.check_trade_result(
                                trade_id
                            )

                            if is_win:
                                self.wins += 1
                                self.consecutive_losses = 0
                                self.current_profit = profit
                                self.total_profit += profit
                                logger.info(f"✓ WIN: +${profit:.2f}")
                            else:
                                self.losses += 1
                                self.consecutive_losses += 1
                                self.current_profit = -config.STAKE
                                self.total_profit -= config.STAKE
                                logger.info(
                                    f"✗ LOSS: -${config.STAKE:.2f} "
                                    f"({self.consecutive_losses}/{config.MAX_CONSECUTIVE_LOSSES})"
                                )

                            # Update balance
                            self.balance = await self.update_balance()

                            # Log result
                            self.log_trade(
                                trade_id,
                                direction,
                                self.current_price,
                                self.previous_digit,
                                current_digit,
                                "WIN" if is_win else "LOSS",
                                profit if is_win else -config.STAKE,
                            )

                        # Check take profit
                        if (
                            config.TAKE_PROFIT > 0
                            and self.total_profit >= config.TAKE_PROFIT
                        ):
                            console.print(
                                f"[green]TAKE PROFIT REACHED: ${self.total_profit:.2f}[/green]"
                            )
                            self.running = False
                            break

                        # Check stop loss
                        if (
                            config.STOP_LOSS > 0
                            and self.total_profit <= -config.STOP_LOSS
                        ):
                            console.print(
                                f"[red]STOP LOSS HIT: ${self.total_profit:.2f}[/red]"
                            )
                            self.running = False
                            break
                else:
                    await asyncio.sleep(2)

                # Update previous digit
                self.previous_digit = current_digit
                self.previous_price = self.current_price

            except Exception as e:
                logger.error(f"Trading loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def dashboard_loop(self) -> None:
        """Display live dashboard."""
        with Live(self.build_dashboard(), refresh_per_second=1, console=console) as live:
            while self.running:
                try:
                    live.update(self.build_dashboard())
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Dashboard error: {e}")
                    await asyncio.sleep(1)

    async def run(self) -> None:
        """Run the bot."""
        if not await self.connect():
            console.print("[red]Failed to connect[/red]")
            return

        self.running = True

        def handle_signal(signum, frame):
            logger.info("Shutdown signal received")
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            await asyncio.gather(
                self.trading_loop(),
                self.dashboard_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        except Exception as e:
            logger.error(f"Bot error: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown bot gracefully."""
        logger.info("Shutting down...")
        self.running = False
        await asyncio.sleep(0.5)
        await self.close()

        # Print final stats
        console.print("\n[cyan]Final Statistics:[/cyan]")
        console.print(f"Total Trades: {self.total_trades}")
        console.print(f"Wins: {self.wins}")
        console.print(f"Losses: {self.losses}")
        if self.total_trades > 0:
            wr = self.wins / self.total_trades * 100
            console.print(f"Win Rate: {wr:.1f}%")
        console.print(f"Total P/L: ${self.total_profit:+.2f}")
        console.print(f"Final Balance: ${self.balance:.2f}")
        logger.info("Shutdown complete")


async def main() -> None:
    """Main entry point."""
    if not config.EMAIL or config.EMAIL == "your-email@example.com":
        console.print("[red]ERROR: Configure email and password in config.py[/red]")
        return

    bot = QuotexDigitBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
