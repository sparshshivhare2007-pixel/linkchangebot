import asyncio
import logging
import os
import re
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from config import *

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG mode on
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== BOT INIT ==========
bot = Client("link_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ========== GLOBAL VARIABLES ==========
usernames_list = []
delay_seconds = 3600
is_running = False
current_index = 0
current_username = None
rotation_task = None
owner_session = None
session_connected = False

# ========== HELPER FUNCTIONS ==========

def parse_delay(time_str):
    time_str = time_str.lower().strip()
    seconds = 0
    
    hour_match = re.search(r'(\d+)\s*(?:hour|hr|h)', time_str)
    if hour_match:
        seconds += int(hour_match.group(1)) * 3600
    
    min_match = re.search(r'(\d+)\s*(?:min|m)', time_str)
    if min_match:
        seconds += int(min_match.group(1)) * 60
    
    sec_match = re.search(r'(\d+)\s*(?:sec|s)', time_str)
    if sec_match:
        seconds += int(sec_match.group(1))
    
    if seconds == 0 and time_str.isdigit():
        seconds = int(time_str) * 60
    
    return max(seconds, 30)

def format_delay(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}hour{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes}min{'s' if minutes > 1 else ''}")
    if secs > 0:
        parts.append(f"{secs}sec{'s' if secs > 1 else ''}")
    
    return ' '.join(parts) if parts else "0sec"

def save_usernames():
    with open("usernames.txt", "w") as f:
        for username in usernames_list:
            f.write(f"{username}\n")

def load_usernames():
    try:
        with open("usernames.txt", "r") as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

# ========== CHANGE USERNAME ==========

async def change_username():
    global current_index, current_username
    
    logger.debug(f"🔄 change_username() called")
    logger.debug(f"📛 usernames_list: {usernames_list}")
    logger.debug(f"🔐 session_connected: {session_connected}")
    
    if not usernames_list:
        logger.error("❌ No usernames in list!")
        return False
    
    if not session_connected or not owner_session:
        logger.error("❌ Session not connected!")
        return False
    
    try:
        username = usernames_list[current_index]
        clean_username = username.replace("@", "").strip()
        
        logger.debug(f"📛 Changing to: @{clean_username}")
        
        await owner_session.set_channel_username(CHANNEL_ID, clean_username)
        
        current_username = clean_username
        current_index = (current_index + 1) % len(usernames_list)
        
        logger.info(f"✅ Username changed to: @{clean_username}")
        
        await bot.send_message(
            OWNER_ID,
            f"✅ **Username Updated!**\n\n"
            f"📛 New: @{clean_username}\n"
            f"📌 Channel: {CHANNEL_ID}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔄 Next: @{usernames_list[current_index] if usernames_list else 'None'}\n"
            f"⏱ Delay: {format_delay(delay_seconds)}"
        )
        return True
        
    except Exception as e:
        logger.error(f"❌ Error changing username: {e}")
        await bot.send_message(OWNER_ID, f"❌ **Error!**\n\n{str(e)}")
        return False

# ========== ROTATION TASK ==========

async def rotation_loop():
    global is_running
    
    logger.info("🔄 Rotation loop started!")
    
    while is_running:
        try:
            success = await change_username()
            if success:
                logger.info(f"⏳ Waiting {format_delay(delay_seconds)}...")
                await asyncio.sleep(delay_seconds)
            else:
                logger.warning("⚠️ Failed, retrying in 5 minutes...")
                await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"❌ Rotation loop error: {e}")
            await asyncio.sleep(60)

# ========== BOT COMMANDS ==========

@bot.on_message(filters.command("start"))
async def start_command(client, message: Message):
    logger.debug(f"📥 /start command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized access from: {message.from_user.id}")
        await message.reply("❌ You are not authorized!")
        return
    
    status_text = "✅ Connected" if session_connected else "❌ Not Connected"
    
    logger.info(f"✅ /start response sent to: {message.from_user.id}")
    
    await message.reply(
        f"🤖 **Link Changer Bot**\n\n"
        f"📌 Channel: `{CHANNEL_ID}`\n"
        f"📛 Usernames: {len(usernames_list)} loaded\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n"
        f"🔐 Session: {status_text}\n\n"
        f"**Commands:**\n"
        f"/connect - Connect owner session\n"
        f"/addusername @name1, @name2 - Bulk add\n"
        f"/done - Finish adding\n"
        f"/setdelay 20min - Set delay\n"
        f"/forcestart - Start rotation\n"
        f"/forcestop - Stop rotation\n"
        f"/change_now - Change now\n"
        f"/status - Check status\n"
        f"/list - Show usernames\n"
        f"/clear - Clear list"
    )

