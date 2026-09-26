import os
import telebot
import requests
import json
import time
from datetime import datetime
from google import genai

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    text = message.text or ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Received message: {text}")
    
    structured_data = extract_truck_data_with_ai(text)
    structured_data["timestamp"] = timestamp
    structured_data["notes"] = f"Telegram Bot - {text}"

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
    Analyze this trucking/driver update message and extract fields into a JSON object with these exact keys:
    - "company": ("Borderlanders Inc" or "Cargoprime Corp" or company mentioned)
    - "driver_status": ("Active", "Inactive", or "Terminated")
    - "driver_type": ("Company driver" or "Owner" or "Finance")
    - "driver_name": (Full name of driver if mentioned, else "Unknown Driver")
    - "driver_effective_date": (Effective date in YYYY-MM-DD if mentioned, else current date)
    - "driver_termination_date": (Termination date if mentioned, else "")
    - "truck_status": ("Active" or "Inactive" or "Changed unit")
    - "plate": (Plate number if mentioned, else "")
    - "state": (State code like IN, PA, GA if mentioned, else "")
    - "unit_number": (Unit number if mentioned, else "")
    - "make": (Truck make like Freightliner, Volvo, Peterbilt if mentioned, else "")
    - "year": (Year like 2022, 2026 if mentioned, else "")
    - "vin": (VIN number if mentioned, else "")
    - "truck_type": (Truck type like Penske Lease, Ryder Rental if mentioned, else "")

    Message text:
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
    time.sleep(3)
    print("Clearing webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Note: {e}")
        
    print("Policy Pulse AI Bot is running...")
    bot.infinity_polling(skip_pending=True)
