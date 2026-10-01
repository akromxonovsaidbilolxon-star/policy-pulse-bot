import json
import logging
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from sheet_engine import FleetSheetManager

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_USERNAME = os.getenv("TARGET_USERNAME", "").lstrip("@").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")
CREDS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# Initialize Sheet Engine & Gemini Client
sheet_manager = FleetSheetManager(
    spreadsheet_id=SPREADSHEET_ID,
    worksheet_name=WORKSHEET_NAME,
    creds_path=CREDS_PATH,
    creds_json=CREDS_JSON,
)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


class DriverItem(BaseModel):
  name: str = Field(description="Full name of driver")
  team_tag: str = Field(
      default="", description="'team1', 'team2', or empty if solo"
  )


class DispatchEvent(BaseModel):
  action: str = Field(
      description="'pickup', 'drop', 'swap', 'returned', or 'transfer'"
  )
  company_name: str = Field(
      default="", description="Name of company or carrier"
  )
  unit_number: str = Field(description="Truck unit number")
  effective_date: str = Field(description="Event date formatted as MM/DD/YYYY")
  location: str = Field(
      default="",
      description=(
          "Vehicle location: Rolling, Shop, Yard, Vacation, Returned, etc."
      ),
  )
  drivers: list[DriverItem] = Field(
      default_factory=list, description="List of drivers involved"
  )


def extract_dispatch_info(text: str) -> dict:
  system_instruction = (
      "You are an insurance and fleet compliance extraction parser. "
      "Extract details from logistics/dispatch messages into strict JSON"
      " format. Identify driver names (and tag team1/team2 if team drivers are"
      " present), unit numbers, effective dates (convert to MM/DD/YYYY),"
      " company names, and locations (e.g., Rolling, Shop, Returned, Yard,"
      " Vacation)."
  )

  response = gemini_client.models.generate_content(
      model="gemini-2.5-flash",
      contents=text,
      config=types.GenerateContentConfig(
          system_instruction=system_instruction,
          response_mime_type="application/json",
          response_schema=DispatchEvent,
          temperature=0.1,
      ),
  )

  return json.loads(response.text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  message = update.effective_message
  if not message or not message.text:
    return

  text = message.text
  bot_username = context.bot.username.lower() if context.bot.username else ""
  is_tagged = False

  # Check mention entities
  if message.entities:
    for ent in message.entities:
      if ent.type == "mention":
        mention = text[ent.offset : ent.offset + ent.length].lstrip("@").lower()
        if mention in [TARGET_USERNAME, bot_username]:
          is_tagged = True
          break
      elif ent.type == "text_mention" and ent.user and ent.user.username:
        if ent.user.username.lower() in [TARGET_USERNAME, bot_username]:
          is_tagged = True
          break

  # Check replies
  if message.reply_to_message and message.reply_to_message.from_user:
    replied_user = message.reply_to_message.from_user.username or ""
    if replied_user.lower() in [TARGET_USERNAME, bot_username]:
      is_tagged = True

  if not is_tagged:
    return

  logging.info(f"Tag detected: {text}")

  try:
    parsed_event = extract_dispatch_info(text)
    logging.info(f"Extracted payload: {parsed_event}")

    if not parsed_event.get("unit_number"):
      await message.reply_text(
          "Could not detect a valid unit number from this message."
      )
      return

    result = sheet_manager.process_event(parsed_event)
    await message.reply_text(f"Processed via Gemini:\n{result}")

  except Exception as e:
    logging.error(f"Error handling update: {e}", exc_info=True)
    await message.reply_text(f"Error updating sheet: {str(e)}")


def main():
  app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
  app.add_handler(
      MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
  )
  print("Fleet Bot is active and listening...")
  app.run_polling()


if __name__ == "__main__":
  main()
