import os
import telebot
import requests
import json
import time
import threading
from datetime import datetime
from google import genai
from collections import defaultdict

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Thread-safe storage for message buffering
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
        print(f"Captured part from chat {chat_id}: {text[:50]}...")
        message_buffers[chat_id].append(text)
        
        # Reset the timer safely
        if chat_id in timers:
            timers[chat_id].cancel()
            
        timers[chat_id] = threading.Timer(5.0, process_accumulated_messages, args=[chat_id])
        timers[chat_id].start()

def process_accumulated_messages(chat_id):
    with buffer_lock:
        texts = message_buffers.pop(chat_id, [])
        if chat_id in timers:
            del timers[chat_id]
            
    if not texts:
        return
        
    combined_text = "\n--- [NEW MESSAGE PART] ---\n".join(texts)
    print(f"=== PROCESSING COMBINED BLOCK ({len(texts)} parts) ===")
    print(combined_text[:300]) # Prints preview to Railway logs to verify everything is captured
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
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
    if not client:
        return {
            "company": "Borderlanders Inc",
            "driver_name": "",
            "driver_status": "Active",
            "driver_type": "Company driver"
        }
    
    prompt = (
        "You are an advanced logistics data extraction engine. Analyze the following combined Telegram message block carefully. "
        "These messages belong together as a single dispatch batch. Extract all driver names, unit numbers, companies, and truck specs.\n\n"
        "CRITICAL RULES:\n"
        "- Look for actual human names (e.g., 'Jonathan Correa', 'Daud Abdirahim Aden', 'Mohamed Yusuf Moalim').\n"
        "- IGNORE administrative UI words like 'Date', 'Inspector', 'Driver GTG', 'Telegram'.\n"
        "- If no genuine human driver name is present, return an empty string '' for 'driver_name'.\n\n"
        "Extract fields into a strict JSON object with these exact keys:\n"
        "- 'company': ('Successor Inc', 'Cargoprime Corp', 'Borderlanders Inc', or 'Pars', default to 'Borderlanders Inc')\n"
        "- 'driver_status': ('Active', 'Inactive', or 'Terminated')\n"
        "- 'driver_type': ('Company driver' or 'Owner')\n"
        "- 'driver_name': (Real full driver name or team string, or '' if none)\n"
        "- 'driver_effective_date': (YYYY-MM-DD if found, else current date)\n"
        "- 'unit_number': (Unit number if found, else '')\n"
        "- 'make': (Truck make if found, else '')\n"
        "- 'year': (Year if found, else '')\n"
        "- 'vin': (VIN if found, else '')\n\n"
        f"Combined Messages:\n{raw_text}\n\n"
        "Return ONLY valid JSON. No markdown backticks, just raw JSON."
    )
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        return data
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {
            "company": "Borderlanders Inc",
            "driver_name": "",
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
        
    print("Policy Pulse AI Bot is running with Thread-Safe Buffering...")
    bot.infinity_polling(skip_pending=True)
