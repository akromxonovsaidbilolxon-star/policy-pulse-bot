import os
import telebot
import requests
import json
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
    
    # Use AI to parse the text into structured data
    structured_data = extract_truck_data_with_ai(text)
    structured_data["timestamp"] = timestamp
    structured_data["chat_name"] = message.chat.title or "Private Chat"
    structured_data["sender"] = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()

    # Send structured data to Google Apps Script
    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger updated: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")

def extract_truck_data_with_ai(raw_text):
    """Uses Gemini to parse trucking text into strict JSON."""
    if not client:
        return {"action_type": "log", "notes": raw_text}
    
    prompt = f"""
    Analyze this trucking inspection or swap note and extract the fields as a JSON object with these exact keys:
    - "company": (e.g. BORDERLANDERS INC)
    - "driver_name": (Full name of driver)
    - "action_type": ("pickup", "dropoff", "truck_swap", or "inactive")
    - "unit_number": (Pick up or drop off unit number)
    - "vin": (VIN number if present)
    - "make_year": (Make and year if present)
    - "plate": (Plate number if present)
    - "notes": (Inspector notes or reason)

    Note text:
    {raw_text}
    
    Return ONLY valid JSON. No markdown ticks, just raw JSON.
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {"action_type": "log", "notes": raw_text}

if __name__ == "__main__":
    bot.remove_webhook()
    print("Policy Pulse AI Bot is running...")
    bot.infinity_polling()
