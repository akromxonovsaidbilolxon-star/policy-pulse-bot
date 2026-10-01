import os
import re
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")


def parse_message(text: str) -> dict:
    data = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_message": text,
        "company": "Cargo Prime",
        "action_type": "PICKUP",
        "driver_name": "",
        "unit_number": "",
        "pickup_unit": "",
        "vin": "",
        "pickup_vin": "",
        "plate": "",
        "truck_type": "Penske Rental",
        "location": "Shop"
    }

    if re.search(r"borderlanders", text, re.IGNORECASE):
        data["company"] = "Borderlanders Inc"
    elif re.search(r"supreme", text, re.IGNORECASE):
        data["company"] = "Supreme"
    elif re.search(r"successor", text, re.IGNORECASE):
        data["company"] = "Successor Inc"
    elif re.search(r"cargo\s*prime", text, re.IGNORECASE):
        data["company"] = "Cargo Prime"

    if re.search(r"\b(drop|dropped|termination|returned|return)\b", text, re.IGNORECASE):
        data["action_type"] = "DROP"
    else:
        data["action_type"] = "PICKUP"

    driver_match = re.search(r"(?:driver|drivers)[\s\:\-]+([^\n\r]+)", text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()

    drop_match = re.search(r"(?:drop(?:ped)?(?:\s*unit)?|old(?:\s*unit)?|returning)[\s\:\#\-]*([0-9A-Za-z]+)", text, re.IGNORECASE)
    if drop_match:
        data["unit_number"] = drop_match.group(1).strip()

    pickup_match = re.search(r"(?:pickup(?:\s*unit)?|new(?:\s*unit)?|picking\s*up)[\s\:\#\-]*([0-9A-Za-z]+)", text, re.IGNORECASE)
    if pickup_match:
        data["pickup_unit"] = pickup_match.group(1).strip()

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

    vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", text)
    if len(vins) >= 1:
        data["vin"] = vins[0]
    if len(vins) >= 2:
        data["pickup_vin"] = vins[1]

    return data


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    logger.info(f"Incoming: {text}")

    payload = parse_message(text)

    if not WEBHOOK_URL:
        await update.message.reply_text("Error: WEBHOOK_URL is not set.")
        return

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        logger.info(f"Response: {response.text}")

        res_data = response.json() if response.status_code == 200 else {}
        status_text = res_data.get("status", "processed")

        reply = (
            f"Updated in Sheets ({status_text}):\n"
            f"• Action: {payload['action_type']}\n"
            f"• Dropped Unit: {payload['unit_number'] or 'None'}\n"
            f"• Pickup Unit: {payload['pickup_unit'] or 'None'}\n"
            f"• Drivers: {payload['driver_name'] or 'None'}"
        )
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Error syncing with Sheets: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Bot started and listening...")
    app.run_polling()


if __name__ == "__main__":
    main()
