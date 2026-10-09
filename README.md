# Flipkart Stock Alert Bot

A free, automated stock monitoring bot for Flipkart products that sends Telegram alerts when items come back in stock. Runs on GitHub Actions every 15 minutes.

## Features

- **Delivery location-aware** - Sets delivery address before checking stock
- **False positive protection** - Requires 2 consecutive IN_STOCK detections before alerting
- **Telegram alerts with screenshots** - Get photos showing the actual product page
- **State persistence** - Only alerts on status changes to avoid spam
- **Failure handling** - Captures screenshots on errors, alerts on status transitions
- **GitHub Actions** - Runs every 15 minutes for free
- **Desktop browser profile** - Uses realistic desktop Chromium with en-IN locale

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

### 2. Set Up GitHub Repository

1. Create a new GitHub repository
2. Upload all files from this project
3. Go to **Settings → Secrets and variables → Actions**
4. Add the following secrets:
   - `TELEGRAM_BOT_TOKEN` - Your bot token from BotFather
   - `TELEGRAM_CHAT_ID` - Your numeric chat ID
   - `FK_ADDRESS` - Your full delivery address (e.g., "123 Main St, Pune, Maharashtra")

### 3. Configure Products

Edit `config.json` to add your products:

```json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "chat_id": "YOUR_CHAT_ID_HERE"
  },
  "products": [
    {
      "pid": "COMHHT9GHUHHZXYK",
      "name": "ASUS ExpertBook P5"
    }
  ]
}
```

**Finding the PID:**
- Open the product on Flipkart
- Look for `?pid=XXXXX` in the URL
- Copy only the alphanumeric PID (e.g., `COMHHT9GHUHHZXYK`)

### 4. Test Locally (Optional - Recommended)

```bash
# Create virtual environment
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set environment variables
export FK_ADDRESS="Your full address here"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Run with visible browser
python scripts/check_stock.py --local --headed
```

The `--local` flag prints messages instead of sending them, and `--headed` shows the browser.

### 5. Test GitHub Actions

1. Push your code to GitHub
2. Go to **Actions** tab
3. Select "Flipkart Stock Alert" workflow
4. Click **Run workflow** → choose branch → **Run workflow**
5. Watch the execution and check for any errors

## How It Works

### Stock Detection Logic

1. **Set delivery location** - Opens address flow, enters your address from `FK_ADDRESS`, selects first suggestion
2. **Verify location** - Checks that your city/area appears in the page text
3. **Check OUT OF STOCK signals FIRST** (from visible text):
   - "not deliverable"
   - "currently unavailable"
   - "sold out"
   - "notify me"
   - "cannot be delivered"
4. **Check IN STOCK signals** (enabled, visible buttons only):
   - "Add to Cart" button
   - "Buy Now" button
5. **Require 2 consecutive IN_STOCK results** before sending alert
6. **UNKNOWN/ERROR handling:**
   - Saves full-page screenshot
   - Uploads to GitHub artifacts (3 days retention)
   - Sends ONE alert when status changes into UNKNOWN/ERROR
   - Job exits with error code (shows as red/failed in Actions)

### State Management

- `state.json` tracks:
  - Current status for each product
  - Pending status (for 2-check confirmation)
  - Last checked timestamp
  - Last failure report timestamp
- Only commits to repo when state actually changes
- Prevents spam alerts for the same status

### GitHub Actions Workflow

- **Schedule:** Every 15 minutes (`*/15 * * * *`)
- **Manual:** Trigger via **Actions → Run workflow**
- **Concurrency:** One run at a time (no overlapping jobs)
- **Timeout:** 10 minutes max
- **Browser:** Desktop Chromium, headless, en-IN locale
- **Screenshots:** Always uploaded as artifacts (3 days retention)
- **Exit code:** Non-zero on UNKNOWN/ERROR status

## File Structure

```
fk stk/
├── .github/workflows/
│   └── stock-check.yml      # GitHub Actions workflow
├── scripts/
│   └── check_stock.py       # Main Python script
├── config.json              # Product config (edit this)
├── state.json               # Last known status (auto-managed)
├── requirements.txt         # Python dependencies
├── screenshots/             # Debug screenshots (auto-created)
└── README.md                # This file
```

## Troubleshooting

### Bot Not Sending Messages
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct in secrets
- Make sure the bot has been started in chat (send `/start`)

### Location Not Verified
- Check that `FK_ADDRESS` is set correctly in secrets
- Run locally with `--headed` to see the address entry flow
- Make sure the address gets autocomplete suggestions from Flipkart

### False Positives
- The bot requires 2 consecutive IN_STOCK detections before alerting
- Each check is separated by at least 15 minutes

### Workflow Failing
- Check the Actions tab for error messages
- Download the screenshot artifacts to see what the page looked like
- Look for "Location verified: NO" in the logs

### Invalid PID Error
- Make sure the PID contains only ASCII letters and numbers
- If you copied from browser, check for Greek/Cyrillic lookalike characters
- Try typing the PID manually instead of copying

## Debug Mode

Set `DEBUG_NETWORK=true` environment variable to log network requests containing "state" in the URL:

```bash
export DEBUG_NETWORK=true
python scripts/check_stock.py --local --headed
```

This saves a `network_debug_*.json` file with request details (cookies/tokens stripped).

## Cost

- **GitHub Actions:** Free (2000 minutes/month for private repos, unlimited for public)
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
      "pid": "COMHHT9GHUHHZXYK",
      "name": "ASUS ExpertBook P5"
    },
    {
      "pid": "ANOTHERPRODUCTPID",
      "name": "Another Product"
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

Note: More frequent checks may increase detection risk by Flipkart.
