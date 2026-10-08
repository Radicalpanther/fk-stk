#!/usr/bin/env python3
"""
Flipkart Stock Alert Bot
Checks product availability and sends Telegram alerts when status changes.
"""

import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from playwright.async_api import async_playwright, Browser, Page, Playwright

# Type aliases
StockStatus = Literal["IN_STOCK", "OUT_OF_STOCK", "UNKNOWN", "ERROR"]
AlertStatus = Literal["ALERT_SENT", "FAILURE_REPORTED", "NO_CHANGE"]

# Default user agent for realistic desktop browsing
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

class FlipkartStockChecker:
    """Main stock checker class using Playwright."""

    def __init__(self, config_path: str = "config.json", state_path: str = "state.json"):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.config = self._load_config()
        self.state = self._load_state()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def _load_config(self) -> Dict:
        """Load configuration from JSON file, with secrets from environment."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Validate required fields
        required = ["products", "pincode", "telegram"]
        for field in required:
            if field not in config:
                raise ValueError(f"Missing required config field: {field}")

        # Validate telegram config or read from env
        telegram_config = config["telegram"]
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if bot_token and chat_id:
            # Use environment variables if present (GitHub Secrets)
            telegram_config["bot_token"] = bot_token
            telegram_config["chat_id"] = chat_id
        elif "bot_token" not in telegram_config or "chat_id" not in telegram_config:
            raise ValueError("Telegram config must contain 'bot_token' and 'chat_id' (or set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars)")

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

    async def setup_browser(self) -> None:
        """Initialize Playwright browser with proper settings."""
        self.playwright = await async_playwright().start()

        # Launch Chromium with realistic settings
        self.browser = await self.playwright.chromium.launch(
            headless=os.getenv("HEADLESS", "true").lower() == "true",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )

        # Create new context with MOBILE user agent for simpler page layout
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            locale="en-IN",
            viewport={"width": 390, "height": 844},
        )

        # Block unnecessary resources to speed up loading (commented out - may cause crashes)
        # await context.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot}", lambda route: route.abort())

        self.page = await context.new_page()

        # Set extra headers to appear more like a real browser
        await self.page.set_extra_http_headers({
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        })

    async def close_browser(self) -> None:
        """Clean up browser resources."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def check_product(self, product: Dict) -> Tuple[StockStatus, Optional[str]]:
        """
        Check a single product's stock status.
        Returns (status, error_message)
        """
        # Build URL with pincode parameter instead of using input
        url = product.get("url", "")
        pincode = self.config.get("pincode", "")

        # DON'T append pincode to URL - causes Flipkart E002 error
        # Use the original URL and enter pincode via UI

        if not url:
            return "ERROR", "No URL provided in product config"

        print(f"Checking product: {product.get('name', 'Unknown')}")
        print(f"URL: {url}")

        try:
            # Navigate to product page with location embedded
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # Wait for initial load

            # Check if page loaded correctly (look for product title or 404)
            page_title = await self.page.title()
            if "flipkart" not in page_title.lower() and "404" not in page_title.lower():
                print(f"Warning: Page title doesn't look like Flipkart: {page_title}")

            # For mobile layout, check stock status directly without pincode entry
            # (Flipkart mobile shows availability upfront)
            status = await self._determine_stock_status()

            # If status is unknown, try pincode entry as fallback
            if status == "UNKNOWN":
                print("Direct check was UNKNOWN, trying pincode entry...")
                pincode_entered = await self._enter_pincode(pincode)
                if pincode_entered:
                    await asyncio.sleep(3)
                    status = await self._determine_stock_status()

            print(f"Status determined: {status}")
            return status, None

        except Exception as e:
            error_msg = f"Error checking product: {str(e)}"
            print(error_msg)
            return "ERROR", error_msg

    async def _enter_pincode(self, pincode: str) -> bool:
        """Find pincode input field, fill it, and click check button."""
        try:
            # Wait a bit longer for the page to fully load
            await asyncio.sleep(3)

            # First, check for a "Check Delivery" or "Check Availability" button.
            # Sometimes the pincode input is hidden until you click a button.
            delivery_button_selectors = [
                'button:has-text("Check Delivery")',
                'button:has-text("CHECK DELIVERY")',
                'button:has-text("Check Availability")',
                'button:has-text("CHECK AVAILABILITY")',
                'button:has-text("Check")',
                'button:has-text("CHECK")',
                'button:has-text("Enter Delivery Pincode")',
                'button:has-text("Enter your pincode")',
                'span:has-text("Check Delivery")',
                'span:has-text("Check")',
                'div[class*="delivery"] button',
                'div[class*="pincode"] button',
            ]

            for btn_selector in delivery_button_selectors:
                try:
                    btn = await self.page.wait_for_selector(btn_selector, timeout=2000)
                    if btn:
                        await btn.click()
                        print(f"Clicked delivery button: {btn_selector}")
                        await asyncio.sleep(1)
                        break
                except:
                    continue

            # Look for pincode input (multiple possible selectors)
            # Note: The last generic selector ('input[type="text"]:visible')
            # is removed from the top of the list because it often matches the
            # search bar instead of the delivery pincode field.
            pincode_selectors = [
                'input[placeholder*="Enter Delivery Pincode"]',
                'input[placeholder*="Delivery Pincode"]',
                'input[placeholder*="enter delivery pincode"]',
                'input[placeholder*="PIN Code"]',
                'input[placeholder*="Pin Code"]',
                'input[placeholder*="pin code"]',
                'input[placeholder*="pin"]',
                'input[placeholder*="PIN"]',
                'input[placeholder*="Pincode"]',
                'input[placeholder*="pincode"]',
                'input[name*="pincode"]',
                'input[name*="pincodeInputId"]',
                'input[name*="delivery_pincode"]',
                'input[name*="delivery"]',
                'input[id*="pincode"]',
                'input[id*="pincodeInputId"]',
                'input[data-id*="pincode"]',
                'input[data-testid*="pincode"]',
                'input[class*="pincode"]',
                'input[type="text"][name*="pin"]',
                'input[type="text"][name*="delivery"]',
                'div[class*="delivery"] input[type="text"]',
                'div[class*="pincode"] input',
                'div[class*="pincode-delivery"] input',
                'form input[type="text"]',
                # Only use the generic visible text input if none of the above worked
            ]

            for selector in pincode_selectors:
                try:
                    pincode_input = await self.page.wait_for_selector(selector, timeout=2000)
                    if pincode_input:
                        # Check if visible and enabled
                        is_visible = await pincode_input.is_visible()
                        is_enabled = await pincode_input.is_enabled()

                        if not is_visible or not is_enabled:
                            continue

                        await pincode_input.click()
                        await asyncio.sleep(0.5)
                        await pincode_input.fill(pincode)
                        print(f"Filled pincode: {pincode} using selector: {selector[:50]}")

                        # Look for check button near the input
                        check_button_selectors = [
                            'button:has-text("Check")',
                            'button:has-text("CHECK")',
                            'span:has-text("Check")',
                            'button[type="submit"]',
                            'button[class*="check"]',
                            'button[class*="Check"]',
                        ]

                        for btn_selector in check_button_selectors:
                            try:
                                check_button = await self.page.wait_for_selector(btn_selector, timeout=2000)
                                if check_button:
                                    await check_button.click()
                                    print("Clicked check button")
                                    return True
                            except:
                                continue

                        # If no check button found, try pressing Enter
                        await pincode_input.press("Enter")
                        print("Pressed Enter for pincode")
                        return True
                except:
                    continue

            # If we didn't find it, print page content for debugging
            page_content = await self.page.content()
            print("Pincode input not found! Looking for known patterns...")

            # Look for pincode text in page content
            import re
            pincode_patterns = [
                r'pincode[^>]*>',
                r'PIN[^>]*>',
                r'delivery[^>]*>',
                r'check.*delivery',
                r'enter.*pin',
            ]

            for pattern in pincode_patterns:
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                if matches:
                    print(f"Found pattern '{pattern}' in page")

            # Save full HTML for manual inspection
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page_content)
            print("Saved full page HTML to debug_page.html")

            return False

        except Exception as e:
            print(f"Error entering pincode: {e}")
            return False

    async def _determine_stock_status(self) -> StockStatus:
        """Determine stock status based on page content."""
        try:
            # Wait a bit more for any dynamic content
            await asyncio.sleep(2)

            # Take screenshot for debugging if needed
            if os.getenv("DEBUG_SCREENSHOT", "false").lower() == "true":
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await self.page.screenshot(path=f"debug_{timestamp}.png")

            # First extract all text from the page
            page_text = await self.page.content()
            page_text_lower = page_text.lower()

            # Check for IN STOCK text signals
            in_stock_texts = [
                "add to cart",
                "buy now",
                "add to basket"
            ]

            for text in in_stock_texts:
                if text in page_text_lower:
                    return "IN_STOCK"

            # Check for IN STOCK selectors
            in_stock_selectors = [
                'button:has-text("Add to Cart")',
                'button:has-text("ADD TO CART")',
                'button:has-text("Buy Now")',
                'button:has-text("BUY NOW")',
                'button[class*="add-to-cart"]',
                'button[class*="buy-now"]',
                '//button[contains(text(), "Add to Cart")]',
                '//button[contains(text(), "Buy Now")]',
                'div[class*="cart"]',
                'li:has-text("Add to Cart")',
                'li:has-text("Buy Now")',
                'li button',
            ]

            for selector in in_stock_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=1000)
                    if element:
                        # Check if button is enabled
                        is_disabled = await element.get_attribute("disabled")
                        if not is_disabled:
                            return "IN_STOCK"
                except:
                    continue

            # Check for OUT OF STOCK signals
            out_of_stock_texts = [
                "Currently unavailable",
                "Sold Out",
                "SOLD OUT",
                "Notify Me",
                "NOTIFY ME",
                "Out of Stock",
                "OUT OF STOCK",
                "not deliverable",
                "not available",
                "Cannot be delivered",
            ]

            page_text = await self.page.content()
            page_text_lower = page_text.lower()

            for text in out_of_stock_texts:
                if text.lower() in page_text_lower:
                    return "OUT_OF_STOCK"

            # Check for specific out-of-stock elements
            out_of_stock_selectors = [
                'button:has-text("Notify Me")',
                'button:has-text("NOTIFY ME")',
                'div[class*="out-of-stock"]',
                'div[class*="sold-out"]',
                'span[class*="out-of-stock"]',
            ]

            for selector in out_of_stock_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=1000)
                    if element:
                        return "OUT_OF_STOCK"
                except:
                    continue

            # If we get here, we couldn't determine status
            return "UNKNOWN"

        except Exception as e:
            print(f"Error determining stock status: {e}")
            return "ERROR"

    async def send_telegram_alert(self, product: Dict, status: StockStatus, previous_status: Optional[str] = None) -> bool:
        """Send Telegram alert if status changed."""
        if status not in ["IN_STOCK", "OUT_OF_STOCK"]:
            return False

        # Only alert if status changed
        product_id = product.get("id", product.get("url", ""))
        if product_id in self.state and self.state[product_id].get("status") == status:
            print(f"No status change for {product.get('name')}, skipping alert")
            return False

        bot_token = self.config["telegram"]["bot_token"]
        chat_id = self.config["telegram"]["chat_id"]

        product_name = product.get("name", "Unknown Product")
        product_url = product.get("url", "")

        if status == "IN_STOCK":
            message = f"✅ IN STOCK ALERT!\n\n{product_name}\nis now IN STOCK!\n\n{product_url}"
        else:  # OUT_OF_STOCK
            message = f"❌ OUT OF STOCK\n\n{product_name}\nis now OUT OF STOCK.\n\n{product_url}"

        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        print(f"Telegram alert sent: {status}")
                        return True
                    else:
                        error_text = await response.text()
                        print(f"Failed to send Telegram alert: {error_text}")
                        return False

        except Exception as e:
            print(f"Error sending Telegram alert: {e}")
            return False

    async def save_debug_screenshot(self, product_name: str, status: StockStatus) -> str:
        """Save screenshot for debugging unknown/error states."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in product_name if c.isalnum() or c in " _-")[:50]
        filename = f"screenshots/{safe_name}_{status}_{timestamp}.png"

        # Create screenshots directory if it doesn't exist
        Path("screenshots").mkdir(exist_ok=True)

        await self.page.screenshot(path=filename)
        print(f"Debug screenshot saved: {filename}")
        return filename

    async def send_failure_report(self, product: Dict, error_msg: str, screenshot_path: Optional[str] = None) -> bool:
        """Send failure report to Telegram."""
        product_id = product.get("id", product.get("url", ""))

        # Check if we already reported this failure recently
        if product_id in self.state:
            last_report = self.state[product_id].get("last_failure_report")
            if last_report and (datetime.now() - datetime.fromisoformat(last_report)).total_seconds() < 3600:  # 1 hour cooldown
                print("Failure already reported recently, skipping")
                return False

        bot_token = self.config["telegram"]["bot_token"]
        chat_id = self.config["telegram"]["chat_id"]

        product_name = product.get("name", "Unknown Product")

        message = f"⚠️ CHECK FAILED\n\n{product_name}\n\nError: {error_msg}"

        if screenshot_path and os.path.exists(screenshot_path):
            message += f"\n\nScreenshot saved: {screenshot_path}"

        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        print("Failure report sent to Telegram")

                        # Update failure report timestamp
                        if product_id not in self.state:
                            self.state[product_id] = {}
                        self.state[product_id]["last_failure_report"] = datetime.now().isoformat()
                        self._save_state()

                        return True
                    else:
                        error_text = await response.text()
                        print(f"Failed to send failure report: {error_text}")
                        return False

        except Exception as e:
            print(f"Error sending failure report: {e}")
            return False

    async def run(self) -> Dict[str, AlertStatus]:
        """Main execution method."""
        print("Starting Flipkart stock check...")

        # Add random delay (0-60 seconds) to avoid patterns
        delay = random.randint(0, 60)
        print(f"Random delay: {delay} seconds")
        await asyncio.sleep(delay)

        await self.setup_browser()

        results = {}

        try:
            for product in self.config["products"]:
                product_id = product.get("id", product.get("url", ""))
                product_name = product.get("name", "Unknown Product")

                # Check stock
                status, error_msg = await self.check_product(product)

                if status in ["ERROR", "UNKNOWN"]:
                    # Save debug screenshot
                    screenshot_path = None
                    if self.page:
                        screenshot_path = await self.save_debug_screenshot(product_name, status)

                    # Send failure report (with cooldown)
                    report_sent = await self.send_failure_report(product, error_msg or "Unknown status", screenshot_path)
                    results[product_id] = "FAILURE_REPORTED" if report_sent else "NO_CHANGE"

                elif status in ["IN_STOCK", "OUT_OF_STOCK"]:
                    # Send alert if status changed
                    previous_status = None
                    if product_id in self.state:
                        previous_status = self.state[product_id].get("status")

                    alert_sent = await self.send_telegram_alert(product, status, previous_status)

                    # Update state
                    if product_id not in self.state:
                        self.state[product_id] = {}

                    old_status = self.state[product_id].get("status")
                    self.state[product_id].update({
                        "status": status,
                        "last_checked": datetime.now().isoformat(),
                        "name": product_name,
                    })

                    # Only save state if it changed
                    if old_status != status:
                        self._save_state()
                        print(f"State updated for {product_name}: {old_status} -> {status}")

                    results[product_id] = "ALERT_SENT" if alert_sent else "NO_CHANGE"

                else:
                    results[product_id] = "NO_CHANGE"

                # Small delay between products
                await asyncio.sleep(2)

        finally:
            await self.close_browser()

        return results

async def main():
    """Entry point for the script."""
    try:
        checker = FlipkartStockChecker()
        results = await checker.run()

        print("\nSummary:")
        for product_id, result in results.items():
            print(f"  {product_id}: {result}")

        # Exit with appropriate code
        if any(status == "FAILURE_REPORTED" for status in results.values()):
            sys.exit(1)
        else:
            sys.exit(0)

    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())