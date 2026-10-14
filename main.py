import os
import telebot
import requests
import json
import time
import re
import threading
import uuid
from datetime import datetime
from collections import defaultdict
from telebot import types
import gspread  # <-- NEW IMPORT

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "").strip()
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

if not TOKEN:
    print("Error: Missing TELEGRAM_BOT_TOKEN in environment variables.")

# --- NEW: GOOGLE SHEETS SETUP ---
# Ensure 'credentials.json' is in the same folder as this script on Railway
try:
    gc = gspread.service_account(filename='credentials.json')
    # CHANGE THIS to the exact name of your Google Sheet
    spreadsheet = gc.open('Your_Spreadsheet_Name') 
    sheet1 = spreadsheet.worksheet('Sheet1') # Main Tracker
    sheet2 = spreadsheet.worksheet('Sheet2') # Policy Database
    GSPREAD_READY = True
    print("Successfully connected to Google Sheets directly.")
except Exception as e:
    print(f"Warning: gspread setup failed. Direct sheet updates disabled: {e}")
    GSPREAD_READY = False
# ---------------------------------

bot = telebot.TeleBot(TOKEN)
message_buffers = defaultdict(list)
timers = {}
buffer_lock = threading.Lock()

@bot.message_handler(commands=['myid', 'start'])
def send_my_id(message):
    chat_id = message.chat.id
    bot.reply_to(message, f"Your Telegram Chat ID is: {chat_id}")

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

    # --- NEW GSPREAD LOGIC EXECUTED HERE ---
    if GSPREAD_READY:
        action = structured_data.get("action_type")
        d_vin = structured_data.get("vin", "").upper().strip() # Dropped VIN
        p_vin = structured_data.get("pickup_vin", "").upper().strip() # Picked up VIN
        
        try:
            sheet1_vins = sheet1.col_values(15) # Sheet1 Column O (VIN)
            sheet2_vins = sheet2.col_values(3)  # Sheet2 Column C (VIN)
            
            # 1. HANDLE DROPOFFS AND OLD TRUCK IN SWAPS
            if action in ["DROPOFF", "SWAP"] and d_vin:
                try:
                    d_row = sheet1_vins.index(d_vin) + 1 # +1 because arrays start at 0, sheets at 1
                    # Update Truck Status (I/9) to In active. We DO NOT touch AL/PD.
                    sheet1.update_acell(f'I{d_row}', 'In active')
                    print(f"Gspread: Marked dropped truck {d_vin} as In active.")
                except ValueError:
                    print(f"Gspread: Dropped VIN {d_vin} not found in Sheet1.")
                    
            # 2. HANDLE PICKUPS AND NEW TRUCK IN SWAPS
            if action in ["PICKUP", "SWAP"] and p_vin:
                try:
                    p_row1 = sheet1_vins.index(p_vin) + 1
                    
                    # Look up statuses in Sheet2
                    al_status = ""
                    pd_status = ""
                    try:
                        p_row2 = sheet2_vins.index(p_vin) + 1
                        al_status = sheet2.cell(p_row2, 4).value # Column D (AL Policy)
                        pd_status = sheet2.cell(p_row2, 5).value # Column E (PD Policy)
                    except ValueError:
                        print(f"Gspread: Pickup VIN {p_vin} not found in Sheet2. AL/PD left blank.")
                        
                    # Batch Update Sheet1: Status (I/9), AL (H/8), PD (G/7)
                    updates = [{'range': f'I{p_row1}', 'values': [['Active']]}]
                    if al_status:
                        updates.append({'range': f'H{p_row1}', 'values': [[al_status]]})
                    if pd_status:
                        updates.append({'range': f'G{p_row1}', 'values': [[pd_status]]})
                        
                    sheet1.batch_update(updates)
                    print(f"Gspread: Marked pickup truck {p_vin} Active with AL:{al_status} PD:{pd_status}")
                    
                except ValueError:
                    print(f"Gspread: Pickup VIN {p_vin} not found in Sheet1.")
                    
        except Exception as e:
            print(f"Gspread execution error: {e}")
    # ---------------------------------------

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
