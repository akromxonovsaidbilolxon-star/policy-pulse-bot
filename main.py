import os
import telebot
import requests
import json
import time
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
        "You are an advanced logistics data extraction engine. Analyze the following Telegram message text carefully. "
        "Your job is to extract real driver names, unit numbers, companies, and truck specs.\n\n"
        "CRITICAL RULES FOR DRIVER NAMES:\n"
        "- Look for actual human names (e.g., 'Jonathan Correa', 'Daud Abdirahim Aden', 'Mohamed Yusuf Moalim', 'Frank Rodriguez').\n"
        "- IGNORE administrative words like 'Date', 'Inspector', 'Driver GTG', 'Telegram', or group chat titles.\n"
        "- If no genuine human driver name is present in the text, return an empty string '' for 'driver_name'. Do NOT guess or pick random words.\n\n"
        "Extract fields into a strict JSON object with these exact keys:\n"
        "- 'company': (Extract company name like 'Successor Inc', 'Cargoprime Corp', 'Borderlanders Inc', or 'Pars', default to 'Borderlanders Inc')\n"
        "- 'driver_status': ('Active', 'Inactive', or 'Terminated')\n"
        "- 'driver_type': ('Company driver' or 'Owner')\n"
        "- 'driver_name': (Real full driver name or team string, or '' if none)\n"
        "- 'driver_effective_date': (YYYY-MM-DD if found, else current date)\n"
        "- 'unit_number': (Unit number if found, else '')\n"
        "- 'make': (Truck make if found, else '')\n"
        "- 'year': (Year if found, else '')\n"
        "- 'vin': (VIN if found, else '')\n\n"
        f"Messages:\n{raw_text}\n\n"
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
        
    print("Policy Pulse AI Bot is running...")
    bot.infinity_polling(skip_pending=True)
