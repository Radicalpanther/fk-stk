#!/usr/bin/env python3
"""
Flipkart Stock Alert Bot
Checks product availability and sends Telegram alerts when status changes.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from playwright.async_api import async_playwright, Browser, Page, Playwright

# Type aliases
StockStatus = Literal["IN_STOCK", "OUT_OF_STOCK", "UNKNOWN", "ERROR"]
AlertStatus = Literal["ALERT_SENT", "FAILURE_REPORTED", "NO_CHANGE", "FIRST_RUN"]

# Desktop user agent matching Chromium
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

class FlipkartStockChecker:
    """Main stock checker class using Playwright."""

    def __init__(self, config_path: str = "config.json", state_path: str = "state.json",
                 local_mode: bool = False, headed: bool = False):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.local_mode = local_mode
        self.headed = headed
        self.config = self._load_config()
        self.state = self._load_state()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.debug_network = os.getenv("DEBUG_NETWORK", "false").lower() == "true"
        self.network_logs = []

    def _load_config(self) -> Dict:
        """Load configuration from JSON file, with secrets from environment."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Validate required fields
        required = ["products", "telegram"]
        for field in required:
            if field not in config:
                raise ValueError(f"Missing required config field: {field}")

        # Validate telegram config or read from env
        telegram_config = config["telegram"]
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if bot_token and chat_id:
            telegram_config["bot_token"] = bot_token
            telegram_config["chat_id"] = chat_id
        elif "bot_token" not in telegram_config or "chat_id" not in telegram_config:
            if not self.local_mode:
                raise ValueError("Telegram config must contain 'bot_token' and 'chat_id' (or set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars)")

        # Get address from environment
        config["address"] = os.getenv("FK_ADDRESS", "")
        if not config["address"] and not self.local_mode:
            raise ValueError("FK_ADDRESS environment variable is required")

        return config

    def _load_state(self) -> Dict:
        """Load previous state from JSON file."""
        if not self.state_path.exists():
            return {}

        try:
            with open(self.state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def _save_state(self) -> None:
        """Save current state to JSON file."""
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)

    def _validate_pid(self, pid: str) -> bool:
        """Validate that PID contains only ASCII alphanumeric characters."""
        if not pid:
            return False
        if not re.match(r'^[a-zA-Z0-9]+$', pid):
            print(f"ERROR: Invalid PID '{pid}' - must be ASCII alphanumeric only")
            print("Check for lookalike Greek/Cyrillic characters if copied from browser")
            return False
        return True

    def _build_product_url(self, pid: str) -> str:
        """Build Flipkart product URL from PID."""
        return f"https://www.flipkart.com/product/p/itme?pid={pid}"

    async def _log_network_request(self, route):
        """Log network requests containing 'state' in URL for debugging."""
        url = route.request.url
        if 'state' in url.lower():
            try:
                await route.continue_()
                response = await route.fetch()
                body = await response.text()

                # Strip sensitive data
                log_entry = {
                    "url": url,
                    "method": route.request.method,
                    "status": response.status,
                    "body_preview": body[:500] if body else None,
                    "timestamp": datetime.now().isoformat()
                }
                self.network_logs.append(log_entry)
            except Exception as e:
                print(f"Error logging network request: {e}")
                await route.continue_()
        else:
            await route.continue_()

    async def setup_browser(self) -> None:
        """Initialize Playwright browser with proper settings."""
        self.playwright = await async_playwright().start()

        # Use headless unless in headed mode
        headless = not self.headed and os.getenv("HEADLESS", "true").lower() == "true"

        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )

        # Desktop context with Chromium user agent and en-IN locale
        context = await self.browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="en-IN",
            viewport={"width": 1366, "height": 768},
        )

        self.page = await context.new_page()

        # Set up network logging if debug mode enabled
        if self.debug_network:
            await self.page.route("**/*", self._log_network_request)

        await self.page.set_extra_http_headers({
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        })

    async def close_browser(self) -> None:
        """Clean up browser resources."""
        # Save network logs if debug mode enabled
        if self.debug_network and self.network_logs:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = f"network_debug_{timestamp}.json"
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(self.network_logs, f, indent=2)
            print(f"Network debug log saved: {log_file}")

        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def check_product(self, product: Dict) -> Tuple[StockStatus, Optional[str]]:
        """
        Check a single product's stock status.
        Returns (status, error_message)
        """
        pid = product.get("pid", "")

        # Validate PID
        if not self._validate_pid(pid):
            return "ERROR", f"Invalid PID: {pid}"

        url = self._build_product_url(pid)

        print(f"Checking product: {product.get('name', 'Unknown')}")
        print(f"URL: {url}")

        try:
            # Navigate to product page
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # Verify page loaded
            page_title = await self.page.title()
            if "flipkart" not in page_title.lower():
                print(f"Warning: Page title doesn't look like Flipkart: {page_title}")

            # Determine stock status from visible page text
            status, match_info = await self._determine_stock_status()

            if self.local_mode:
                print(f"Match info: {match_info}")
                print(f"Final status: {status}")

            return status, None

        except Exception as e:
            error_msg = f"Error checking product: {str(e)}"
            print(error_msg)
            return "ERROR", error_msg

    async def _determine_stock_status(self) -> Tuple[StockStatus, str]:
        """
        Determine stock status based on VISIBLE page text only.
        Returns (status, match_info)
        """
        try:
            # Get visible text only
            page_text = await self.page.inner_text("body")
            page_text_lower = page_text.lower()

            # Check OUT OF STOCK signals FIRST (with higher priority)
            out_of_stock_signals = [
                "not available at this pincode",
                "not deliverable",
                "currently unavailable",
                "sold out",
                "notify me",
                "cannot be delivered",
            ]

            for signal in out_of_stock_signals:
                if signal in page_text_lower:
                    return "OUT_OF_STOCK", f"Found text: '{signal}'"

            # Now check IN STOCK: enabled visible Add to Cart or Buy Now button
            in_stock_buttons = [
                'button:has-text("Add to Cart")',
                'button:has-text("ADD TO CART")',
                'button:has-text("Buy Now")',
                'button:has-text("BUY NOW")',
                'button:has-text("Go to Cart")',
                'button:has-text("GO TO CART")',
            ]

            for selector in in_stock_buttons:
                try:
                    button = await self.page.wait_for_selector(selector, timeout=500)
                    if button:
                        is_visible = await button.is_visible()
                        is_disabled = await button.get_attribute("disabled")

                        if is_visible and not is_disabled:
                            button_text = await button.inner_text()
                            return "IN_STOCK", f"Found enabled button: '{button_text}'"
                except:
                    continue

            # If neither found, return UNKNOWN
            return "UNKNOWN", "No clear stock signals found"

        except Exception as e:
            print(f"Error determining stock status: {e}")
            return "ERROR", str(e)

    async def send_telegram_message(self, text: str, photo_path: Optional[str] = None) -> bool:
        """Send plain text message or photo to Telegram."""
        if self.local_mode:
            print(f"[LOCAL MODE] Would send Telegram message:\n{text}")
            return True

        bot_token = self.config["telegram"]["bot_token"]
        chat_id = self.config["telegram"]["chat_id"]

        try:
            import aiohttp

            if photo_path and os.path.exists(photo_path):
                # Send photo with caption
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

                with open(photo_path, 'rb') as photo_file:
                    form = aiohttp.FormData()
                    form.add_field('chat_id', chat_id)
                    form.add_field('caption', text)
                    form.add_field('photo', photo_file, filename='screenshot.png')

                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, data=form) as response:
                            if response.status == 200:
                                print("Telegram photo sent")
                                return True
                            else:
                                error_text = await response.text()
                                print(f"Failed to send photo: {error_text}")
                                return False
            else:
                # Send text message (plain text, no parse_mode)
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            print("Telegram message sent")
                            return True
                        else:
                            error_text = await response.text()
                            print(f"Failed to send message: {error_text}")
                            return False

        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False

    async def save_screenshot(self, product_name: str, status: StockStatus) -> str:
        """Save screenshot for debugging or alerts."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in product_name if c.isalnum() or c in " _-")[:50]
        filename = f"screenshots/{safe_name}_{status}_{timestamp}.png"

        Path("screenshots").mkdir(exist_ok=True)

        await self.page.screenshot(path=filename, full_page=True)
        print(f"Screenshot saved: {filename}")
        return filename

    def _should_send_alert(self, product_id: str, new_status: StockStatus) -> bool:
        """
        Determine if an alert should be sent based on status change.
        Requires 2 consecutive IN_STOCK results before alerting.
        """
        if product_id not in self.state:
            # First run: record silently
            return False

        product_state = self.state[product_id]
        old_status = product_state.get("status")
        pending_status = product_state.get("pending_status")

        # For IN_STOCK: require 2 consecutive identical results
        if new_status == "IN_STOCK":
            if pending_status == "IN_STOCK":
                # Second consecutive IN_STOCK
                if old_status != "IN_STOCK":
                    return True  # Status change confirmed
            # First or mismatched: don't alert yet
            return False

        # For OUT_OF_STOCK: alert immediately on change
        if new_status == "OUT_OF_STOCK" and old_status == "IN_STOCK":
            return True

        return False

    def _should_send_failure_alert(self, product_id: str, new_status: StockStatus) -> bool:
        """Determine if a failure alert should be sent (only on status change into UNKNOWN/ERROR)."""
        if product_id not in self.state:
            return False

        old_status = self.state[product_id].get("status")

        # Send alert only when transitioning INTO unknown/error
        if new_status in ["UNKNOWN", "ERROR"] and old_status not in ["UNKNOWN", "ERROR"]:
            return True

        # Send "recovered" message when transitioning OUT of unknown/error
        if new_status in ["IN_STOCK", "OUT_OF_STOCK"] and old_status in ["UNKNOWN", "ERROR"]:
            return True

        return False

    async def run(self) -> Dict[str, AlertStatus]:
        """Main execution method."""
        print("Starting Flipkart stock check...")

        await self.setup_browser()

        results = {}
        has_error = False

        try:
            for product in self.config["products"]:
                product_id = product.get("pid", "")
                product_name = product.get("name", "Unknown Product")

                # Initialize state for first run
                if product_id not in self.state:
                    self.state[product_id] = {
                        "status": None,
                        "last_checked": None,
                        "name": product_name,
                        "pending_status": None,
                        "pending_count": 0,
                        "last_failure_report": None,
                    }

                # Check stock
                status, error_msg = await self.check_product(product)

                # Save screenshot
                screenshot_path = await self.save_screenshot(product_name, status)

                if self.local_mode:
                    print(f"Screenshot: {screenshot_path}")

                product_state = self.state[product_id]
                old_status = product_state.get("status")
                is_first_run = old_status is None

                # Handle UNKNOWN/ERROR status
                if status in ["UNKNOWN", "ERROR"]:
                    has_error = True

                    # Send failure alert only on status change
                    if self._should_send_failure_alert(product_id, status):
                        if status == "ERROR":
                            message = f"CHECK FAILED\n\n{product_name}\n\nError: {error_msg or 'Unknown error'}"
                        else:
                            message = f"STATUS UNKNOWN\n\n{product_name}\n\nCould not determine stock status"

                        await self.send_telegram_message(message)
                        results[product_id] = "FAILURE_REPORTED"
                    else:
                        results[product_id] = "NO_CHANGE"

                    # Update state
                    product_state["status"] = status
                    product_state["last_checked"] = datetime.now().isoformat()
                    product_state["pending_status"] = None
                    product_state["pending_count"] = 0

                elif status in ["IN_STOCK", "OUT_OF_STOCK"]:
                    # Check if this is first run
                    if is_first_run:
                        print(f"First run for {product_name}, recording status silently")
                        product_state["status"] = status
                        product_state["last_checked"] = datetime.now().isoformat()
                        product_state["pending_status"] = status if status == "IN_STOCK" else None
                        product_state["pending_count"] = 1 if status == "IN_STOCK" else 0
                        results[product_id] = "FIRST_RUN"
                    else:
                        # Handle pending status for IN_STOCK
                        pending_status = product_state.get("pending_status")
                        pending_count = product_state.get("pending_count", 0)

                        if status == "IN_STOCK":
                            if pending_status == "IN_STOCK":
                                # Second consecutive IN_STOCK: confirm and alert if changed
                                if old_status != "IN_STOCK":
                                    message = f"IN STOCK ALERT!\n\n{product_name}\n\nStatus: IN STOCK"
                                    await self.send_telegram_message(message, screenshot_path)
                                    results[product_id] = "ALERT_SENT"
                                else:
                                    results[product_id] = "NO_CHANGE"

                                # Update to IN_STOCK
                                product_state["status"] = "IN_STOCK"
                                product_state["pending_status"] = None
                                product_state["pending_count"] = 0
                            else:
                                # First IN_STOCK: mark as pending
                                print(f"First IN_STOCK for {product_name}, waiting for confirmation")
                                product_state["pending_status"] = "IN_STOCK"
                                product_state["pending_count"] = 1
                                results[product_id] = "NO_CHANGE"
                        else:  # OUT_OF_STOCK
                            # Alert immediately on change
                            if old_status == "IN_STOCK":
                                message = f"OUT OF STOCK\n\n{product_name}\n\nStatus: OUT OF STOCK"
                                await self.send_telegram_message(message, screenshot_path)
                                results[product_id] = "ALERT_SENT"
                            else:
                                results[product_id] = "NO_CHANGE"

                            product_state["status"] = "OUT_OF_STOCK"
                            product_state["pending_status"] = None
                            product_state["pending_count"] = 0

                        # Send "recovered" message if coming from error state
                        if old_status in ["UNKNOWN", "ERROR"]:
                            message = f"CHECK RECOVERED\n\n{product_name}\n\nStatus: {status}"
                            await self.send_telegram_message(message)

                        product_state["last_checked"] = datetime.now().isoformat()

                else:
                    results[product_id] = "NO_CHANGE"

                # Save state after each product
                self._save_state()

                # Small delay between products
                if not self.local_mode:
                    await asyncio.sleep(2)

        finally:
            await self.close_browser()

        # Exit with error if any product had UNKNOWN/ERROR status
        if has_error:
            print("\nERROR: One or more products had UNKNOWN or ERROR status")
            sys.exit(1)

        return results

async def main():
    """Entry point for the script."""
    parser = argparse.ArgumentParser(description="Flipkart Stock Alert Bot")
    parser.add_argument("--local", action="store_true", help="Local test mode (prints instead of sending Telegram)")
    parser.add_argument("--headed", action="store_true", help="Show browser window (non-headless)")
    args = parser.parse_args()

    try:
        checker = FlipkartStockChecker(local_mode=args.local, headed=args.headed)
        results = await checker.run()

        print("\nSummary:")
        for product_id, result in results.items():
            print(f"  {product_id}: {result}")

        sys.exit(0)

    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
