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
    
    # Extract data using robust logistics regex patterns for Swaps, Drops, and Pickups
    structured_data = extract_truck_data(combined_text)
    structured_data["timestamp"] = timestamp

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
        "driver_name": "",
        "unit_number": "",     # Drop unit
        "pickup_unit": "",     # New pickup unit
        "pickup_vin": "",
        "pickup_plate": "",
        "pickup_make": "",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "",
        "notes": f"Telegram - {raw_text[:100]}"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper:
        data["action_type"] = "SWAP"
    elif "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
    elif "SHOP" in text_upper:
        data["action_type"] = "SHOP"
    elif "RETURN" in text_upper:
        data["action_type"] = "RETURNED"
        
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
        
    # Extract Drop Unit
    drop_unit_match = re.search(r'(?:Drop unit|Unit|Drop off unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if drop_unit_match:
        data["unit_number"] = drop_unit_match.group(1).strip()
        
    # Extract Pick up Unit
    pick_unit_match = re.search(r'Pick up unit[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if pick_unit_match:
        data["pickup_unit"] = pick_unit_match.group(1).strip()
        
    # Extract Pick up VIN
    pick_vin_match = re.search(r'Pick up unit.*?Vin:\s*([A-Z0-9]+)', raw_text, re.DOTALL | re.IGNORECASE)
    if pick_vin_match:
        data["pickup_vin"] = pick_vin_match.group(1).strip()
    else:
        vins = re.findall(r'Vin:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if len(vins) > 1:
            data["pickup_vin"] = vins[1]
        elif len(vins) == 1:
            data["pickup_vin"] = vins[0]
            
    # Extract Pick up Plate
    plates = re.findall(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if len(plates) > 1:
        data["pickup_plate"] = plates[1]
    elif len(plates) == 1:
        data["pickup_plate"] = plates[0]
        
    # Extract Pick up Make
    makes = re.findall(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if len(makes) > 1:
        data["pickup_make"] = makes[1]
    elif len(makes) == 1:
        data["pickup_make"] = makes[0]
        
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
        
    print("Policy Pulse Fleet Bot is running with SWAP intelligence...")
    bot.infinity_polling(skip_pending=True)
