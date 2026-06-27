import os, json, base64
from dotenv import load_dotenv
load_dotenv()
import gspread
from google.oauth2.service_account import Credentials

GSHEET_ID = os.environ["GSHEET_ID"]
GSHEED_KEY_B64 = os.environ["GSHEET_KEY_B64"]

creds = Credentials.from_service_account_info(
    json.loads(base64.b64decode(GSHEED_KEY_B64)),
    scopes=["https://spreadsheets.google.com/feeds"])
sheet = gspread.authorize(creds).open_by_key(GSHEET_ID).sheet1

sheet.append_row(["2025-01-01T00:00:00", "BTCUSDT", "LONG", "100000", "110000", "TP", "10.0", "1100.0"])
print("OK — row appended to Google Sheet")
