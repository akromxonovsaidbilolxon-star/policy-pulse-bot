import os
import telebot
import requests
import json
import time
import re
from datetime import datetime
from google import genai
from collections import defaultdict
from threading import Timer

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

message_buffers = defaultdict(list)
timers = {}

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    if not text:
        return
    
    print(f"Captured text from chat {chat_id}: {text[:60]}...")
    message_buffers[chat_id].append(text)
    
    if chat_id in timers:
        timers[chat_id].cancel()
        
    timers[chat_id] = Timer(6.0, process_accumulated_messages, args=[chat_id])
    timers[chat_id].start()

def process_accumulated_messages(chat_id):
    texts = message_buffers.pop(chat_id, [])
    if not texts:
        return
        
    combined_text = "\n---\n".join(texts)
    print(f"Processing combined message block...")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Extract data using AI with fallback to regular expression parsing
    structured_data = extract_truck_data_with_ai(combined_text)
    structured_data["timestamp"] = timestamp
    structured_data["notes"] = f"Telegram Bot - {combined_text[:120]}"

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger response: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")

def extract_truck_data_with_ai(raw_text):
    # Improved regex fallback to catch names like "Jonathan Correa" or "Daud Abdirahim Aden"
    fallback_driver = "Unknown Driver"
    
    # Look for patterns after words like Driver, or capitalized name pairs
    name_match = re.search(r'(?:Driver[:\s]*|[-–]\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})', raw_text)
    if name_match:
        fallback_driver = name_match.group(1).strip()
    else:
        # Fallback to finding capitalized multi-word names in raw text
        words_match = re.search(r'\b([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', raw_text)
        if words_match:
            fallback_driver = words_match.group(1).strip()

    unit_match = re.search(r'(?:Unit[:\s#]*|Truck[:\s#]*)([0-9]{4,6})', raw_text, re.IGNORECASE)
    fallback_unit = unit_match.group(1) if unit_match else ""

    if not client:
        return {"driver_name": fallback_driver, "unit_number": fallback_unit, "company": "Borderlanders Inc", "driver_status": "Active"}
    
    prompt = f"""
    Analyze these logistics dispatch messages and extract the fields as a strict JSON object with these exact keys:
    - "company": ("Borderlanders Inc", "Cargoprime Corp", "Successor Inc", or "Pars")
    - "driver_status": ("Active", "Inactive", or "Terminated")
    - "driver_type": ("Company driver" or "Owner" or "Finance")
    - "driver_name": (Extract the full driver name or team, e.g. "Jonathan Correa", "Daud Abdirahim Aden / Mohamed Yusuf Moalim")
    - "driver_effective_date": (YYYY-MM-DD if found, else current date)
    - "unit_number": (Unit number if found)
    - "make": (Truck make like Kenworth, Volvo, Freightliner if found)
    - "year": (Year if found)
    - "vin": (VIN if found)

    Messages:
    {raw_text}
    
    Return ONLY valid JSON. No markdown backticks, just raw JSON.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        
        if not data.get("driver_name") or data.get("driver_name") == "Unknown Driver":
            data["driver_name"] = fallback_driver
        if not data.get("unit_number"):
            data["unit_number"] = fallback_unit
            
        return data
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {
            "company": "Borderlanders Inc",
            "driver_name": fallback_driver,
            "unit_number": fallback_unit,
            "driver_status": "Active",
            "driver_type": "Company driver"
        }

    if not client:
        return {"driver_name": fallback_driver, "unit_number": fallback_unit, "company": "Borderlanders Inc", "driver_status": "Active"}
    
    prompt = f"""
    Analyze these logistics dispatch messages and extract the fields as a strict JSON object with these exact keys:
    - "company": ("Borderlanders Inc", "Cargoprime Corp", "Successor Inc", or "Pars")
    - "driver_status": ("Active", "Inactive", or "Terminated")
    - "driver_type": ("Company driver" or "Owner" or "Finance")
    - "driver_name": (Full name of driver or team, e.g. "Jonathan Correa", "Daud Abdirahim Aden / Mohamed Yusuf Moalim")
    - "driver_effective_date": (YYYY-MM-DD if found, else current date)
    - "driver_termination_date": ("")
    - "truck_status": ("Active" or "Inactive")
    - "plate": ("")
    - "state": ("")
    - "unit_number": (Unit number if found)
    - "make": (Truck make like Kenworth, Volvo, Freightliner if found)
    - "year": (Year if found)
    - "vin": (VIN if found)
    - "truck_type": ("")

    Messages:
    {raw_text}
    
    Return ONLY valid JSON. No markdown backticks, just raw JSON.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        
        # If AI missed the driver name, use our regex fallback
        if not data.get("driver_name") or data.get("driver_name") == "Unknown Driver":
            data["driver_name"] = fallback_driver
        if not data.get("unit_number"):
            data["unit_number"] = fallback_unit
            
        return data
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {
            "company": "Borderlanders Inc",
            "driver_name": fallback_driver,
            "unit_number": fallback_unit,
            "driver_status": "Active",
            "driver_type": "Company driver"
        }

if __name__ == "__main__":
    print("Waiting for old instance to close...")
    time.sleep(5)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse AI Bot is running...")
    bot.infinity_polling(skip_pending=True)
