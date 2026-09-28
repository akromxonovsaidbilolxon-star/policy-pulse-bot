import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot
from telebot import types

# 1. Initialize Bot
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# 2. Setup Google Sheets Connection
def get_sheets_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # If storing credentials in a JSON file:
    # creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    
    # Alternatively, parsing from an environment variable string:
    creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
    creds = ServiceAccountCredentials.from_json_creds_dict(creds_dict, scope)
    
    client = gspread.authorize(creds)
    return client

def log_event_to_sheet(data_row):
    try:
        client = get_sheets_client()
        sheet_name = os.getenv("SPREADSHEET_NAME", "PolicyPulse_Logs")
        sheet = client.open(sheet_name).sheet1
        sheet.append_row(data_row)
        return True
    except Exception as e:
        print(f"Error writing to Google Sheets: {e}")
        return False

# 3. Bot Handlers
@bot.message_handler(commands=['start', 'help'])
send_welcome(message):
    welcome_text = (
        "👋 **Welcome to Policy Pulse Bot!**\n\n"
        "Send your driver updates, status changes, or truck swap logs using the format:\n"
        "`[Driver Name] | [Event Type] | [Details]`\n\n"
        "Example:\n"
        "John Doe | Truck Swap | Unit #402 to #405"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_log_message(message):
    text = message.text
    user = message.from_user.username or message.from_user.first_name
    
    # Basic parsing logic (splitting by pipe '|')
    parts = [p.strip() for p in text.split('|')]
    
    if len(parts) >= 3:
        driver_name = parts[0]
        event_type = parts[1]
        details = parts[2]
        timestamp = message.date # Can be formatted to a readable date string
        
        # Row data structure for Google Sheets
        row_data = [str(timestamp), user, driver_name, event_type, details]
        
        success = log_event_to_sheet(row_data)
        
        if success:
            bot.reply_to(message, "✅ Event successfully logged to Google Sheets!")
        else:
            bot.reply_to(message, "⚠️ Failed to log event. Please check system logs.")
    else:
        bot.reply_to(
            message, 
            "❌ Invalid format. Please use: `Driver Name | Event Type | Details`", 
            parse_mode="Markdown"
        )

# 4. Run Bot
if __name__ == "__main__":
    print("Policy Pulse Bot is running...")
    bot.infinity_polling()
