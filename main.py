import os
import telebot
import requests
from datetime import datetime

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if message.chat.title:
        chat_name = message.chat.title
    else:
        chat_name = f"Private: {message.chat.first_name or ''} {message.chat.last_name or ''}".strip()
        
    sender = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    if not sender:
        sender = message.from_user.username or "Unknown"
        
    text = message.text or "[Non-text message]"

    payload = {
        "timestamp": timestamp,
        "chat_name": chat_name,
        "sender": sender,
        "message": text
    }

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=payload)
            print(f"Logged to Sheets: {response.text}")
        except Exception as e:
            print(f"Error posting to Google Sheets: {e}")
    else:
        print("GOOGLE_SCRIPT_URL is not set.")

if __name__ == "__main__":
    print("Policy Pulse Bot is running and polling for messages...")
    bot.infinity_polling()
