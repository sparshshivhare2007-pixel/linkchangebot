import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from config import *

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== BOT INIT ==========
bot = Client("link_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
owner_session = Client(SESSION_PATH, api_id=API_ID, api_hash=API_HASH)

# ========== GLOBAL VARIABLES ==========
usernames_list = []
delay_seconds = 3600  # Default 1 hour
is_running = False
current_index = 0
current_username = None
rotation_task = None

# ========== HELPER FUNCTIONS ==========

def parse_delay(time_str):
    """
    Convert delay string to seconds
    Examples:
    20min -> 1200 seconds
    20hour -> 72000 seconds
    2sec -> 2 seconds
    1hour 30min -> 5400 seconds
    20min 30sec -> 1230 seconds
    """
    time_str = time_str.lower().strip()
    seconds = 0
    
    # Extract hours
    hour_match = re.search(r'(\d+)\s*(?:hour|hr|h)', time_str)
    if hour_match:
        seconds += int(hour_match.group(1)) * 3600
    
    # Extract minutes
    min_match = re.search(r'(\d+)\s*(?:min|m)', time_str)
    if min_match:
        seconds += int(min_match.group(1)) * 60
    
    # Extract seconds
    sec_match = re.search(r'(\d+)\s*(?:sec|s)', time_str)
    if sec_match:
        seconds += int(sec_match.group(1))
    
    # If only number given, treat as minutes (backward compatible)
    if seconds == 0 and time_str.isdigit():
        seconds = int(time_str) * 60
    
    # Minimum 30 seconds (to avoid rate limit)
    return max(seconds, 30)

def format_delay(seconds):
    """Format seconds to readable string"""
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
    """Save usernames to file"""
    with open("usernames.txt", "w") as f:
        for username in usernames_list:
            f.write(f"{username}\n")

def load_usernames():
    """Load usernames from file"""
    try:
        with open("usernames.txt", "r") as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

# ========== CHANGE USERNAME FUNCTION ==========

async def change_username():
    global current_index, current_username
    
    if not usernames_list:
        logger.error("❌ No usernames in list!")
        return False
    
    try:
        # Get current username
        username = usernames_list[current_index]
        clean_username = username.replace("@", "").strip()
        
        # Change channel username
        await owner_session.set_channel_username(
            CHANNEL_ID,
            clean_username
        )
        
        current_username = clean_username
        current_index = (current_index + 1) % len(usernames_list)
        
        logger.info(f"✅ Username changed to: @{clean_username}")
        
        # Send notification
        await bot.send_message(
            OWNER_ID,
            f"✅ **Username Updated!**\n\n"
            f"📛 New: @{clean_username}\n"
            f"📌 Channel: {CHANNEL_ID}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔄 Next: {usernames_list[current_index] if usernames_list else 'None'}\n"
            f"⏱ Delay: {format_delay(delay_seconds)}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error changing username: {e}")
        await bot.send_message(
            OWNER_ID,
            f"❌ **Error!**\n\n{str(e)}"
        )
        return False

# ========== ROTATION TASK ==========

async def rotation_loop():
    global is_running
    
    logger.info("🔄 Rotation loop started!")
    
    while is_running:
        try:
            # Change username
            success = await change_username()
            
            if success:
                # Wait for delay
                logger.info(f"⏳ Waiting {format_delay(delay_seconds)}...")
                await asyncio.sleep(delay_seconds)
            else:
                # If failed, wait 5 minutes and retry
                logger.warning("⚠️ Failed, retrying in 5 minutes...")
                await asyncio.sleep(300)
                
        except Exception as e:
            logger.error(f"❌ Rotation loop error: {e}")
            await asyncio.sleep(60)

# ========== BOT COMMANDS ==========

@bot.on_message(filters.command("start"))
async def start_command(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ You are not authorized!")
        return
    
    await message.reply(
        f"🤖 **Link Changer Bot**\n\n"
        f"📌 Channel: `{CHANNEL_ID}`\n"
        f"📛 Usernames: {len(usernames_list)} loaded\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n\n"
        f"**Commands:**\n"
        f"/addusername @name1, @name2, @name3 - Bulk add\n"
        f"/done - Finish adding usernames\n"
        f"/setdelay 20min - Set delay\n"
        f"/setdelay 1hour 30min 10sec - Complex delay\n"
        f"/forcestart - Start rotation\n"
        f"/forcestop - Stop rotation\n"
        f"/change_now - Change immediately\n"
        f"/status - Current status\n"
        f"/list - Show all usernames\n"
        f"/clear - Clear username list"
    )

@bot.on_message(filters.command("addusername"))
async def add_username(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if len(message.command) < 2:
        await message.reply(
            "❌ **Usage:** /addusername @name1, @name2, @name3\n\n"
            "Examples:\n"
            "/addusername @tech1, @tech2, @tech3\n"
            "/addusername @mybot @testbot @demobot"
        )
        return
    
    # Extract all usernames
    text = ' '.join(message.command[1:])
    
    # Split by comma or space
    if ',' in text:
        new_usernames = [name.strip() for name in text.split(',') if name.strip()]
    else:
        new_usernames = [name.strip() for name in text.split() if name.strip()]
    
    # Clean usernames (remove @ if present)
    cleaned = []
    for name in new_usernames:
        clean = name.replace("@", "").strip()
        if clean and clean not in usernames_list:
            cleaned.append(clean)
    
    if not cleaned:
        await message.reply("❌ No valid usernames found!")
        return
    
    usernames_list.extend(cleaned)
    save_usernames()
    
    await message.reply(
        f"✅ Added {len(cleaned)} username(s)!\n\n"
        f"📝 **Total:** {len(usernames_list)} usernames\n"
        f"📛 **Added:** {', '.join(['@' + name for name in cleaned])}\n\n"
        f"Type /done when finished"
    )

@bot.on_message(filters.command("done"))
async def done_command(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if not usernames_list:
        await message.reply("❌ No usernames added! Use /addusername first.")
        return
    
    save_usernames()
    
    await message.reply(
        f"✅ **Done!** {len(usernames_list)} usernames saved.\n\n"
        f"📛 Usernames:\n" + 
        "\n".join([f"{i+1}. @{name}" for i, name in enumerate(usernames_list[:10])]) +
        (f"\n... and {len(usernames_list) - 10} more" if len(usernames_list) > 10 else "") +
        f"\n\n⏱ Set delay: /setdelay 20min\n"
        f"🚀 Start rotation: /forcestart"
    )

@bot.on_message(filters.command("setdelay"))
async def set_delay(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if len(message.command) < 2:
        await message.reply(
            "❌ **Usage:** /setdelay <time>\n\n"
            "**Examples:**\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 30sec\n"
            "/setdelay 1hour 30min 10sec\n"
            "/setdelay 20min 30sec"
        )
        return
    
    delay_str = ' '.join(message.command[1:])
    delay_seconds = parse_delay(delay_str)
    
    await message.reply(
        f"✅ **Delay set!**\n\n"
        f"⏱ {format_delay(delay_seconds)}\n"
        f"⏰ {delay_seconds} seconds"
    )
    
    # If running, restart with new delay
    if is_running:
        await message.reply("🔄 Rotation running - will use new delay from next cycle.")

@bot.on_message(filters.command("forcestart"))
async def force_start(client, message: Message):
    global is_running, rotation_task
    
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if is_running:
        await message.reply("⚠️ Rotation already running!")
        return
    
    if not usernames_list:
        await message.reply("❌ No usernames! Add first: /addusername")
        return
    
    is_running = True
    rotation_task = asyncio.create_task(rotation_loop())
    
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
    
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if not is_running:
        await message.reply("⚠️ Rotation already stopped!")
        return
    
    is_running = False
    
    if rotation_task:
        rotation_task.cancel()
        rotation_task = None
    
    await message.reply("⏹ **Rotation Stopped!**\n\nCurrent username will stay as is.")

@bot.on_message(filters.command("change_now"))
async def change_now(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if not usernames_list:
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
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    next_username = usernames_list[current_index] if usernames_list else "None"
    
    await message.reply(
        f"📊 **Bot Status**\n\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n"
        f"📛 Current: @{current_username or 'None'}\n"
        f"📋 Total: {len(usernames_list)} usernames\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Next: @{next_username}\n"
        f"📍 Index: {current_index + 1}/{len(usernames_list)}\n"
        f"📌 Channel: {CHANNEL_ID}"
    )

@bot.on_message(filters.command("list"))
async def list_usernames(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if not usernames_list:
        await message.reply("❌ No usernames!")
        return
    
    text = f"📝 **Usernames List** ({len(usernames_list)})\n\n"
    
    for i, name in enumerate(usernames_list):
        marker = "👉 " if i == current_index else "   "
        text += f"{marker}{i+1}. @{name}\n"
        
        if len(text) > 3500:
            text += "\n... and more"
            break
    
    await message.reply(text)

@bot.on_message(filters.command("clear"))
async def clear_usernames(client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ Unauthorized!")
        return
    
    if is_running:
        await message.reply("❌ Stop rotation first: /forcestop")
        return
    
    usernames_list.clear()
    save_usernames()
    
    await message.reply("🗑️ All usernames cleared!")

# ========== MAIN ==========

async def main():
    global usernames_list
    
    logger.info("🚀 Starting Link Changer Bot...")
    
    # Load usernames
    usernames_list = load_usernames()
    logger.info(f"📛 Loaded {len(usernames_list)} usernames")
    
    # Start sessions
    await bot.start()
    await owner_session.start()
    logger.info("✅ Sessions started!")
    
    logger.info(f"📌 Channel: {CHANNEL_ID}")
    logger.info(f"⏱ Delay: {format_delay(delay_seconds)}")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
