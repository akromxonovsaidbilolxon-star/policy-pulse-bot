import os
import telebot
import requests
import json
import time
import re
import threading
from datetime import datetime
from collections import defaultdict

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()

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
    
    sub_blocks = re.split(r'(?=\[DROPOFF\]|\[PICKUP\]|\[SWAP\])', combined_text, flags=re.IGNORECASE)
    sub_blocks = [b.strip() for b in sub_blocks if b.strip()]
    if not sub_blocks:
        sub_blocks = [combined_text]

    for block in sub_blocks:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        structured_data = extract_truck_data(block)
        structured_data["timestamp"] = timestamp
        structured_data["raw_message"] = block

        if GOOGLE_SCRIPT_URL:
            try:
                # 45-second timeout to prevent Google Apps Script lag drops
                response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data, timeout=45)
                print(f"Ledger response for block: {response.text}")
            except Exception as e:
                print(f"Error posting to Google Sheets: {e}")
        else:
            print("Warning: GOOGLE_SCRIPT_URL is not set.")

def extract_truck_data(raw_text):
    data = {
        "company": "Pars Transportation",
        "action_type": "PICKUP",
        "driver_status": "Active",
        "driver_type": "Company driver",
        "driver_name": "",
        "unit_number": "",
        "pickup_unit": "",
        "vin": "",
        "pickup_vin": "",
        "make": "",
        "year": "",
        "truck_type": "Nexgen Rental",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "Rolling"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper:
        data["action_type"] = "SWAP"
    elif "TERMINAT" in text_upper or "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
        data["driver_status"] = "Terminated"
    else:
        data["action_type"] = "PICKUP"
        
    text_lower = raw_text.lower()
    if "returned" in text_lower or "return" in text_lower:
        data["location"] = "Returned"
    elif "yard" in text_lower:
        data["location"] = "Yard"
    elif "shop" in text_lower or "repair" in text_lower or "issue" in text_lower:
        data["location"] = "Shop"
    elif "home" in text_lower:
        data["location"] = "Home"
    else:
        data["location"] = "Shop" if data["action_type"] in ["SWAP", "DROPOFF"] else "Rolling"

    company_match = re.search(r'Company:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if company_match:
        comp_val = company_match.group(1).strip()
        data["company"] = comp_val
        
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()

    unit_match = re.search(r'(?:Drop off unit|Drop unit|Pick up unit|Unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if unit_match:
        data["pickup_unit"] = unit_match.group(1).strip()
        data["unit_number"] = unit_match.group(1).strip()

    vin_match = re.search(r'[Vv]in:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if vin_match:
        data["pickup_vin"] = vin_match.group(1).strip()
        data["vin"] = vin_match.group(1).strip()

    make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if make_match:
        make_val = make_match.group(1).strip()
        data["make"] = make_val
        year_match = re.search(r'(20[0-9]{2})', make_val)
        if year_match:
            data["year"] = year_match.group(1)

    return data

if __name__ == "__main__":
    print("Waiting 5 seconds to ensure old bot instance is dead...")
    time.sleep(5)
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
