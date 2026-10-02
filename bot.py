import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

# Diagnostic check for Railway logs
missing_vars = []
if not TELEGRAM_BOT_TOKEN:
    missing_vars.append("TELEGRAM_BOT_TOKEN")
if not GEMINI_API_KEY:
    missing_vars.append("GEMINI_API_KEY")
if not APPS_SCRIPT_URL:
    missing_vars.append("APPS_SCRIPT_URL")

if missing_vars:
    logger.error(f"FATAL: Missing environment variables: {', '.join(missing_vars)}")
    raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are a data extraction bot for trucking fleet management and driver compliance.
Parse the incoming raw message into structured JSON with these keys:
- event_type: ("ASSIGNMENT", "EQUIPMENT_SWAP", "NEW_DRIVER", "TERMINATION", or "OTHER")
- carrier: ("Cargo Prime", "Borderlanders", "Supreme", "Successor", etc. Default to "Cargo Prime" if not specified)
- driver_name: Driver's full name, or null
- equipment_id: Unit / Truck number (e.g. "3401", "TR-102"), or null
- trailer_number: Trailer number if mentioned, or null
- vin: Last 6 digits or full VIN if mentioned, or null
- action_type: ("SWAP", "PICKUP", "DROPOFF", or null)
- notes: Brief summary of the update

Output MUST be strictly valid JSON matching this schema:
{
  "event_type": "...",
  "carrier": "...",
  "driver_name": "...",
  "equipment_id": "...",
  "trailer_number": "...",
  "vin": "...",
  "action_type": "...",
  "notes": "..."
}
"""

def parse_message_with_gemini(raw_text: str) -> dict:
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=raw_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1,
            )
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Error calling Gemini: {e}")
        return {
            "event_type": "OTHER",
            "notes": "Failed to parse automatically"
        }

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    raw_text = msg.text
    chat_title = update.effective_chat.title if update.effective_chat else "Direct Message"
    logger.info(f"Processing message from [{chat_title}]: {raw_text[:60]}...")

    # 1. Parse text using Gemini
    data = parse_message_with_gemini(raw_text)
    data["raw_text"] = raw_text
    data["channel_name"] = chat_title

    # 2. Push to Google Sheets via Apps Script Webhook
    try:
        res = requests.post(APPS_SCRIPT_URL, json=data, timeout=12)
        if res.status_code == 200:
            logger.info("Successfully synced to Google Sheets!")
        else:
            logger.warning(f"Apps Script responded with HTTP {res.status_code}: {res.text}")
    except Exception as e:
        logger.error(f"Failed to post to Google Apps Script: {e}")

def main():
    logger.info("Starting Telegram Bot Application...")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Catch all non-command text messages
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Bot is active and polling for updates...")
    app.run_polling()

if __name__ == "__main__":
    main()
