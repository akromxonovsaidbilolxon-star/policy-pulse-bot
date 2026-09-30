import os
import telebot
from google import genai
from google.genai import types

# 1. Load Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("Telegram_Token")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing Telegram_Token or GEMINI_API_KEY in environment variables.")

# 2. Initialize Telegram Bot and Gemini Client
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# System prompt defining what violations to check for
VIOLATION_PROMPT = """
You are an expert compliance and document auditor. Analyze the provided image, document, or text 
for any compliance violations, discrepancies, policy breaches, or anomalies. 
Provide a clear, concise report:
1. **Status:** (Compliant / Violation Found / Needs Review)
2. **Details:** Explain what was found.
3. **Recommendation:** What action should be taken.
"""

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "Hello! Send me any document, photo, or image, and I will scan it for violations and send the results directly here."
    )

# Handle Photos
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # Get the highest resolution photo
        fileID = message.photo[-1].file_id
        file_info = bot.get_file(fileID)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save temporarily
        temp_path = "temp_image.jpg"
        with open(temp_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Upload to Gemini File API and analyze
        uploaded_file = client.files.upload(file=temp_path)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, VIOLATION_PROMPT]
        )
        
        # Clean up local file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        # Send result back to the Telegram chat
        bot.reply_to(message, response.text)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing image: {str(e)}")

# Handle Documents (PDFs, Images as files, etc.)
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_name = message.document.file_name or "temp_doc"
        temp_path = f"temp_{file_name}"
        
        with open(temp_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Upload to Gemini File API and analyze
        uploaded_file = client.files.upload(file=temp_path)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[uploaded_file, VIOLATION_PROMPT]
        )
        
        # Clean up local file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        # Send result back to the Telegram chat
        bot.reply_to(message, response.text)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing document: {str(e)}")

if __name__ == "__main__":
    print("Bot is starting and polling for messages...")
    # Start polling so it listens continuously for incoming messages in Telegram
    bot.infinity_polling()
