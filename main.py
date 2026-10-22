import os
import telebot
import requests
import json
import time
import re
import threading
import uuid
import io
import pandas as pd
from datetime import datetime
from collections import defaultdict
from telebot import types

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

if not TOKEN:
    print("Error: Missing TELEGRAM_BOT_TOKEN in environment variables.")

bot = telebot.TeleBot(TOKEN)
message_buffers = defaultdict(list)
timers = {}
buffer_lock = threading.Lock()

# Month name mapping for natural language queries
MONTH_MAP = {
    "january": 1, "jan": 1, "01": 1,
    "february": 2, "feb": 2, "02": 2,
    "march": 3, "mar": 3, "03": 3,
    "april": 4, "apr": 4, "04": 4,
    "may": 5, "05": 5,
    "june": 6, "jun": 6, "06": 6,
    "july": 7, "jul": 7, "07": 7,
    "august": 8, "aug": 8, "08": 8,
    "september": 9, "sep": 9, "sept": 9, "09": 9,
    "october": 10, "oct": 10, "10": 10,
    "november": 11, "nov": 11, "11": 11,
    "december": 12, "dec": 12, "12": 12
}

@bot.message_handler(commands=['myid', 'start'])
def send_my_id(message):
    chat_id = message.chat.id
    bot.reply_to(message, f"Your Telegram Chat ID is: {chat_id}")

@bot.message_handler(func=lambda msg: msg.text and ("change report" in msg.text.lower() or "report for" in msg.text.lower()))
def handle_report_request(message):
    query = message.text.strip()
    bot.reply_to(message, "🔍 Pulling audit records and generating Excel report...")

    # Extract target month
    matched_month = None
    matched_month_name = ""
    for name, month_num in MONTH_MAP.items():
        if re.search(rf"\b{name}\b", query, re.IGNORECASE):
            matched_month = month_num
            matched_month_name = name.capitalize()
            break

    # Extract company name (assumes phrasing like: "give me <Company> change report for ...")
    company_name = None
    comp_match = re.search(r"(?:give me\s+)?(.+?)\s+(?:change\s+)?report", query, re.IGNORECASE)
    if comp_match:
        company_name = comp_match.group(1).strip()

    if not GOOGLE_SCRIPT_URL:
        bot.reply_to(message, "⚠️ GOOGLE_SCRIPT_URL is not set.")
        return

    try:
        resp = requests.get(f"{GOOGLE_SCRIPT_URL}?action=get_records", timeout=30)
        records = resp.json()

        report_rows = []
        for r in records:
            # Match company (case-insensitive substring)
            rec_company = str(r.get("company", "") or r.get("Company", "")).strip()
            if company_name and company_name.lower() not in rec_company.lower():
                continue

            # Parse and match date
            date_raw = str(r.get("event_date", "") or r.get("Date", "") or r.get("timestamp", "")).strip()
            event_dt = None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
                try:
                    event_dt = datetime.strptime(date_raw.split()[0], fmt)
                    break
                except Exception:
                    continue

            if matched_month and event_dt and event_dt.month != matched_month:
                continue

            event_date_str = event_dt.strftime("%Y-%m-%d") if event_dt else date_raw
            action = str(r.get("action_type", "") or r.get("Action", "")).upper()

            d_unit = r.get("unit_number", "") or r.get("Drop Unit", "")
            p_unit = r.get("pickup_unit", "") or r.get("Pick Up Unit", "")
            d_vin = r.get("vin", "") or r.get("Drop VIN", "")
            p_vin = r.get("pickup_vin", "") or r.get("Pick Up VIN", "")

            # Break out each event into individual Add / Remove operations
            if action == "SWAP":
                if d_unit or d_vin:
                    report_rows.append({
                        "Date": event_date_str,
                        "Truck Number": d_unit,
                        "VIN Number": d_vin,
                        "What Happened": "Drop"
                    })
                if p_unit or p_vin:
                    report_rows.append({
                        "Date": event_date_str,
                        "Truck Number": p_unit,
                        "VIN Number": p_vin,
                        "What Happened": "Pick up"
                    })
            elif action == "DROPOFF":
                report_rows.append({
                    "Date": event_date_str,
                    "Truck Number": d_unit or p_unit,
                    "VIN Number": d_vin or p_vin,
                    "What Happened": "Drop"
                })
            else:  # PICKUP
                report_rows.append({
                    "Date": event_date_str,
                    "Truck Number": p_unit or d_unit,
                    "VIN Number": p_vin or d_vin,
                    "What Happened": "Pick up"
                })

        if not report_rows:
            bot.reply_to(message, f"No matching records found for {company_name or 'the specified company'}"
                                  f"{f' in {matched_month_name}' if matched_month_name else ''}.")
            return

        # Build Excel sheet
        df = pd.DataFrame(report_rows)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Change Report')
            
            # Format column widths
            worksheet = writer.sheets['Change Report']
            for col in worksheet.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                worksheet.column_dimensions[col_letter].width = max(max_len + 4, 14)

        excel_buffer.seek(0)
        file_company = (company_name or "Fleet").replace(" ", "_")
        filename = f"{file_company}_Change_Report_{matched_month_name or 'All'}.xlsx"
        
        bot.send_document(
            message.chat.id,
            document=types.InputFile(excel_buffer, filename=filename),
            caption=f"📊 *{company_name or 'Fleet'}* change report ({len(report_rows)} entries)",
            parse_mode="Markdown"
        )

    except Exception as err:
        print(f"Error producing report: {err}")
        bot.reply_to(message, f"❌ Failed to generate report: {err}")

