import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DEFAULT_TARGET_ID = int(
    os.getenv("DEFAULT_TARGET_ID", "-1004364000451")
)

SESSION_FILE = "session_data.json"
TARGET_FILE = "target.json"
USERNAMES_FILE = "usernames.txt"

if not API_ID:
    raise RuntimeError("API_ID missing in .env")

if not API_HASH:
    raise RuntimeError("API_HASH missing in .env")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in .env")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID missing in .env")
