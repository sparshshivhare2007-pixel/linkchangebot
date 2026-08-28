import os
from dotenv import load_dotenv

load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Logger Group ID (for payment notifications)
LOGGER_GROUP_ID = int(os.getenv("LOGGER_GROUP_ID", "0"))

# Default target ID (optional)
DEFAULT_TARGET_ID = int(os.getenv("DEFAULT_TARGET_ID", "0"))

# File paths
SESSION_FILE = "session_data.json"
TARGET_FILE = "target.json"
USERNAMES_FILE = "usernames.txt"

# Bot Links (for inline buttons)
OWNER_LINK = os.getenv("OWNER_LINK", "https://t.me/yourowner")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/yourchannel")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/yoursupport")

# Start Image URL
START_IMAGE_URL = os.getenv("START_IMAGE_URL", "https://telegra.ph/file/your-image-url-here.jpg")

# Validate required variables
if not API_ID:
    raise RuntimeError("❌ API_ID missing in .env file")

if not API_HASH:
    raise RuntimeError("❌ API_HASH missing in .env file")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env file")

if not OWNER_ID:
    raise RuntimeError("❌ OWNER_ID missing in .env file")

if not LOGGER_GROUP_ID:
    raise RuntimeError("❌ LOGGER_GROUP_ID missing in .env file")

print("✅ Configuration loaded successfully!")
print(f"📊 Logger Group ID: {LOGGER_GROUP_ID}")
print(f"👑 Owner ID: {OWNER_ID}")
print(f"🔗 Channel Link: {CHANNEL_LINK}")
print(f"🆘 Support Link: {SUPPORT_LINK}")