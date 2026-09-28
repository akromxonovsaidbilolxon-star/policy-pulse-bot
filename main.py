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

bot = telebot.TeleBot(TOKEN)

message_buffers = defaultdict(list)
timers = {}
buffer_lock = threading.Lock()

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    if not text:
        return
    
    with buffer_lock:
        message_buffers[chat_id].append(text)
        if chat_id in timers:
            timers[chat_id].cancel()
        timers[chat_id] = threading.Timer(4.0, process_accumulated_messages, args=[chat_id])
        timers[chat_id].start()

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
        "company": "Cargo Prime",
        "action_type": "PICKUP",
        "driver_status": "Active",
        "driver_type": "Company driver",
        "driver_name": "",
        "unit_number": "",     # Drop unit or primary unit
        "pickup_unit": "",     # New unit for swaps
        "vin": "",
        "plate": "",
        "make": "",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": ""
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper or "SWAPPED" in text_upper:
        data["action_type"] = "SWAP"
    elif "TERMINAT" in text_upper:
        data["action_type"] = "TERMINATION"
        data["driver_status"] = "Terminated"
    elif "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
        
    # Extract Date
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    # Extract Driver Name
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()
    else:
        alt_name = re.search(r'[-–]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', raw_text)
        if alt_name:
            data["driver_name"] = alt_name.group(1).strip()
        
    # Extract Drop Unit / Primary Unit
    drop_unit_match = re.search(r'(?:Drop unit|Unit|Drop off unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if drop_unit_match:
        data["unit_number"] = drop_unit_match.group(1).strip()
        
    # Extract Pick up Unit (for Swaps)
    pick_unit_match = re.search(r'Pick up unit[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if pick_unit_match:
        data["pickup_unit"] = pick_unit_match.group(1).strip()
        
    # Extract VIN
    vin_match = re.search(r'Vin:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if vin_match:
        data["vin"] = vin_match.group(1).strip()
            
    # Extract Plate
    plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if plate_match:
        data["plate"] = plate_match.group(1).strip()
        
    # Extract Make
    make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if make_match:
        data["make"] = make_match.group(1).strip()
        
    loc_match = re.search(r'Location:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if loc_match:
        data["location"] = loc_match.group(1).strip()

    return data

if __name__ == "__main__":
    print("Waiting for old instance to close...")
    time.sleep(3)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse Fleet Bot is running with Full Lifecycle & Audit Logging...")
    bot.infinity_polling(skip_pending=True)
