import os
import telebot
import requests
import json
import time
import re
import threading
from datetime import datetime
from collections import defaultdict

# Railway environment variables
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()

bot = telebot.TeleBot(TOKEN)

message_buffers = defaultdict(list)
timers = {}
buffer_lock = threading.Lock()

# Unified handler to process incoming text from either private chats, groups, or channels
def handle_incoming_content(message_or_post):
    chat_id = message_or_post.chat.id
    text = message_or_post.text or message_or_post.caption or ""
    if not text:
        return
    
    with buffer_lock:
        message_buffers[chat_id].append(text)
        if chat_id in timers:
            timers[chat_id].cancel()
        timers[chat_id] = threading.Timer(4.0, process_accumulated_messages, args=[chat_id])
        timers[chat_id].start()

# 1. Handler for regular messages (Private chats and groups)
@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    handle_incoming_content(message)

# 2. Handler for channel posts (Added to listen to channels)
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
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    structured_data = extract_truck_data(combined_text)
    structured_data["timestamp"] = timestamp
    structured_data["raw_message"] = combined_text

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger response: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")

def extract_truck_data(raw_text):
    data = {
        "company": "Borderlanders Inc",
        "action_type": "PICKUP",
        "driver_status": "Active",
        "driver_type": "Company driver",
        "driver_name": "",
        "is_team_driver": False,
        "unit_number": "",     # Drop Unit
        "pickup_unit": "",     # New Unit
        "vin": "",
        "pickup_vin": "",
        "plate": "",
        "pickup_plate": "",
        "make": "",
        "year": "",
        "truck_type": "Penske Rental",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "Shop"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper or "SWAPPED" in text_upper:
        data["action_type"] = "SWAP"
    elif "TERMINAT" in text_upper:
        data["action_type"] = "TERMINATION"
        data["driver_status"] = "Terminated"
    elif "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
        
    # Location mapping
    if "YARD" in text_upper:
        data["location"] = "Yard"
    elif "SHOP" in text_upper or "REPAIR" in text_upper or "ISSUE" in text_upper or "PENSKE" in text_upper:
        data["location"] = "Shop"
    elif "RETURN" in text_upper:
        data["location"] = "Returned"
    elif "HOME" in text_upper:
        data["location"] = "Home"
    elif "VACATION" in text_upper or "LEAVE" in text_upper:
        data["location"] = "Vacation"
    else:
        if data["action_type"] in ["SWAP", "DROPOFF"]:
            data["location"] = "Shop"
        else:
            data["location"] = "Rolling"

    # Company name extraction
    company_match = re.search(r'Company:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if company_match:
        data["company"] = company_match.group(1).strip()
        
    # Date extraction
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    # Driver name & team check
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        d_name = driver_match.group(1).strip()
        data["driver_name"] = d_name
        if "/" in d_name or "&" in d_name or "TEAM" in d_name.upper():
            data["is_team_driver"] = True
    else:
        alt_name = re.search(r'[-–]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', raw_text)
        if alt_name:
            data["driver_name"] = alt_name.group(1).strip()

    # Split Drop vs Pickup sections
    parts = re.split(r'Pick up unit', raw_text, flags=re.IGNORECASE)
    drop_section = parts[0]
    pickup_section = parts[1] if len(parts) > 1 else ""

    # Drop Unit
    drop_unit_match = re.search(r'(?:Drop off unit|Drop unit|Unit)[:\s#]*([0-9]+)', drop_section, re.IGNORECASE)
    if drop_unit_match:
        data["unit_number"] = drop_unit_match.group(1).strip()

    drop_vin = re.search(r'Vin:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
    if drop_vin:
        data["vin"] = drop_vin.group(1).strip()
    drop_plate = re.search(r'Plate:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
    if drop_plate:
        data["plate"] = drop_plate.group(1).strip()

    # Pickup Unit
    if pickup_section:
        pick_unit_match = re.search(r'[:\s#]*([0-9]+)', pickup_section)
        if pick_unit_match:
            data["pickup_unit"] = pick_unit_match.group(1).strip()

        pick_vin = re.search(r'Vin:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
        if pick_vin:
            data["pickup_vin"] = pick_vin.group(1).strip()
            
        pick_plate = re.search(r'Plate:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
        if pick_plate:
            data["pickup_plate"] = pick_plate.group(1).strip()

        make_match = re.search(r'Make model year:\s*([^\n]+)', pickup_section, re.IGNORECASE)
        if make_match:
            make_val = make_match.group(1).strip()
            data["make"] = make_val
            year_match = re.search(r'(20[0-9]{2})', make_val)
            if year_match:
                data["year"] = year_match.group(1)

    # Truck Type
    text_lower = raw_text.lower()
    if "penske" in text_lower:
        data["truck_type"] = "Penske Rental"
    elif "ryder" in text_lower:
        data["truck_type"] = "Ryder Rental"
    elif "nexgen" in text_lower:
        data["truck_type"] = "Nexgen Rental"
    else:
        data["truck_type"] = "Finance"

    return data

if __name__ == "__main__":
    print("Waiting for old instance to close...")
    time.sleep(3)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse Fleet Bot is running on Railway...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
