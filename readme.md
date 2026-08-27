# Telegram Link Changer Bot

A powerful Telegram bot for automatic username rotation with payment integration.

## ✨ Features

- 🔄 Automatic username rotation
- 💳 Payment system with INR plans
- 👑 Sudo user management
- 📊 Logger group integration
- 🎨 Beautiful animated UI
- 👥 User management
- 📈 Real-time status

## 💰 Plans

| Plan | Price |
|------|-------|
| 7 Days | ₹150 |
| 14 Days | ₹260 |
| 30 Days | ₹500 |
| Unlimited | ₹900 |

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/telegram-link-changer.git
cd telegram-link-changer
```
### 2. Install Dependencies
bash
pip install -r requirements.txt
3. Configure Environment
Copy .env.example to .env and fill in your credentials:

bash
cp .env.example .env
nano .env
Required variables:

API_ID - From my.telegram.org

API_HASH - From my.telegram.org

BOT_TOKEN - From @BotFather

OWNER_ID - Your Telegram user ID

LOGGER_GROUP_ID - Group ID for payment notifications

4. Add QR Code
Place your payment QR code as qr.jpg in the root directory.

5. Run the Bot
bash
python bot.py
📝 Commands
User Commands
/start - Show bot menu

/status - Show bot status

/list - View all usernames

/current - Show current username

Admin Commands
/connect <session> - Connect Telegram session

/addchannel <link> - Set channel target

/addgroup <link> - Set group target

/addusername @name1, @name2 - Add usernames

/done - Finalize username list

/setdelay 20min - Set rotation delay

/forcestart - Start rotation

/forcestop - Stop rotation

/change_now - Change to next username

/clear - Clear username list

Payment Commands
/pending - View pending payments

/approve <id> - Approve payment

/reject <id> - Reject payment

/users - List all users

Sudo Commands
/addsudo <user_id> - Add sudo user

/rmsudo <user_id> - Remove sudo user

/sudolist - List sudo users

📁 Files
text
telegram-link-changer/
├── bot.py              # Main bot
├── config.py           # Configuration
├── .env                # Environment variables
├── requirements.txt    # Dependencies
├── qr.jpg             # Payment QR code
├── README.md          # Documentation
└── data/              # Data files (auto-generated)
    ├── users.json
    ├── pending_payments.json
    ├── sudo_users.json
    ├── session_data.json
    ├── target.json
    └── usernames.txt
🛠️ Technologies
Python 3.8+

python-telegram-bot

Telethon

Asyncio

python-dotenv

📞 Support
For support, contact the bot owner.

📄 License
MIT License

text

---

## 📁 .env.example

Create a `.env.example` file for reference:

```env
# Telegram API Credentials (from my.telegram.org)
API_ID=123456
API_HASH=your_api_hash_here

# Bot Token (from @BotFather)
BOT_TOKEN=your_bot_token_here

# Owner ID (your Telegram user ID)
OWNER_ID=123456789

# Logger Group ID (where payment notifications will be sent)
LOGGER_GROUP_ID=-1001234567890

# Default Target ID (optional - for channels/groups)
DEFAULT_TARGET_ID=-1004364000451
🚀 Deployment Commands
bash
# Clone repository
git clone https://github.com/yourusername/telegram-link-changer.git
cd telegram-link-changer

# Create virtual environment (optional)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Fill in your credentials

# Upload QR code
# Place qr.jpg in root directory

# Run bot
python bot.py

# For background running (Linux)
nohup python bot.py &

# For background running with screen
screen -S bot
python bot.py
# Press Ctrl+A, then D to detach

# To reattach to screen
screen -r bot

# For PM2 (production)
npm install -g pm2
pm2 start bot.py --interpreter python3 --name "telegram-bot"
pm2 save
pm2 startup
🔒 Security Tips
Never commit .env file to GitHub

Use .gitignore to exclude sensitive files

Use environment variables for all sensitive data

Regularly backup your data files

Use strong bot tokens

Keep your API credentials secure

The bot is now ready for deployment with all configurations properly set up! 🎉


````