@bot.on_message(filters.command("connect"))
async def connect_session(client, message: Message):
    global owner_session, session_connected
    
    logger.debug(f"📥 /connect command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /connect from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if session_connected:
        logger.info(f"ℹ️ Session already connected")
        await message.reply("✅ Session already connected!")
        return
    
    try:
        logger.info(f"🔄 Attempting to connect session from: {SESSION_PATH}")
        await message.reply("🔄 Connecting to session...")
        
        owner_session = Client(SESSION_PATH, api_id=API_ID, api_hash=API_HASH)
        await owner_session.start()
        
        session_connected = True
        logger.info(f"✅ Owner session connected successfully!")
        
        await message.reply(
            f"✅ **Session Connected!**\n\n"
            f"📁 Session: {SESSION_PATH}\n"
            f"🔐 Status: Active\n\n"
            f"Now you can add usernames:\n"
            f"/addusername @name1, @name2, @name3"
        )
        
    except Exception as e:
        logger.error(f"❌ Session connection error: {e}")
        await message.reply(f"❌ **Failed to connect!**\n\n{str(e)}\n\nMake sure session file exists at: {SESSION_PATH}")

@bot.on_message(filters.command("addusername"))
async def add_username(client, message: Message):
    logger.debug(f"📥 /addusername command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /addusername from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not session_connected:
        logger.warning(f"⚠️ Session not connected")
        await message.reply("❌ Session not connected! Use /connect first.")
        return
    
    if len(message.command) < 2:
        logger.debug(f"ℹ️ No usernames provided")
        await message.reply(
            "❌ **Usage:** /addusername @name1, @name2, @name3\n\n"
            "Examples:\n"
            "/addusername @tech1, @tech2, @tech3\n"
            "/addusername @mybot @testbot @demobot"
        )
        return
    
    text = ' '.join(message.command[1:])
    logger.debug(f"📝 Raw text: {text}")
    
    if ',' in text:
        new_usernames = [name.strip() for name in text.split(',') if name.strip()]
    else:
        new_usernames = [name.strip() for name in text.split() if name.strip()]
    
    logger.debug(f"📛 Parsed usernames: {new_usernames}")
    
    cleaned = []
    for name in new_usernames:
        clean = name.replace("@", "").strip()
        if clean and clean not in usernames_list:
            cleaned.append(clean)
    
    if not cleaned:
        logger.warning(f"⚠️ No valid usernames found")
        await message.reply("❌ No valid usernames found!")
        return
    
    usernames_list.extend(cleaned)
    save_usernames()
    
    logger.info(f"✅ Added {len(cleaned)} usernames. Total: {len(usernames_list)}")
    
    await message.reply(
        f"✅ Added {len(cleaned)} username(s)!\n\n"
        f"📝 **Total:** {len(usernames_list)} usernames\n"
        f"📛 **Added:** {', '.join(['@' + name for name in cleaned])}\n\n"
        f"Type /done when finished"
    )

@bot.on_message(filters.command("done"))
async def done_command(client, message: Message):
    logger.debug(f"📥 /done command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /done from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not usernames_list:
        logger.warning(f"⚠️ No usernames to save")
        await message.reply("❌ No usernames added! Use /addusername first.")
        return
    
    save_usernames()
    logger.info(f"✅ Saved {len(usernames_list)} usernames")
    
    response = f"✅ **Done!** {len(usernames_list)} usernames saved.\n\n"
    response += f"📛 Usernames:\n"
    for i, name in enumerate(usernames_list[:10]):
        response += f"{i+1}. @{name}\n"
    if len(usernames_list) > 10:
        response += f"... and {len(usernames_list) - 10} more\n"
    response += f"\n⏱ Set delay: /setdelay 20min\n"
    response += f"🚀 Start rotation: /forcestart"
    
    await message.reply(response)

@bot.on_message(filters.command("setdelay"))
async def set_delay(client, message: Message):
    logger.debug(f"📥 /setdelay command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /setdelay from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if len(message.command) < 2:
        logger.debug(f"ℹ️ No delay provided")
        await message.reply(
            "❌ **Usage:** /setdelay <time>\n\n"
            "**Examples:**\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 30sec\n"
            "/setdelay 1hour 30min 10sec"
        )
        return
    
    delay_str = ' '.join(message.command[1:])
    delay_seconds = parse_delay(delay_str)
    
    logger.info(f"✅ Delay set to: {format_delay(delay_seconds)} ({delay_seconds} seconds)")
    
    await message.reply(
        f"✅ **Delay set!**\n\n"
        f"⏱ {format_delay(delay_seconds)}\n"
        f"⏰ {delay_seconds} seconds"
    )

@bot.on_message(filters.command("forcestart"))
async def force_start(client, message: Message):
    global is_running, rotation_task
    
    logger.debug(f"📥 /forcestart command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /forcestart from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not session_connected:
        logger.warning(f"⚠️ Session not connected")
        await message.reply("❌ Session not connected! Use /connect first.")
        return
    
    if is_running:
        logger.info(f"ℹ️ Rotation already running")
        await message.reply("⚠️ Rotation already running!")
        return
    
    if not usernames_list:
        logger.warning(f"⚠️ No usernames")
        await message.reply("❌ No usernames! Add first: /addusername")
        return
    
    is_running = True
    rotation_task = asyncio.create_task(rotation_loop())
    
    logger.info(f"🚀 Rotation started with {len(usernames_list)} usernames, delay: {format_delay(delay_seconds)}")
    
    await message.reply(
        f"🚀 **Rotation Started!**\n\n"
        f"📛 Usernames: {len(usernames_list)}\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"📌 Channel: {CHANNEL_ID}\n\n"
        f"First change in {format_delay(delay_seconds)}\n"
        f"Use /forcestop to stop"
    )

@bot.on_message(filters.command("forcestop"))
async def force_stop(client, message: Message):
    global is_running, rotation_task
    
    logger.debug(f"📥 /forcestop command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /forcestop from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not is_running:
        logger.info(f"ℹ️ Rotation already stopped")
        await message.reply("⚠️ Rotation already stopped!")
        return
    
    is_running = False
    
    if rotation_task:
        rotation_task.cancel()
        rotation_task = None
    
    logger.info(f"⏹ Rotation stopped")
    
    await message.reply("⏹ **Rotation Stopped!**")

@bot.on_message(filters.command("change_now"))
async def change_now(client, message: Message):
    logger.debug(f"📥 /change_now command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /change_now from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not session_connected:
        logger.warning(f"⚠️ Session not connected")
        await message.reply("❌ Session not connected! Use /connect first.")
        return
    
    if not usernames_list:
        logger.warning(f"⚠️ No usernames")
        await message.reply("❌ No usernames!")
        return
    
    await message.reply("🔄 Changing username now...")
    success = await change_username()
    
    if success:
        await message.reply(f"✅ Changed to @{current_username}")
    else:
        await message.reply("❌ Failed to change!")

@bot.on_message(filters.command("status"))
async def status_command(client, message: Message):
    logger.debug(f"📥 /status command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /status from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    next_username = usernames_list[current_index] if usernames_list else "None"
    status_text = "✅ Connected" if session_connected else "❌ Not Connected"
    
    logger.info(f"📊 Status requested by: {message.from_user.id}")
    
    await message.reply(
        f"📊 **Bot Status**\n\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n"
        f"🔐 Session: {status_text}\n"
        f"📛 Current: @{current_username or 'None'}\n"
        f"📋 Total: {len(usernames_list)} usernames\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Next: @{next_username}\n"
        f"📍 Index: {current_index + 1}/{len(usernames_list)}\n"
        f"📌 Channel: {CHANNEL_ID}"
    )

@bot.on_message(filters.command("list"))
async def list_usernames(client, message: Message):
    logger.debug(f"📥 /list command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /list from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if not usernames_list:
        logger.warning(f"⚠️ No usernames to list")
        await message.reply("❌ No usernames!")
        return
    
    text = f"📝 **Usernames List** ({len(usernames_list)})\n\n"
    
    for i, name in enumerate(usernames_list):
        marker = "👉 " if i == current_index else "   "
        text += f"{marker}{i+1}. @{name}\n"
        
        if len(text) > 3500:
            text += "\n... and more"
            break
    
    logger.info(f"📋 Listed {len(usernames_list)} usernames")
    await message.reply(text)

@bot.on_message(filters.command("clear"))
async def clear_usernames(client, message: Message):
    logger.debug(f"📥 /clear command received from: {message.from_user.id}")
    
    if message.from_user.id != OWNER_ID:
        logger.warning(f"⚠️ Unauthorized /clear from: {message.from_user.id}")
        await message.reply("❌ Unauthorized!")
        return
    
    if is_running:
        logger.warning(f"⚠️ Cannot clear while running")
        await message.reply("❌ Stop rotation first: /forcestop")
        return
    
    usernames_list.clear()
    save_usernames()
    
    logger.info(f"🗑️ All usernames cleared")
    await message.reply("🗑️ All usernames cleared!")

# ========== MAIN ==========

async def main():
    global usernames_list
    
    logger.info("🚀 Starting Link Changer Bot...")
    logger.info("🐛 DEBUG MODE ENABLED - All commands will be logged")
    
    usernames_list = load_usernames()
    logger.info(f"📛 Loaded {len(usernames_list)} usernames")
    
    await bot.start()
    logger.info("✅ Bot started! Use /connect to connect session.")
    logger.info(f"📌 Channel: {CHANNEL_ID}")
    logger.info(f"⏱ Default Delay: {format_delay(delay_seconds)}")
    
    logger.info("📱 Waiting for commands...")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
