import os
import re
import json
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Your Google Apps Script Web App URL


def parse_truck_message(text: str) -> dict:
    """
    Parses incoming dispatch/swap text messages for truck and driver details.
    """
    data = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_message": text,
        "company": "Borderlanders Inc",
        "action_type": "PICKUP",
        "driver_name": "",
        "unit_number": "",
        "pickup_unit": "",
        "vin": "",
        "pickup_vin": "",
        "plate": "",
        "pickup_plate": "",
        "truck_type": "Penske Rental",
        "location": "Shop"
    }

    # Detect company mentions
    if re.search(r"cargo\s*prime", text, re.IGNORECASE):
        data["company"] = "Cargo Prime"
    elif re.search(r"supreme", text, re.IGNORECASE):
        data["company"] = "Supreme"
    elif re.search(r"successor", text, re.IGNORECASE):
        data["company"] = "Successor Inc"
    elif re.search(r"borderlanders", text, re.IGNORECASE):
        data["company"] = "Borderlanders Inc"

    # Detect action: Drop, Termination, Swap, or Pickup
    if re.search(r"\b(drop|dropped|termination|return|returned)\b", text, re.IGNORECASE):
        data["action_type"] = "DROP"
    else:
        data["action_type"] = "PICKUP"

    # Extract Drivers (e.g., "Driver: John Doe / Jane Doe" or "Drivers - Name & Name")
    driver_match = re.search(r"(?:driver|drivers)[\s\:\-]+([^\n\r]+)", text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()

    # Extract dropped / old unit number (e.g., "Drop unit: 27014" or "Dropped: 27014")
    drop_match = re.search(r"(?:drop(?:ped)?(?:\s*unit)?|old(?:\s*unit)?|returning)[\s\:\#\-]*([0-9A-Za-z]+)", text, re.IGNORECASE)
    if drop_match:
        data["unit_number"] = drop_match.group(1).strip()

    # Extract pickup / new unit number (e.g., "Pickup unit: 27012" or "New unit: 27012")
    pickup_match = re.search(r"(?:pickup(?:\s*unit)?|new(?:\s*unit)?|picking\s*up)[\s\:\#\-]*([0-9A-Za-z]+)", text, re.IGNORECASE)
    if pickup_match:
        data["pickup_unit"] = pickup_match.group(1).strip()

    # Fallback: If no explicit pickup/drop keywords exist, extract standalone unit numbers
    if not data["unit_number"] and not data["pickup_unit"]:
        units = re.findall(r"\b(27\d{3}|\d{4,6})\b", text)
        if len(units) == 1:
            if data["action_type"] == "DROP":
                data["unit_number"] = units[0]
            else:
                data["pickup_unit"] = units[0]
        elif len(units) >= 2:
            data["unit_number"] = units[0]
            data["pickup_unit"] = units[1]

    # Extract VIN (17 alphanumeric characters)
    vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", text)
    if len(vins) == 1:
        data["vin"] = vins[0]
    elif len(vins) >= 2:
        data["vin"] = vins[0]
        data["pickup_vin"] = vins[1]

    # Extract License Plates (e.g., "Plate: ABC1234")
    plates = re.findall(r"(?:plate|tag)[\s\:\#\-]*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
    if plates:
        data["plate"] = plates[0].strip()

    return data


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Listens for messages in Telegram, formats the data, and posts it to Google Apps Script.
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text
    logger.info(f"Incoming message: {text}")

    # Parse payload
    payload = parse_truck_message(text)

    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL is not configured in environment variables.")
        await update.message.reply_text("Error: Google Apps Script Webhook URL is missing.")
        return

    try:
        # Send payload to Google Apps Script doPost endpoint
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15
        )

        logger.info(f"Apps Script Response: {response.status_code} - {response.text}")
        
        reply_msg = (
            f"Logged to Sheets:\n"
            f"• Action: {payload['action_type']}\n"
            f"• Drop Unit: {payload['unit_number'] or 'None'}\n"
            f"• Pickup Unit: {payload['pickup_unit'] or 'None'}\n"
            f"• Drivers: {payload['driver_name'] or 'N/A'}"
        )
        await update.message.reply_text(reply_msg)

    except Exception as e:
        logger.error(f"Failed to post to Google Sheets: {e}")
        await update.message.reply_text(f"Error syncing with Sheets: {str(e)}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Bot started and listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
