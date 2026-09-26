import os
import telebot
import requests
import json
import time
import re
import threading
from datetime import datetime
from google import genai
from collections import defaultdict

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

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
    
    # Extract data via AI, with built-in fallback if quota hits 429
    structured_data = extract_truck_data_with_ai(combined_text)
    structured_data["timestamp"] = timestamp

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger response: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")

def extract_truck_data_with_ai(raw_text):
    # Smart Regex Fallback extractor (works instantly even if AI hits quota limits)
    fallback_data = {
        "company": "Borderlanders Inc",
        "driver_status": "Active",
        "driver_type": "Company driver",
        "driver_name": "",
        "truck_status": "Active",
        "plate": "",
        "state": "",
        "unit_number": "",
        "make": "",
        "year": "",
        "vin": ""
    }
    
    # Extract Driver Name
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        fallback_data["driver_name"] = driver_match.group(1).strip()
        
    # Extract Unit / Drop off unit
    unit_match = re.search(r'(?:Unit|Drop off unit|Pick up unit):\s*([0-9]+)', raw_text, re.IGNORECASE)
    if unit_match:
        fallback_data["unit_number"] = unit_match.group(1).strip()
        
    # Extract VIN
    vin_match = re.search(r'Vin:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if vin_match:
        fallback_data["vin"] = vin_match.group(1).strip()
        
    # Extract Plate
    plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if plate_match:
        fallback_data["plate"] = plate_match.group(1).strip()

    if not client:
        return fallback_data
    
    prompt = (
        "Extract logistics fields from this text into a strict JSON object with keys: "
        "'company', 'driver_status', 'driver_type', 'driver_name', 'driver_effective_date', "
        "'truck_status', 'plate', 'state', 'unit_number', 'make', 'year', 'vin', 'truck_type'.\n\n"
        f"Text:\n{raw_text}\n\nReturn ONLY valid JSON. No markdown backticks."
    )
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        
        # Merge with fallback if any key is missing
        for k, v in fallback_data.items():
            if not data.get(k):
                data[k] = v
        return data
    except Exception as e:
        print(f"AI Quota/Parsing error ({e}), using smart regex fallback...")
        return fallback_data

if __name__ == "__main__":
    print("Waiting for old instance to close...")
    time.sleep(5)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse AI Bot is running with Quota Protection...")
    bot.infinity_polling(skip_pending=True)
