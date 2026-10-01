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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")
AUDIT_WORKSHEET_NAME = os.getenv("AUDIT_WORKSHEET_NAME", "Audit Log")
CREDS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# Initialize Sheet Engine & Gemini Client
sheet_manager = FleetSheetManager(
    spreadsheet_id=SPREADSHEET_ID,
    worksheet_name=WORKSHEET_NAME,
    audit_worksheet_name=AUDIT_WORKSHEET_NAME,
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
  is_dispatch_related: bool = Field(
      description=(
          "Set to true if this message contains vehicle or driver assignments,"
          " drops, pickups, or status changes. Set to false for regular chat,"
          " greetings, or irrelevant talk."
      )
  )
  action: str = Field(
      default="",
      description="'pickup', 'drop', 'swap', 'returned', or 'transfer'",
  )
  company_name: str = Field(
      default="", description="Name of company or carrier"
  )
  unit_number: str = Field(default="", description="Truck unit number")
  effective_date: str = Field(
      default="", description="Event date formatted as MM/DD/YYYY"
  )
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
      "Analyze every message. First decide whether the text relates to fleet operations "
      "(truck pickup, drop, driver change, swap, or unit location updates). "
      "If it is not dispatch-related, set is_dispatch_related to false. "
      "If it is relevant, set is_dispatch_related to true and extract driver names "
      "(tag team1/team2 if team drivers are present), unit numbers, effective dates (MM/DD/YYYY), "
      "company names, and locations (e.g., Rolling, Shop, Returned, Yard, Vacation)."
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

  if message.from_user and message.from_user.is_bot:
    return

  try:
    parsed_event = extract_dispatch_info(text)

    if (
        not parsed_event.get("is_dispatch_related")
        or not parsed_event.get("unit_number")
    ):
      return

    logging.info(f"Processing dispatch message: {text}")

    # Pass parsed data along with raw message text to maintain an audit trail
    result = sheet_manager.process_event(parsed_event, raw_text=text)
    await message.reply_text(f"Processed & Audited via Gemini:\n{result}")

  except Exception as e:
    logging.error(f"Error handling message: {e}", exc_info=True)


def main():
  app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
  app.add_handler(
      MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
  )
  print("Fleet Bot with Audit Logging is active...")
  app.run_polling()


if __name__ == "__main__":
  main()
