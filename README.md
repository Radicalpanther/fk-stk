# Flipkart Stock Alert Bot

A free, automated stock monitoring bot for Flipkart products that sends Telegram alerts when items come back in stock. Runs on GitHub Actions every 15 minutes.

## Features

- **Multi-product support** - Monitor multiple products from config.json
- **Telegram alerts** - Get notified when stock status changes
- **State persistence** - Only alerts on status changes to avoid spam
- **Failure handling** - Captures screenshots on errors, reports via Telegram
- **GitHub Actions** - Runs every 15 minutes for free
- **Random delay** - Adds 0-60s delay to avoid detection patterns

## Quick Setup

### 1. Create Telegram Bot and Get Chat ID

#### Create a Bot:
1. Open Telegram and search for `@BotFather`
2. Start a chat and send `/newbot`
3. Follow the prompts to name your bot
4. Copy the **Bot Token** (starts with `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

#### Get Your Chat ID:
1. Search for `@userinfobot` in Telegram
2. Start a chat and send `/start`
3. Your **Chat ID** will be displayed (a number like `123456789`)

#### Alternative - Get Group Chat ID:
1. Add your bot to a group
2. Send a message in the group
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Look for `chat":{"id":-123456789,...}` for negative group IDs

### 2. Set Up GitHub Repository

1. Create a new GitHub repository
2. Upload all files from this project
3. Go to **Settings → Secrets and variables → Actions**
4. Add the following secrets:
   - `TELEGRAM_BOT_TOKEN` - Your bot token from BotFather
   - `TELEGRAM_CHAT_ID` - Your numeric chat ID

### 3. Configure Products

Edit `config.json` to add your products:

```json
{
  "pincode": "YOUR_PINCODE",
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID"
  },
  "products": [
    {
      "id": "your-product-id",
      "name": "Product Name",
      "url": "https://www.flipkart.com/p/itm...?pid=YOUR_PID"
    }
  ]
}
```

**Note:** Use only the `pid` parameter from Flipkart URLs. The full URL path after `p/` is optional.

### 4. Test Locally (Optional - Recommended)

Before deploying to GitHub, test locally to verify selectors work:

```bash
# Create virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install

# Run with visible browser (debug mode)
set DEBUG_SCREENSHOT=true
set HEADLESS=false
python scripts/check_stock.py
```

This will:
- Open a visible Chrome browser
- Navigate to the product page
- Enter your pincode and check availability
- Take screenshots for debugging

If selectors need adjustment:
1. Open the page in browser
2. Right-click → Inspect
3. Find the pincode input element
4. Update the selector in `scripts/check_stock.py`

### 5. Test GitHub Actions

1. Push your code to GitHub
2. Go to **Actions** tab
3. Select "Flipkart Stock Alert" workflow
4. Click **Run workflow** → choose branch → **Run workflow**
5. Watch the execution and check for any errors

### 6. Verify Telegram Alerts

- If the product is OUT OF STOCK: You'll receive an "OUT OF STOCK" alert
- If the product is IN STOCK: You'll receive an "IN STOCK" alert
- Subsequent runs will only alert if the status changes

## How It Works

### Stock Detection Logic

1. **Check pincode delivery** - Enters your pincode in the delivery box
2. **Look for IN STOCK signals:**
   - "Add to Cart" button (enabled)
   - "Buy Now" button (enabled)
3. **Look for OUT OF STOCK signals:**
   - "Currently unavailable"
   - "Sold Out"
   - "Notify Me"
   - "not deliverable"
4. **UNKNOWN/ERROR handling:**
   - Saves screenshot to `screenshots/` folder
   - Uploads as GitHub artifact
   - Sends ONE failure report via Telegram (with 1-hour cooldown)

### State Management

- `state.json` tracks the last known status of each product
- Only commits to repo when status actually changes
- Prevents spam alerts for the same status

### GitHub Actions Workflow

- **Schedule:** Every 15 minutes (`*/15 * * * *`)
- **Manual:** You can trigger via **Actions → Run workflow**
- **Browser:** Headless Chromium with en-IN locale
- **Random delay:** 0-60 seconds to avoid patterns

## File Structure

```
fk stk/
├── .github/workflows/
│   └── stock-check.yml      # GitHub Actions workflow
├── scripts/
│   └── check_stock.py       # Main Python script
├── config.json              # Product config (edit this)
├── state.json               # Last known status (auto-generated)
├── requirements.txt         # Python dependencies
├── screenshots/             # Debug screenshots (auto-created)
└── README.md                # This file
```

## Troubleshooting

### Bot Not Sending Messages
- Verify bot_token and chat_id are correct in secrets
- Make sure the bot has been started in chat (send `/start`)
- Check if bot was added to group (for group alerts)

### Captcha or Blocked
- The workflow runs with a random delay to reduce detection
- Consider using a VPN or proxy if Flipkart blocks your IP
- The user agent and headers are designed to appear legitimate

### Pincode Not Found
- Flipkart may have changed their selectors
- Run locally with `HEADLESS=false` to debug
- Update the selectors in `_enter_pincode()` method

### False Negatives
- Try adjusting the wait times in `check_product()`
- Increase `await asyncio.sleep()` values for slower connections

## Cost

- **GitHub Actions:** Free (2000 minutes/month for private repos)
- **Playwright:** Free and open source
- **Telegram Bot:** Free
- **Total cost:** $0

## Customization

### Add More Products

Add to `config.json`:
```json
{
  "products": [
    {
      "id": "product-1",
      "name": "Product 1 Name",
      "url": "https://www.flipkart.com/...pid=..."
    },
    {
      "id": "product-2",
      "name": "Product 2 Name",
      "url": "https://www.flipkart.com/...pid=..."
    }
  ]
}
```

### Change Check Frequency

Edit `.github/workflows/stock-check.yml`:
```yaml
schedule:
  - cron: '*/5 * * * *'  # Every 5 minutes
```

### Add Custom Selectors

Edit the selector lists in `scripts/check_stock.py`:
- `in_stock_selectors` - Elements indicating in-stock
- `out_of_stock_selectors` - Elements indicating out-of-stock
- `out_of_stock_texts` - Text patterns indicating out-of-stock