import asyncio
import re
import json
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from config import *

# ========== BOT INIT ==========
print("🚀 Starting Link Changer Bot (Telethon)...")
# NOTE: Do NOT call .start(...) here. Creating the client without
# connecting keeps it bound to the loop that will actually run it.
bot = TelegramClient('bot_session', API_ID, API_HASH)

# ========== GLOBAL VARIABLES ==========
usernames_list = []
delay_seconds = 3600
is_running = False
current_index = 0
current_username = None
rotation_task = None
owner_session = None
session_connected = False

# ========== SESSION STORAGE ==========
SESSION_FILE = "session_data.json"

def save_session_string(sess_str):
    with open(SESSION_FILE, "w") as f:
        json.dump({"session_string": sess_str}, f)
    print("✅ Session string saved")

def load_session_string():
    try:
        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
            return data.get("session_string")
    except:
        return None

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

    print(f"🔹 Changing username...")

    if not usernames_list:
        print("❌ No usernames!")
        return False

    if not session_connected or not owner_session:
        print("❌ Session not connected!")
        return False

    try:
        username = usernames_list[current_index]
        clean_username = username.replace("@", "").strip()

        print(f"🔹 Changing to: @{clean_username}")

        # Get channel entity
        channel = await owner_session.get_entity(CHANNEL_ID)

        # Change username
        await owner_session.edit_channel_username(channel, clean_username)

        current_username = clean_username
        current_index = (current_index + 1) % len(usernames_list)

        print(f"✅ Changed to: @{clean_username}")

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

    except FloodWaitError as e:
        print(f"⏳ Flood wait: {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        await bot.send_message(OWNER_ID, f"❌ **Error!**\n\n{str(e)}")
        return False

# ========== ROTATION TASK ==========

async def rotation_loop():
    global is_running

    print("🔄 Rotation started!")

    while is_running:
        try:
            success = await change_username()
            if success:
                print(f"⏳ Waiting {format_delay(delay_seconds)}...")
                await asyncio.sleep(delay_seconds)
            else:
                print("⚠️ Retrying in 5 minutes...")
                await asyncio.sleep(300)
        except Exception as e:
            print(f"❌ Loop error: {e}")
            await asyncio.sleep(60)

# ========== BOT COMMANDS ==========

@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    print(f"📥 /start from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    status = "✅ Connected" if session_connected else "❌ Not Connected"

    await event.reply(
        f"🤖 **Link Changer Bot**\n\n"
        f"📌 Channel: `{CHANNEL_ID}`\n"
        f"📛 Usernames: {len(usernames_list)}\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n"
        f"🔐 Session: {status}\n\n"
        f"**Commands:**\n"
        f"/connect <session_string> - Connect session\n"
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

@bot.on(events.NewMessage(pattern='/connect'))
async def connect_session(event):
    global owner_session, session_connected

    print(f"📥 /connect from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if session_connected:
        await event.reply("✅ Session already connected!")
        return

    # Get session string from command
    parts = event.raw_text.split()
    session_string = None

    if len(parts) > 1:
        session_string = parts[1]
        save_session_string(session_string)
        await event.reply("🔄 Connecting with session...")
    else:
        saved = load_session_string()
        if saved:
            session_string = saved
            await event.reply("🔄 Loading saved session...")
        else:
            await event.reply(
                "❌ No session string!\n\n"
                "Usage: `/connect <session_string>`"
            )
            return

    try:
        owner_session = TelegramClient(
            'owner_session',
            API_ID,
            API_HASH,
            session_string=session_string
        )
        await owner_session.start()
        session_connected = True

        print("✅ Session connected!")
        await event.reply(
            f"✅ **Session Connected!**\n\n"
            f"🔐 Status: Active\n"
            f"📌 Channel: {CHANNEL_ID}\n\n"
            f"Now add usernames:\n"
            f"/addusername @name1, @name2"
        )

    except Exception as e:
        print(f"❌ Session error: {e}")
        session_connected = False
        await event.reply(f"❌ Connection failed!\n\n{str(e)}")

@bot.on(events.NewMessage(pattern='/addusername'))
async def add_username(event):
    print(f"📥 /addusername from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not session_connected:
        await event.reply("❌ Connect first: /connect")
        return

    text = event.raw_text.replace('/addusername', '').strip()

    if not text:
        await event.reply("❌ Usage: /addusername @name1, @name2, @name3")
        return

    if ',' in text:
        new_usernames = [n.strip() for n in text.split(',') if n.strip()]
    else:
        new_usernames = [n.strip() for n in text.split() if n.strip()]

    cleaned = []
    for name in new_usernames:
        clean = name.replace("@", "").strip()
        if clean and clean not in usernames_list:
            cleaned.append(clean)

    if not cleaned:
        await event.reply("❌ No valid usernames!")
        return

    usernames_list.extend(cleaned)
    save_usernames()

    await event.reply(
        f"✅ Added {len(cleaned)} username(s)!\n\n"
        f"📝 Total: {len(usernames_list)}\n"
        f"📛 Added: {', '.join(['@' + n for n in cleaned])}\n\n"
        f"Type /done when finished"
    )

@bot.on(events.NewMessage(pattern='/done'))
async def done_command(event):
    print(f"📥 /done from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not usernames_list:
        await event.reply("❌ No usernames! Use /addusername")
        return

    save_usernames()

    response = f"✅ Done! {len(usernames_list)} usernames saved.\n\n"
    for i, name in enumerate(usernames_list[:10]):
        response += f"{i+1}. @{name}\n"
    if len(usernames_list) > 10:
        response += f"... and {len(usernames_list) - 10} more\n"
    response += f"\nSet delay: /setdelay 20min\n"
    response += f"Start: /forcestart"

    await event.reply(response)

@bot.on(events.NewMessage(pattern='/setdelay'))
async def set_delay(event):
    print(f"📥 /setdelay from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    text = event.raw_text.replace('/setdelay', '').strip()

    if not text:
        await event.reply(
            "❌ Usage: /setdelay 20min\n\n"
            "Examples:\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 30sec\n"
            "/setdelay 1hour 30min"
        )
        return

    global delay_seconds
    delay_seconds = parse_delay(text)

    await event.reply(
        f"✅ Delay set!\n\n"
        f"⏱ {format_delay(delay_seconds)}\n"
        f"⏰ {delay_seconds} seconds"
    )

@bot.on(events.NewMessage(pattern='/forcestart'))
async def force_start(event):
    global is_running, rotation_task

    print(f"📥 /forcestart from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not session_connected:
        await event.reply("❌ Connect first: /connect")
        return

    if is_running:
        await event.reply("⚠️ Already running!")
        return

    if not usernames_list:
        await event.reply("❌ Add usernames first: /addusername")
        return

    is_running = True
    rotation_task = asyncio.create_task(rotation_loop())

    await event.reply(
        f"🚀 **Rotation Started!**\n\n"
        f"📛 Usernames: {len(usernames_list)}\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"📌 Channel: {CHANNEL_ID}"
    )

@bot.on(events.NewMessage(pattern='/forcestop'))
async def force_stop(event):
    global is_running, rotation_task

    print(f"📥 /forcestop from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not is_running:
        await event.reply("⚠️ Already stopped!")
        return

    is_running = False
    if rotation_task:
        rotation_task.cancel()
        rotation_task = None

    await event.reply("⏹ **Rotation Stopped!**")

@bot.on(events.NewMessage(pattern='/change_now'))
async def change_now(event):
    print(f"📥 /change_now from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not session_connected:
        await event.reply("❌ Connect first: /connect")
        return

    if not usernames_list:
        await event.reply("❌ No usernames!")
        return

    await event.reply("🔄 Changing...")
    success = await change_username()

    if success:
        await event.reply(f"✅ Changed to @{current_username}")
    else:
        await event.reply("❌ Failed!")

@bot.on(events.NewMessage(pattern='/status'))
async def status_command(event):
    print(f"📥 /status from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    next_username = usernames_list[current_index] if usernames_list else "None"

    await event.reply(
        f"📊 **Status**\n\n"
        f"🔄 Status: {'✅ Running' if is_running else '⏹ Stopped'}\n"
        f"🔐 Session: {'✅ Connected' if session_connected else '❌ Not Connected'}\n"
        f"📛 Current: @{current_username or 'None'}\n"
        f"📋 Total: {len(usernames_list)}\n"
        f"⏱ Delay: {format_delay(delay_seconds)}\n"
        f"🔄 Next: @{next_username}\n"
        f"📍 Index: {current_index + 1}/{len(usernames_list)}"
    )

@bot.on(events.NewMessage(pattern='/list'))
async def list_usernames(event):
    print(f"📥 /list from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if not usernames_list:
        await event.reply("❌ No usernames!")
        return

    text = f"📝 **Usernames** ({len(usernames_list)})\n\n"
    for i, name in enumerate(usernames_list):
        marker = "👉 " if i == current_index else "   "
        text += f"{marker}{i+1}. @{name}\n"

    await event.reply(text)

@bot.on(events.NewMessage(pattern='/clear'))
async def clear_usernames(event):
    print(f"📥 /clear from: {event.sender_id}")

    if event.sender_id != OWNER_ID:
        await event.reply("❌ Unauthorized!")
        return

    if is_running:
        await event.reply("❌ Stop first: /forcestop")
        return

    usernames_list.clear()
    save_usernames()
    await event.reply("🗑️ All cleared!")

# ========== AUTO-CONNECT ==========

async def auto_connect():
    global owner_session, session_connected

    saved = load_session_string()
    if saved:
        print("🔄 Auto-connecting session...")
        try:
            owner_session = TelegramClient(
                'owner_session',
                API_ID,
                API_HASH,
                session_string=saved
            )
            await owner_session.start()
            session_connected = True
            print("✅ Auto-connected!")
            return True
        except Exception as e:
            print(f"❌ Auto-connect failed: {e}")
            return False
    return False

# ========== MAIN ==========

async def main():
    global usernames_list

    print("=" * 50)
    print("🚀 Link Changer Bot (Telethon)")
    print("=" * 50)

    usernames_list = load_usernames()
    print(f"📛 Loaded {len(usernames_list)} usernames")

    # Connect the bot HERE, inside the loop that will actually drive it.
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Bot started!")
    print(f"📌 Channel: {CHANNEL_ID}")
    print(f"⏱ Delay: {format_delay(delay_seconds)}")
    print("=" * 50)

    await auto_connect()

    print("📱 Waiting for commands...")
    print("=" * 50)

    await bot.run_until_disconnected()

if __name__ == "__main__":
    # Use the client's OWN loop instead of asyncio.run().
    # This is Telethon's recommended fix for:
    # "RuntimeError: The asyncio event loop must not change after connection"
    # It guarantees the loop the client was created with is the same
    # loop that drives main(), so there's never a mismatch.
    with bot:
        bot.loop.run_until_complete(main())
