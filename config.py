import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", 32141443))
API_HASH = os.getenv("API_HASH", "4f34a89257ac316505f5a47b237454cc")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8835310418:AAGrYPEu8j7MQKumNTrsoQAHp-VeVd6ZXYE")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", -1004364000451))
OWNER_ID = int(os.getenv("OWNER_ID", 8974535424))
