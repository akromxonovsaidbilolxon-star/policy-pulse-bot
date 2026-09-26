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

# Буфер для сбора сообщений из чатов, чтобы объединять быстрые серии постов
message_buffers = defaultdict(list)
timers = {}

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    if not text:
        return
    
    print(f"Captured part from chat {chat_id}: {text[:50]}...")
    
    # Добавляем текст сообщения в буфер конкретного чата
    message_buffers[chat_id].append(text)
    
    # Сбрасываем таймер: ждем 8 секунд тишины, чтобы собрать все части сообщения воедино
    if chat_id in timers:
        timers[chat_id].cancel()
        
    timers[chat_id] = Timer(8.0, process_accumulated_messages, args=[chat_id])
    timers[chat_id].start()

def process_accumulated_messages(chat_id):
    texts = message_buffers.pop(chat_id, [])
    if not texts:
        return
        
    combined_text = "\n---\n".join(texts)
    print(f"Processing combined message block ({len(texts)} parts)...")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Отправляем всю пачку целиком в Gemini AI
    structured_data = extract_truck_data_with_ai(combined_text)
    structured_data["timestamp"] = timestamp
    structured_data["notes"] = f"Telegram Group Update - {combined_text[:100]}..."

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger response: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")

def extract_truck_data_with_ai(raw_text):
    if not client:
        return {}
    
    prompt = f"""
    Analyze this complete set of trucking/driver update messages from Telegram and extract fields into a JSON object with these exact keys:
    - "company": (Extract company name like "Successor Inc", "Cargoprime Corp", or "Borderlanders Inc")
    - "driver_status": ("Active", "Inactive", or "Terminated")
    - "driver_type": ("Company driver" or "Owner" or "Finance")
    - "driver_name": (Full name of driver/team mentioned, e.g., "Daud Abdirahim Aden / Mohamed Yusuf Moalim", else "Unknown Driver")
    - "driver_effective_date": (Effective date in YYYY-MM-DD if mentioned, else current date)
    - "driver_termination_date": (Termination date if mentioned, else "")
    - "truck_status": ("Active" or "Inactive" or "Changed unit")
    - "plate": (Plate number if mentioned, else "")
    - "state": (State code like IN, PA, GA if mentioned, else "")
    - "unit_number": (Unit number like 6603311 if mentioned, else "")
    - "make": (Truck make like Kenworth, Volvo, Freightliner if mentioned, else "")
    - "year": (Year like 2026 if mentioned, else "")
    - "vin": (VIN number if mentioned, else "")
    - "truck_type": (Truck type/vendor if mentioned, else "")

    Combined Message text:
    {raw_text}
    
    Return ONLY valid JSON. No markdown backticks, just raw JSON.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {}

if __name__ == "__main__":
    print("Waiting for old instance to close...")
    time.sleep(5)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse AI Bot is running with smart multi-message grouping...")
    bot.infinity_polling(skip_pending=True)