def handle_incoming_content(message_or_post):
    try:
        chat_id = message_or_post.chat.id
    except AttributeError:
        return
        
    text = getattr(message_or_post, 'text', None) or getattr(message_or_post, 'caption', None) or ""
    if not text or text.startswith('/'):
        return
    
    with buffer_lock:
        message_buffers[chat_id].append(text)
        if chat_id in timers:
            timers[chat_id].cancel()
        timers[chat_id] = threading.Timer(4.0, process_accumulated_messages, args=[chat_id])
        timers[chat_id].start()

@bot.message_handler(func=lambda message: True)
def handle_incoming_report(message):
    handle_incoming_content(message)

@bot.channel_post_handler(func=lambda post: True)
def handle_channel_posts(post):
    handle_incoming_content(post)

def process_accumulated_messages(chat_id):
    with buffer_lock:
        texts = message_buffers.pop(chat_id, [])
        if chat_id in timers:
            del timers[chat_id]
            
    if not texts:
        return
        
    combined_text = "\n".join(texts)
    print(f"=== PROCESSING BLOCK ({len(texts)} parts) ===")
    
    transaction_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    structured_data = extract_truck_data(combined_text)
    structured_data["transaction_id"] = transaction_id
    structured_data["timestamp"] = timestamp
    structured_data["raw_message"] = combined_text

    if GOOGLE_SCRIPT_URL:
        try:
            response = requests.post(GOOGLE_SCRIPT_URL, json=structured_data, timeout=45)
            print(f"Ledger response: {response.text}")
            
            if ADMIN_TELEGRAM_ID:
                try:
                    res_json = response.json()
                    if res_json.get("status") == "success":
                        action = structured_data.get("action_type", "UPDATE")
                        company = structured_data.get("company", "N/A")
                        driver = structured_data.get("driver_name", "N/A")
                        
                        d_unit = structured_data.get("unit_number")
                        p_unit = structured_data.get("pickup_unit")
                        
                        if action == "SWAP":
                            unit_display = f"Dropped: {d_unit or 'N/A'} ➔ Picked Up: {p_unit or 'N/A'}"
                        elif action == "DROPOFF":
                            unit_display = f"Dropped: {d_unit or p_unit or 'N/A'}"
                        else:
                            unit_display = f"Picked Up: {p_unit or d_unit or 'N/A'}"
                            
                        loc = structured_data.get("location", "N/A")
                        change_date = structured_data.get("event_date", datetime.now().strftime("%Y-%m-%d"))
                        
                        notif_text = (
                            f"🛡️ *PolicyPulse // Fleet Operations Dispatch*\n\n"
                            f"• *Action:* {action}\n"
                            f"• *Company:* {company}\n"
                            f"• *Driver:* {driver}\n"
                            f"• *Unit:* {unit_display}\n"
                            f"• *Location:* {loc}\n"
                            f"• *Change Date:* {change_date}\n"
                            f"• *Status:* Sheet successfully updated ✅"
                        )
                        
                        markup = types.InlineKeyboardMarkup()
                        btn = types.InlineKeyboardButton("Task completed: Update the insurance", callback_data="insurance_updated")
                        markup.add(btn)
                        
                        bot.send_message(ADMIN_TELEGRAM_ID, notif_text, parse_mode="Markdown", reply_markup=markup)
                except Exception as notif_err:
                    print(f"Failed to send Telegram notification: {notif_err}")

        except Exception as e:
            print(f"Error posting to Google Sheets Apps Script: {e}")
    else:
        print("Warning: GOOGLE_SCRIPT_URL is not set.")

@bot.callback_query_handler(func=lambda call: call.data == "insurance_updated")
def handle_insurance_callback(call):
    try:
        updated_text = call.message.text + "\n• *Insurance Status:* Completed & Verified ✅"
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=updated_text,
            parse_mode="Markdown",
            reply_markup=None 
        )
        bot.answer_callback_query(call.id, text="Insurance marked as completed!")
    except Exception as e:
        print(f"Error updating message on callback: {e}")

