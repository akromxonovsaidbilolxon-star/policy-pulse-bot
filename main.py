def extract_truck_data(raw_text):
    data = {
        "company": "Borderlanders Inc",
        "action_type": "PICKUP",
        "driver_name": "",
        "unit_number": "",
        "vin": "",
        "plate": "",
        "make": "",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "",
        "notes": f"Telegram - {raw_text[:100]}"
    }
    
    text_upper = raw_text.upper()
    if "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
    elif "SHOP" in text_upper:
        data["action_type"] = "SHOP"
    elif "RETURN" in text_upper:
        data["action_type"] = "RETURNED"
        
    # Extract Date
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    # Extract Driver Name
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        data["driver_name"] = driver_match.group(1).strip()
        
    # Extract Unit Number (handles both drop off and pick up labels)
    unit_match = re.search(r'(?:Unit|Drop off unit|Pick up unit|Truck)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
    if unit_match:
        data["unit_number"] = unit_match.group(1).strip()
        
    vin_match = re.search(r'Vin:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if vin_match:
        data["vin"] = vin_match.group(1).strip()
        
    plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
    if plate_match:
        data["plate"] = plate_match.group(1).strip()
        
    make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if make_match:
        data["make"] = make_match.group(1).strip()
        
    loc_match = re.search(r'Location:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if loc_match:
        data["location"] = loc_match.group(1).strip()

    return data
