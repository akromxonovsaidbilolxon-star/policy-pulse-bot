def extract_truck_data(raw_text):
    data = {
        "company": "Borderlanders Inc",
        "action_type": "PICKUP",
        "driver_status": "Active",
        "driver_type": "Company driver",
        "driver_name": "",
        "is_team_driver": False,
        "unit_number": "",     # Drop Unit
        "pickup_unit": "",     # New Unit
        "vin": "",
        "pickup_vin": "",
        "plate": "",
        "pickup_plate": "",
        "make": "",
        "year": "",
        "truck_type": "Penske Rental",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "location": "Shop"
    }
    
    text_upper = raw_text.upper()
    if "SWAP" in text_upper or "SWAPPED" in text_upper:
        data["action_type"] = "SWAP"
    elif "TERMINAT" in text_upper:
        data["action_type"] = "TERMINATION"
        data["driver_status"] = "Terminated"
    elif "DROPOFF" in text_upper or "DROP OFF" in text_upper or "DROPPED" in text_upper:
        data["action_type"] = "DROPOFF"
    elif "PICKUP" in text_upper or "PICK UP" in text_upper:
        data["action_type"] = "PICKUP"
        
    # Location mapping
    if "YARD" in text_upper:
        data["location"] = "Yard"
    elif "SHOP" in text_upper or "REPAIR" in text_upper or "ISSUE" in text_upper or "PENSKE" in text_upper:
        data["location"] = "Shop"
    elif "RETURN" in text_upper:
        data["location"] = "Returned"
    elif "HOME" in text_upper:
        data["location"] = "Home"
    elif "VACATION" in text_upper or "LEAVE" in text_upper:
        data["location"] = "Vacation"
    else:
        if data["action_type"] in ["SWAP", "DROPOFF"]:
            data["location"] = "Shop"
        else:
            data["location"] = "Rolling"

    # Company name extraction
    company_match = re.search(r'Company:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if company_match:
        data["company"] = company_match.group(1).strip()
        
    # Date extraction
    date_match = re.search(r'Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', raw_text, re.IGNORECASE)
    if date_match:
        data["event_date"] = date_match.group(1).strip()
        
    # Driver name & team check
    driver_match = re.search(r'Driver name:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if driver_match:
        d_name = driver_match.group(1).strip()
        data["driver_name"] = d_name
        if "/" in d_name or "&" in d_name or "TEAM" in d_name.upper():
            data["is_team_driver"] = True
    else:
        alt_name = re.search(r'[-–]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', raw_text)
        if alt_name:
            data["driver_name"] = alt_name.group(1).strip()

    # Check if it's a SWAP or has a split section
    if "Pick up unit" in raw_text or data["action_type"] == "SWAP":
        parts = re.split(r'Pick up unit', raw_text, flags=re.IGNORECASE)
        drop_section = parts[0]
        pickup_section = parts[1] if len(parts) > 1 else ""

        # Drop Unit details
        drop_unit_match = re.search(r'(?:Drop off unit|Drop unit|Unit)[:\s#]*([0-9]+)', drop_section, re.IGNORECASE)
        if drop_unit_match:
            data["unit_number"] = drop_unit_match.group(1).strip()

        drop_vin = re.search(r'Vin:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_vin:
            data["vin"] = drop_vin.group(1).strip()
        drop_plate = re.search(r'Plate:\s*([A-Z0-9]+)', drop_section, re.IGNORECASE)
        if drop_plate:
            data["plate"] = drop_plate.group(1).strip()

        # Pickup Unit details from second section
        if pickup_section:
            pick_unit_match = re.search(r'[:\s#]*([0-9]+)', pickup_section)
            if pick_unit_match:
                data["pickup_unit"] = pick_unit_match.group(1).strip()

            pick_vin = re.search(r'Vin:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_vin:
                data["pickup_vin"] = pick_vin.group(1).strip()
                
            pick_plate = re.search(r'Plate:\s*([A-Z0-9]+)', pickup_section, re.IGNORECASE)
            if pick_plate:
                data["pickup_plate"] = pick_plate.group(1).strip()
    else:
        # Pure PICKUP or DROPOFF message without split sections
        unit_match = re.search(r'(?:Pick up unit|Unit)[:\s#]*([0-9]+)', raw_text, re.IGNORECASE)
        if unit_match:
            data["pickup_unit"] = unit_match.group(1).strip()
            data["unit_number"] = unit_match.group(1).strip()

        vin_match = re.search(r'Vin:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if vin_match:
            data["pickup_vin"] = vin_match.group(1).strip()
            data["vin"] = vin_match.group(1).strip()

        plate_match = re.search(r'Plate:\s*([A-Z0-9]+)', raw_text, re.IGNORECASE)
        if plate_match:
            data["pickup_plate"] = plate_match.group(1).strip()
            data["plate"] = plate_match.group(1).strip()

    # Common Make/Model/Year parsing
    make_match = re.search(r'Make model year:\s*([^\n]+)', raw_text, re.IGNORECASE)
    if make_match:
        make_val = make_match.group(1).strip()
        data["make"] = make_val
        year_match = re.search(r'(20[0-9]{2})', make_val)
        if year_match:
            data["year"] = year_match.group(1)

    # Truck Type
    text_lower = raw_text.lower()
    if "penske" in text_lower:
        data["truck_type"] = "Penske Rental"
    elif "ryder" in text_lower:
        data["truck_type"] = "Ryder Rental"
    elif "nexgen" in text_lower:
        data["truck_type"] = "Nexgen Rental"
    else:
        data["truck_type"] = "Finance"

    return data
