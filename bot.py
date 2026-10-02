import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are a data extraction assistant for fleet management and driver compliance updates.
Extract the structured entity details from the message:
- event_type: (e.g., "TRUCK_SWAP", "NEW_DRIVER", "TERMINATION", "EQUIPMENT_PICKUP", "EQUIPMENT_DROPOFF", "OTHER")
- driver_name: Full name if mentioned, else null
- equipment_id: Truck number, trailer number, or VIN if mentioned, else null
- notes: Any extra key context or summary details

Respond strictly in valid JSON matching this schema:
{
  "event_type": string,
  "driver_name": string or null,
  "equipment_id": string or null,
  "notes": string
}
"""

def parse_with_gemini(text: str) -> dict:
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1,
            )
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Gemini parsing failed: {e}")
        return {
            "event_type": "UNKNOWN",
            "driver_name": None,
            "equipment_id": None,
            "notes": "Parsing failed"
        }

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    raw_text = message.text
    logger.info(f"Received message: {raw_text[:50]}...")

    # Step 1: Parse entities with Gemini
    parsed_data = parse_with_gemini(raw_text)
    parsed_data["raw_text"] = raw_text

    # Step 2: Push to Google Sheets via Apps Script Webhook
    try:
        res = requests.post(APPS_SCRIPT_URL, json=parsed_data, timeout=10)
        if res.status_code == 200:
            logger.info("Successfully synced row to Google Sheets.")
        else:
            logger.error(f"Apps Script error ({res.status_code}): {res.text}")
    except Exception as e:
        logger.error(f"Failed to post to Apps Script: {e}")

def main():
    if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, APPS_SCRIPT_URL]):
        raise ValueError("Missing one or more required environment variables.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Listen to text messages from direct chats, groups, or channels where the bot is added
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
