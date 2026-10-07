import os
import telebot
import requests
import json
import time
import re
import threading
import uuid
from datetime import datetime
from collections import defaultdict

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

if not TOKEN:
    print("Error: Missing TELEGRAM_BOT_TOKEN in environment variables.")

bot = telebot.TeleBot(TOKEN)
message_buffers = defaultdict(list)
timers = {}
buffer_lock = threading.Lock()

def handle_incoming_content(message_or_post):
    try:
        chat_id = message_or_post.chat.id
    except AttributeError:
        return
        
    text = getattr(message_or_post, 'text', None) or getattr(message_or_post, 'caption', None) or ""
    if not text:
        return
    
    with buffer_lock:
        message_buffers[chat_id].append(text)
        if chat_id in timers:
            timers[chat_id].cancel()
        timers[chat_id] = threading.Timer(4.0, process_accumulated_messages, args=[chat_id])
        timers[chat_id].start()

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    handle_incoming_content(message)

@bot.channel_post_handler(func=lambda post: True)
def handle_channel_posts(post):
    handle_incoming_content(post)

def process_accumulated_messages(chat_id):
    with buffer_lock:
        texts = message_buffers.pop(chat_id, [])
        if chat_id in timers:
            del timers[chat_id]
            
    if not texts:
        return
        
    combined_text = "\n".join(texts)
    print(f"=== PROCESSING BLOCK ({len(texts)} parts) ===")
    
    transaction_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    structured_data = extract_truck_data(combined_text)
    structured_data["transaction_id"] = transaction_id
    structured_data["timestamp"] = timestamp
    structured_data["raw_message"] = combined_text

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data, timeout=45)
            print(f"Ledger response: {response.text}")
            
            # Send instant Telegram notification if ADMIN_TELEGRAM_ID is configured
            if ADMIN_TELEGRAM_ID:
                try:
                    res_json = response.json()
                    if res_json.get("status") == "success":
                        action = structured_data.get("action_type", "UPDATE")
                        company = structured_data.get("company", "N/A")
                        driver = structured_data.get("driver_name", "N/A")
                        unit = structured_data.get("pickup_unit") or structured_data.get("unit_number") or "N/A"
                        loc = structured_data.get("location", "N/A")
                        
                        notif_text = (
                            f"🚨 *Fleet Ledger Update*\n\n"
                            f"• *Action:* `{action}`\n"
                            f"• *Company:* `{company}`\n"
                            f"• *Driver:* `{driver}`\n"
                            f"• *Unit:* `{unit}`\n"
                            f"• *Location:* `{loc}`\n"
                            f"• *Status:* Successfully Logged ✅"
                        )
                        bot.send_message(ADMIN_TELEGRAM_ID, notif_text, parse_mode="Markdown")
                except Exception as notif_err:
                    print(f"Failed to send Telegram notification: {notif_err}")

        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")
    else:
        print("Warning: GOOGLE_SCRIPT_URL is not set.")

def extract_truck_data(raw_text):
    data = {
        "company": "Pars Transportation",
        "action_type": "PICKUP",
        "driver_status": "",
        "driver_name": "",
        "unit_number": "",
        "vin": "",
        "plate": "",
        "pickup_unit": "",
        "pickup_vin": "",
        "pickup_plate": "",
        "make": "",
        "year": "",
        "truck_type": "Nexgen Rental",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "Shop"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper:
        data["action_type"] = "SWAP"
        data["driver_status"] = ""
    elif "TERMINAT" in text_upper or "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
        data["driver_status"] = "Inactive"
    else:
        data["action_type"] = "PICKUP"
        data["driver_status"] = "Active"
        
    text_lower = raw_text.lower()
    if "returned" in text_lower or "return" in text_lower:
        data["location"] = "Returned"
    elif "yard" in text_lower:
        data["location"] = "Yard"
    elif "shop" in text_lower or "repair" in text_lower or "issue" in text_lower or "fulton" in text_lower or "boulevard" in text_lower:
        data["location"] = "Shop"
    elif "home" in text_lower:
        data["location"] = "Home"
    else:
        data["location"] = "Shop" if data["action_type"] in ["SWAP", "DROPOFF"] else "Rolling"

    company_match = re.search(r'Company:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if company_match:
        data["company"] = company_match.group(1).strip()
        
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, raw_text, re.IGNORECASE) if False else re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()

    if "Pick up unit" in raw_text or data["action_type"] == "SWAP":
        parts = re.split(r'Pick up unit', raw_text, flags=re.IGNORECASE)
        drop_section = parts[0]
        pickup_section = parts[1] if len(parts) > 1 else ""

        drop_unit = re.search(r'(?:Drop unit|Drop off unit|Unit)[:\s#]*([0-9]+)', drop_section, re.IGNORECASE)
        if drop_unit:
            data["unit_number"] = drop_unit.group(1).strip()

        drop_vin = re.search(r'[Vv]in:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_vin:
            data["vin"] = drop_vin.group(1).strip()

        drop_plate = re.search(r'Plate:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_plate:
            data["plate"] = drop_plate.group(1).strip()

        if pickup_section:
            pick_unit = re.search(r'[:\s#]*([0-9]+)', pickup_section)
            if pick_unit:
                data["pickup_unit"] = pick_unit.group(1).strip()

            pick_vin = re.search(r'[Vv]in:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_vin:
                data["pickup_vin"] = pick_vin.group(1).strip()

            pick_plate = re.search(r'Plate:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_plate:
                data["pickup_plate"] = pick_plate.group(1).strip()
    else:
        unit_match = re.search(r'(?:Drop off unit|Drop unit|Pick up unit|Unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
        if unit_match:
            data["pickup_unit"] = unit_match.group(1).strip()
            data["unit_number"] = unit_match.group(1).strip()

        vin_match = re.search(r'[Vv]in:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if vin_match:
            data["pickup_vin"] = vin_match.group(1).strip()
            data["vin"] = vin_match.group(1).strip()

        plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if plate_match:
            data["plate"] = plate_match.group(1).strip()
            data["pickup_plate"] = plate_match.group(1).strip()

    make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if make_match:
        make_val = make_match.group(1).strip()
        data["make"] = make_val
        year_match = re.search(r'(20[0-9]{2})', make_val)
        if year_match:
            data["year"] = year_match.group(1)

    return data

if __name__ == "__main__":
    print("Waiting 8 seconds to ensure old bot instance is dead...")
    time.sleep(8)
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Webhook note: {e}")
        
    print("Policy Pulse Fleet Bot is running on Railway...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Polling error encountered: {e}. Restarting in 5 seconds...")
            time.sleep(5)