def extract_truck_data(raw_text):
    data = {
        "company": "Pars Transportation",
        "action_type": "PICKUP",
        "driver_status": "",
        "driver_name": "",
        "unit_number": "",
        "vin": "",
        "plate": "",
        "pickup_unit": "",
        "pickup_vin": "",
        "pickup_plate": "",
        "make": "",
        "year": "",
        "pickup_make": "",
        "pickup_year": "",
        "truck_type": "Nexgen Rental",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "Shop"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper:
        data["action_type"] = "SWAP"
        data["driver_status"] = ""
    elif "TERMINAT" in text_upper or "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper or "DROP" in text_upper:
        data["action_type"] = "DROPOFF"
        data["driver_status"] = "Empty"
    else:
        data["action_type"] = "PICKUP"
        data["driver_status"] = "Active"
        
    text_lower = raw_text.lower()
    if "returned" in text_lower or "return" in text_lower:
        data["location"] = "Returned"
    elif "yard" in text_lower:
        data["location"] = "Yard"
    elif "shop" in text_lower or "repair" in text_lower or "issue" in text_lower or "fulton" in text_lower or "boulevard" in text_lower:
        data["location"] = "Shop"
    elif "home" in text_lower:
        data["location"] = "Home"
    else:
        data["location"] = "Shop" if data["action_type"] in ["SWAP", "DROPOFF"] else "Rolling"

    company_match = re.search(r'Company:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if company_match:
        data["company"] = company_match.group(1).strip()
        
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()

    if "Pick up unit" in raw_text or data["action_type"] == "SWAP":
        parts = re.split(r'Pick up unit', raw_text, flags=re.IGNORECASE)
        drop_section = parts[0]
        pickup_section = parts[1] if len(parts) > 1 else ""

        drop_unit = re.search(r'(?:Drop unit|Drop off unit|Unit)[:\s#]*([0-9]+)', drop_section, re.IGNORECASE)
        if drop_unit:
            data["unit_number"] = drop_unit.group(1).strip()

        drop_vin = re.search(r'[Vv]in:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_vin:
            data["vin"] = drop_vin.group(1).strip()

        drop_plate = re.search(r'Plate:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_plate:
            data["plate"] = drop_plate.group(1).strip()
            
        drop_make = re.search(r'Make model year:\s*([^\n]+)', drop_section, re.IGNORECASE)
        if drop_make:
            make_val = drop_make.group(1).strip()
            data["make"] = make_val
            year_match = re.search(r'(20[0-9]{2})', make_val)
            if year_match:
                data["year"] = year_match.group(1)

        if pickup_section:
            pick_unit = re.search(r'[:\s#]*([0-9]+)', pickup_section)
            if pick_unit:
                data["pickup_unit"] = pick_unit.group(1).strip()

            pick_vin = re.search(r'[Vv]in:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_vin:
                data["pickup_vin"] = pick_vin.group(1).strip()

            pick_plate = re.search(r'Plate:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_plate:
                data["pickup_plate"] = pick_plate.group(1).strip()
                
            pick_make = re.search(r'Make model year:\s*([^\n]+)', pickup_section, re.IGNORECASE)
            if pick_make:
                pick_make_val = pick_make.group(1).strip()
                data["pickup_make"] = pick_make_val
                pick_year_match = re.search(r'(20[0-9]{2})', pick_make_val)
                if pick_year_match:
                    data["pickup_year"] = pick_year_match.group(1)
    else:
        unit_match = re.search(r'(?:Drop off unit|Drop unit|Pick up unit|Unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
        if unit_match:
            data["pickup_unit"] = unit_match.group(1).strip()
            data["unit_number"] = unit_match.group(1).strip()

        vin_match = re.search(r'[Vv]in:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if vin_match:
            data["pickup_vin"] = vin_match.group(1).strip()
            data["vin"] = vin_match.group(1).strip()

        plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if plate_match:
            data["plate"] = plate_match.group(1).strip()
            data["pickup_plate"] = plate_match.group(1).strip()

        make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
        if make_match:
            make_val = make_match.group(1).strip()
            data["make"] = make_val
            data["pickup_make"] = make_val
            year_match = re.search(r'(20[0-9]{2})', make_val)
            if year_match:
                data["year"] = year_match.group(1)
                data["pickup_year"] = year_match.group(1)

    return data

if __name__ == "__main__":
    print("Waiting 8 seconds to ensure old bot instance is dead...")
    time.sleep(8)
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Webhook note: {e}")
        
    print("Policy Pulse Fleet Bot is running on Railway...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Polling error encountered: {e}. Restarting in 5 seconds...")
            time.sleep(5)
