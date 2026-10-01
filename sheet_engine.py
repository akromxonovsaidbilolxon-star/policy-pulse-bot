import json
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Column Index Reference (0-based) matching your spreadsheet layout
COL_COMPANY = 0
COL_DRIVER_STATUS = 1
COL_DRIVER_TYPE = 2
COL_DRIVER_NAME = 3
COL_DRIVER_EFF = 4
COL_DRIVER_TERM = 5
COL_FLEET_POLICY_1 = 6
COL_TRUCK_STATUS = 7
COL_PLATE = 8
COL_ST = 9
COL_UNIT = 10
COL_MAKE = 11
COL_YEAR = 12
COL_VIN = 13
COL_TRUCK_TYPE = 14
COL_TRUCK_EFF = 15
COL_POLICY_EFF = 16
COL_POLICY_EXP = 17
COL_TRUCK_TERM = 18
COL_FLEET_POLICY_2 = 19
COL_VALUE = 20
COL_LOCATION = 21

class FleetSheetManager:
    def __init__(self, spreadsheet_id: str, worksheet_name: str, audit_worksheet_name: str = "Audit Log", creds_path: str = None, creds_json: str = None):
        if creds_json:
            service_account_info = json.loads(creds_json)
            self.creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        elif creds_path and os.path.exists(creds_path):
            self.creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        else:
            raise ValueError("No valid credentials found. Set GOOGLE_CREDENTIALS_JSON or provide credentials.json.")

        self.client = gspread.authorize(self.creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        self.sheet = self.spreadsheet.worksheet(worksheet_name)
        
        # Load or create Audit Log worksheet
        try:
            self.audit_sheet = self.spreadsheet.worksheet(audit_worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            self.audit_sheet = self.spreadsheet.add_worksheet(title=audit_worksheet_name, rows=1000, cols=10)
            self.audit_sheet.append_row([
                "Timestamp", "Unit #", "Company", "Action", 
                "Drivers Involved", "Location", "Status Change Details", "Raw Message"
            ])

    def log_audit(self, unit: str, company: str, action: str, drivers: list, location: str, details: str, raw_text: str):
        driver_str = ", ".join([f"{d.get('name', '')} ({d.get('team_tag', 'solo')})".strip() for d in drivers])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audit_sheet.append_row([
            timestamp, unit, company, action, driver_str, location, details, raw_text
        ])

    def process_event(self, event_data: dict, raw_text: str = "") -> str:
        all_rows = self.sheet.get_all_values()
        unit_target = str(event_data.get("unit_number", "")).strip()
        company = event_data.get("company_name", "").strip()
        action = event_data.get("action", "pickup").lower()
        drivers = event_data.get("drivers", [])
        eff_date = event_data.get("effective_date", datetime.today().strftime("%m/%d/%Y"))
        location = event_data.get("location", "Rolling" if action == "pickup" else "Shop")

        matching_indices = [
            idx for idx, row in enumerate(all_rows)
            if len(row) > COL_UNIT and row[COL_UNIT].strip() == unit_target
        ]

        specs = {
            "plate": "", "st": "", "make": "", "year": "",
            "vin": "", "type": "", "value": "", "company": company
        }
        status_changes = []

        if matching_indices:
            last_idx = matching_indices[-1]
            last_row = all_rows[last_idx]

            specs["plate"] = last_row[COL_PLATE] if len(last_row) > COL_PLATE else ""
            specs["st"] = last_row[COL_ST] if len(last_row) > COL_ST else ""
            specs["make"] = last_row[COL_MAKE] if len(last_row) > COL_MAKE else ""
            specs["year"] = last_row[COL_YEAR] if len(last_row) > COL_YEAR else ""
            specs["vin"] = last_row[COL_VIN] if len(last_row) > COL_VIN else ""
            specs["type"] = last_row[COL_TRUCK_TYPE] if len(last_row) > COL_TRUCK_TYPE else ""
            specs["value"] = last_row[COL_VALUE] if len(last_row) > COL_VALUE else ""
            if not specs["company"] and len(last_row) > COL_COMPANY:
                specs["company"] = last_row[COL_COMPANY]

            batch_updates = []
            for idx in matching_indices:
                row = all_rows[idx]
                r_num = idx + 1

                curr_t_status = row[COL_TRUCK_STATUS].strip() if len(row) > COL_TRUCK_STATUS else ""
                curr_d_status = row[COL_DRIVER_STATUS].strip() if len(row) > COL_DRIVER_STATUS else ""

                if action == "pickup":
                    if curr_t_status.lower() == "active":
                        batch_updates.append({"range": f"H{r_num}", "values": [[""]]})
                        status_changes.append(f"Row {r_num}: Truck Status cleared")
                        if len(row) > COL_TRUCK_TERM and not row[COL_TRUCK_TERM]:
                            batch_updates.append({"range": f"S{r_num}", "values": [[eff_date]]})
                            status_changes.append(f"Row {r_num}: Truck Term set to {eff_date}")

                    if curr_d_status.lower() == "active":
                        batch_updates.append({"range": f"B{r_num}", "values": [[""]]})
                        status_changes.append(f"Row {r_num}: Driver Status cleared")
                        if len(row) > COL_DRIVER_TERM and not row[COL_DRIVER_TERM]:
                            batch_updates.append({"range": f"F{r_num}", "values": [["changed unit"]]})
                            status_changes.append(f"Row {r_num}: Driver Term set to 'changed unit'")

                elif action in ["drop", "returned"]:
                    if curr_t_status.lower() == "active":
                        batch_updates.append({"range": f"H{r_num}", "values": [["Inactive"]]})
                        batch_updates.append({"range": f"V{r_num}", "values": [[location or "Shop"]]})
                        status_changes.append(f"Row {r_num}: Truck set to Inactive, location set to {location or 'Shop'}")
                    if curr_d_status.lower() == "active":
                        batch_updates.append({"range": f"B{r_num}", "values": [[""]]})
                        status_changes.append(f"Row {r_num}: Driver Status cleared")
                        if len(row) > COL_DRIVER_TERM and not row[COL_DRIVER_TERM]:
                            batch_updates.append({"range": f"F{r_num}", "values": [["dropped"]]})
                            status_changes.append(f"Row {r_num}: Driver Term set to 'dropped'")

            if batch_updates:
                self.sheet.batch_update([
                    {"range": u["range"], "values": u["values"]} for u in batch_updates
                ])

            insert_pos = last_idx + 2
        else:
            insert_pos = len(all_rows) + 1

        inserted_count = 0
        if action == "pickup" or not matching_indices:
            new_rows = []
            for i, driver in enumerate(drivers):
                d_name = driver.get("name", "").strip()
                tag = driver.get("team_tag", "").strip()
                full_name = f"{d_name} {tag}".strip() if tag else d_name

                truck_status_entry = "Active" if (i == len(drivers) - 1 and action == "pickup") else ""
                loc_entry = location if (i == len(drivers) - 1 and action == "pickup") else ""

                row_data = [
                    specs["company"],                        # Company name
                    "Active" if action == "pickup" else "",  # Driver Status
                    "Company driver",                         # Driver type
                    full_name,                                # Driver Name
                    eff_date,                                 # Driver Effective Date
                    "",                                       # Driver Termination Date
                    "",                                       # Fleet Policy
                    truck_status_entry,                       # Truck Status
                    specs["plate"],                           # Plate #
                    specs["st"],                              # ST
                    unit_target,                              # Unit
                    specs["make"],                            # Make
                    specs["year"],                            # Year
                    specs["vin"],                             # VIN
                    specs["type"],                            # Truck Type
                    eff_date,                                 # Truck Effective date
                    "",                                       # Policy Effective Date
                    "",                                       # Expiration Date
                    "",                                       # Truck Termination date
                    "",                                       # Fleet Policy
                    specs["value"],                           # Value
                    loc_entry                                 # Location
                ]
                new_rows.append(row_data)

            self.sheet.insert_rows(new_rows, row=insert_pos)
            inserted_count = len(new_rows)
            status_changes.append(f"Inserted {inserted_count} new row(s) starting at line {insert_pos}")

        change_summary = "; ".join(status_changes) if status_changes else "No status changes"

        # Log action into Audit Log tab
        self.log_audit(
            unit=unit_target,
            company=specs["company"],
            action=action,
            drivers=drivers,
            location=location,
            details=change_summary,
            raw_text=raw_text
        )

        return f"Unit {unit_target} processed. {change_summary}."
