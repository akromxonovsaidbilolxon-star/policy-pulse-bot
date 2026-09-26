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
    
    print(f"Received message: {text}")
    
    # Use AI to parse the text into structured trucking data
    structured_data = extract_truck_data_with_ai(text)
    structured_data["timestamp"] = timestamp
    
    # Send structured data to Google Apps Script Web App (/exec URL)
    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data)
            print(f"Ledger updated response: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")
    else:
        print("Error: GOOGLE_SCRIPT_URL environment variable is missing.")

def extract_truck_data_with_ai(raw_text):
    """Uses Gemini to parse trucking/driver text into strict JSON."""
    if not client:
        return {"action_type": "log", "reason": raw_text, "status": "Active"}
    
    prompt = f"""
    Analyze this logistics, trucking, or driver update message and extract the fields as a JSON object with these exact keys:
    - "company": (e.g. "CargoPrime Corp" or "Borderlanders Inc")
    - "driver_name": (Full name of driver if mentioned, else null)
    - "action_type": (Choose one: "driver_terminated", "driver_added", "driver_moved", "driver_changed", "truck_swap", "truck_added", "truck_removed", "truck_inactive", "truck_active", or "log")
    - "status": (Choose one: "Active", "Terminated", "Inactive", "Swapped")
    - "unit_number": (Unit number if mentioned, else "")
    - "vin": (VIN number if mentioned, else "")
    - "reason": (Reason for change, termination, or notes if mentioned, else "")

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
        return {"action_type": "log", "reason": raw_text, "status": "Active"}

if __name__ == "__main__":
    print("Clearing any lingering webhooks...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Webhook clear note: {e}")
        
    print("Policy Pulse AI Bot is running...")
    bot.infinity_polling(skip_pending=True)
