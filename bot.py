import asyncio
import json
import os
import re
from typing import Optional, Dict
from datetime import datetime, timedelta
from telethon import utils
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import UpdateUsernameRequest
from telethon.errors import (
    FloodWaitError,
    UsernameInvalidError,
    UsernameOccupiedError,
    RPCError,
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config


# ============================================================
# UI HELPERS
# ============================================================

def format_header(title: str, emoji: str = "🤖") -> str:
    """Create a formatted header with emoji and border."""
    border = "═" * 38
    return f"""
┌{border}┐
│ {emoji}  {title}  │
└{border}┘
"""


def format_section(title: str, content: str, emoji: str = "📌") -> str:
    """Create a formatted section with title and content."""
    return f"""
┌─ {emoji} {title}
│
{content}
└─"""


def format_key_value(key: str, value: str, emoji: str = "•") -> str:
    """Format a key-value pair with proper alignment."""
    return f"  {emoji} {key}: {value}"


def format_success(message: str) -> str:
    """Format a success message."""
    return f"""
┌─ ✅ SUCCESS
│
{message}
└─"""


def format_error(message: str) -> str:
    """Format an error message."""
    return f"""
┌─ ❌ ERROR
│
{message}
└─"""


def format_info(message: str) -> str:
    """Format an info message."""
    return f"""
┌─ ℹ️ INFO
│
{message}
└─"""


def format_status(status: str, is_good: bool = True) -> str:
    """Format a status indicator."""
    icon = "🟢" if is_good else "🔴"
    return f"{icon} {status}"


def format_list(items: list, title: str = "LIST") -> str:
    """Format a list of items with numbering."""
    if not items:
        return "📭 Empty"
    
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item}")
    
    return f"""
┌─ 📋 {title}
│
{chr(10).join(lines)}
└─"""


def format_delay(seconds: int) -> str:
    """Format delay in human-readable form."""
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else "0s"


# ============================================================
# FILE FUNCTIONS
# ============================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        save_json(filename, default)
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_usernames():
    if not os.path.exists(config.USERNAMES_FILE):
        return []

    with open(config.USERNAMES_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_usernames(names):
    with open(config.USERNAMES_FILE, "w", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")


# ============================================================
# APPROVAL SYSTEM
# ============================================================

APPROVED_FILE = "approved_users.json"

def load_approved_users():
    """Load approved users from file."""
    if not os.path.exists(APPROVED_FILE):
        save_approved_users({})
        return {}
    
    try:
        with open(APPROVED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_approved_users(data):
    """Save approved users to file."""
    with open(APPROVED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def parse_approve_time(time_str: str) -> Optional[int]:
    """Parse approval time string and return seconds."""
    time_str = time_str.lower().strip()
    
    # Check for unlimited
    if time_str in ["unlimited", "∞", "infinite", "forever", "permanent"]:
        return -1  # -1 means unlimited
    
    # Patterns for time parsing
    patterns = [
        (r"(\d+)\s*day", 86400),
        (r"(\d+)\s*days", 86400),
        (r"(\d+)\s*hr", 3600),
        (r"(\d+)\s*hours?", 3600),
        (r"(\d+)\s*min", 60),
        (r"(\d+)\s*mins?", 60),
        (r"(\d+)\s*sec", 1),
        (r"(\d+)\s*secs?", 1),
    ]
    
    total_seconds = 0
    matched = False
    
    for pattern, multiplier in patterns:
        matches = re.findall(pattern, time_str)
        for match in matches:
            matched = True
            total_seconds += int(match) * multiplier
    
    if not matched:
        return None
    
    return total_seconds


def is_user_approved(user_id: int) -> bool:
    """Check if user is approved and not expired."""
    if user_id == config.OWNER_ID:
        return True  # Owner is always approved
    
    approved_data = load_approved_users()
    user_data = approved_data.get(str(user_id))
    
    if not user_data:
        return False
    
    # Check if unlimited
    if user_data.get("unlimited", False):
        return True
    
    # Check expiration
    expiry = user_data.get("expiry")
    if not expiry:
        return False
    
    try:
        expiry_time = datetime.fromisoformat(expiry)
        return datetime.now() < expiry_time
    except:
        return False


def get_user_approval_info(user_id: int) -> Dict:
    """Get user approval information."""
    if user_id == config.OWNER_ID:
        return {"approved": True, "unlimited": True, "expiry": None, "is_owner": True}
    
    approved_data = load_approved_users()
    user_data = approved_data.get(str(user_id))
    
    if not user_data:
        return {"approved": False, "unlimited": False, "expiry": None, "is_owner": False}
    
    return {
        "approved": True,
        "unlimited": user_data.get("unlimited", False),
        "expiry": user_data.get("expiry"),
        "is_owner": False
    }


def approve_user(user_id: int, time_str: str) -> Dict:
    """Approve a user with given time."""
    approved_data = load_approved_users()
    user_id_str = str(user_id)
    
    # Parse time
    seconds = parse_approve_time(time_str)
    
    if seconds is None:
        return {"success": False, "message": "Invalid time format!"}
    
    if seconds == -1:  # Unlimited
        approved_data[user_id_str] = {
            "unlimited": True,
            "expiry": None,
            "approved_at": datetime.now().isoformat()
        }
        save_approved_users(approved_data)
        return {
            "success": True, 
            "message": f"User {user_id} approved for UNLIMITED time!",
            "duration": "unlimited"
        }
    
    # Calculate expiry
    expiry_time = datetime.now() + timedelta(seconds=seconds)
    approved_data[user_id_str] = {
        "unlimited": False,
        "expiry": expiry_time.isoformat(),
        "approved_at": datetime.now().isoformat(),
        "duration_seconds": seconds
    }
    
    save_approved_users(approved_data)
    
    return {
        "success": True,
        "message": f"User {user_id} approved for {format_delay(seconds)}!",
        "duration": format_delay(seconds),
        "expiry": expiry_time.isoformat()
    }


def revoke_user(user_id: int) -> bool:
    """Revoke a user's approval."""
    approved_data = load_approved_users()
    user_id_str = str(user_id)
    
    if user_id_str in approved_data:
        del approved_data[user_id_str]
        save_approved_users(approved_data)
        return True
    return False


# ============================================================
# GLOBAL DATA
# ============================================================

session_data = load_json(config.SESSION_FILE, {"session": ""})

target_data = load_json(
    config.TARGET_FILE,
    {
        "target_id": config.DEFAULT_TARGET_ID,
        "target_type": "channel",
        "target_link": ""
    }
)

usernames = load_usernames()
delay_seconds = 60
rotation_task: Optional[asyncio.Task] = None
client: Optional[TelegramClient] = None
current_index = 0
entity_cache_loaded = False


# ============================================================
# OWNER CHECK WITH APPROVAL SYSTEM
# ============================================================

def is_owner(update):
    if not update.effective_user:
        return False
    return update.effective_user.id == config.OWNER_ID


def is_authorized(update):
    """Check if user is owner OR approved user."""
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    return user_id == config.OWNER_ID or is_user_approved(user_id)


async def owner_only(update):
    """Check if user is owner only."""
    if not is_owner(update):
        if update.message:
            # Owner contact information with buttons
            owner_contact = f"""
┌─ ❌ ERROR
│
You are not authorized to use this bot.

┌─ 👑 CONTACT OWNER
│
  • Owner: @oyeeee
  • Click below to contact the owner
  • Ask for approval to use this bot
└─"""

            keyboard = [
                [InlineKeyboardButton("📩 Contact Owner", url=f"tg://user?id={config.OWNER_ID}")],
                [InlineKeyboardButton("📢 Join Channel", url=config.CHANNEL_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                owner_contact,
                reply_markup=reply_markup
            )
        return False
    return True


async def authorized_only(update):
    """Check if user is owner OR approved user."""
    if not is_authorized(update):
        if update.message:
            # Get user info
            user = update.effective_user
            user_id = user.id
            username = f"@{user.username}" if user.username else f"ID: {user_id}"
            
            owner_contact = f"""
┌─ ❌ ACCESS DENIED
│
You are not authorized to use this bot!

┌─ ℹ️ YOUR INFO
│
  • User: {username}
  • ID: {user_id}
  • Status: Not Approved

┌─ 👑 CONTACT OWNER
│
  • Owner: @oyeeee
  • Click below to request access
└─"""

            keyboard = [
                [InlineKeyboardButton("📩 Request Access", url=f"tg://user?id={config.OWNER_ID}")],
                [InlineKeyboardButton("📢 Join Channel", url=config.CHANNEL_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                owner_contact,
                reply_markup=reply_markup
            )
        return False
    return True


# ============================================================
# TELETHON SESSION
# ============================================================

async def connect_saved_session():
    global client

    session = session_data.get("session", "")

    if not session:
        return None

    try:
        new_client = TelegramClient(
            StringSession(session),
            config.API_ID,
            config.API_HASH
        )

        await new_client.connect()

        if not await new_client.is_user_authorized():
            await new_client.disconnect()
            return None

        client = new_client
        print("Telegram user session connected.")

        await load_entity_cache()
        
        return client

    except Exception as e:
        print("Session connection failed:", e)
        return None


async def load_entity_cache():
    global entity_cache_loaded
    
    if not client or entity_cache_loaded:
        return
    
    try:
        dialogs = await client.get_dialogs()
        entity_cache_loaded = True
        print(f"✅ Entity cache loaded with {len(dialogs)} dialogs.")
        
        target_id = target_data.get("target_id")
        if target_id:
            try:
                await client.get_entity(target_id)
                print(f"✅ Target entity {target_id} found in cache.")
            except Exception as e:
                print(f"⚠️ Target entity {target_id} not found in cache: {e}")
    except Exception as e:
        print(f"⚠️ Failed to load entity cache: {e}")


async def ensure_client():
    global client

    if client:
        try:
            if client.is_connected():
                if await client.is_user_authorized():
                    if not entity_cache_loaded:
                        await load_entity_cache()
                    return client
        except Exception:
            pass

    return await connect_saved_session()


# ============================================================
# DELAY PARSER
# ============================================================

def parse_delay(text):
    text = text.lower().strip()

    pattern = r"(\d+)\s*(hour|hours|hr|hrs|min|mins|minute|minutes|sec|secs|second|seconds)"
    matches = re.findall(pattern, text)

    if not matches:
        raise ValueError(
            "Invalid delay format.\n\n"
            "• Examples:\n"
            "  /setdelay 20min\n"
            "  /setdelay 1hour\n"
            "  /setdelay 30sec\n"
            "  /setdelay 1hour 30min\n"
            "  /setdelay 1h 30m 10s"
        )

    total = 0

    for value, unit in matches:
        value = int(value)

        if unit in ["hour", "hours", "hr", "hrs"]:
            total += value * 3600
        elif unit in ["min", "mins", "minute", "minutes"]:
            total += value * 60
        elif unit in ["sec", "secs", "second", "seconds"]:
            total += value

    if total <= 0:
        raise ValueError("Delay must be greater than zero.")

    return total


# ============================================================
# USERNAME
# ============================================================

def normalize_username(username):
    username = username.strip()
    if username.startswith("@"):
        username = username[1:]
    return username


# ============================================================
# RESOLVE TELEGRAM TARGET
# ============================================================

async def resolve_target(link):
    tg = await ensure_client()

    if not tg:
        raise RuntimeError("No Telegram session connected.")

    link = link.strip()

    try:
        if "t.me/" in link:
            username = link.split("t.me/", 1)[1]
            username = username.split("?", 1)[0]
            username = username.rstrip("/")
            entity = await tg.get_entity(username)
        else:
            entity = await tg.get_entity(link)

        return entity

    except Exception as e:
        raise RuntimeError(f"Could not resolve target: {e}")


# ============================================================
# SAVE TARGET
# ============================================================

async def set_target(link, target_type):
    entity = await resolve_target(link)

    target_id = utils.get_peer_id(entity)

    target_data.update({
        "target_id": target_id,
        "target_type": target_type,
        "target_link": link
    })

    save_json(config.TARGET_FILE, target_data)
    
    global entity_cache_loaded
    entity_cache_loaded = False

    return entity


# ============================================================
# CHANGE USERNAME
# ============================================================

async def change_username(username):
    tg = await ensure_client()

    if not tg:
        return (False, "Telegram session not connected.")

    target_id = target_data.get("target_id")

    if not target_id:
        return (False, "No target set.")

    username = normalize_username(username)

    try:
        entity = await tg.get_entity(target_id)

        if not getattr(entity, "broadcast", False):
            return (
                False,
                "Target is not a broadcast channel.\n"
                "Telegram does not allow username operations on ordinary groups."
            )

        await tg(UpdateUsernameRequest(entity, username))

        return (True, username)

    except FloodWaitError as e:
        return (False, f"FloodWait: wait {e.seconds} seconds.")

    except UsernameOccupiedError:
        return (False, f"@{username} is already occupied.")

    except UsernameInvalidError:
        return (False, f"@{username} is invalid.")

    except RPCError as e:
        return (False, f"Telegram error: {e}")

    except Exception as e:
        return (False, str(e))


# ============================================================
# ROTATION
# ============================================================

async def rotation_loop():
    global current_index

    print("🔄 Rotation started.")

    while True:
        if not usernames:
            print("No usernames available.")
            break

        if not target_data.get("target_id"):
            print("No target configured.")
            break

        await load_entity_cache()

        username = usernames[current_index]

        success, result = await change_username(username)

        if success:
            print(f"✅ Username changed: @{result}")
            current_index = (current_index + 1) % len(usernames)
            await asyncio.sleep(delay_seconds)
        else:
            print(f"❌ Username change failed: {result}")

            if "FloodWait" in result:
                match = re.search(r"(\d+)\s+seconds", result)
                if match:
                    wait = int(match.group(1))
                    await asyncio.sleep(wait)
                    continue

            await asyncio.sleep(max(delay_seconds, 60))

    print("⏹️ Rotation stopped.")


# ============================================================
# APPROVAL COMMAND HANDLERS
# ============================================================

# ============================================================
# /APPROVE - Owner only command to approve users
# ============================================================

async def approve_command(update, context):
    """Approve a user to use the bot."""
    if not await owner_only(update):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            f"""{format_error("Invalid Usage")}

┌─ 📖 USAGE
│
  /approve <user_id_or_username> <time>

┌─ ⏱️ TIME FORMATS
│
  • 1day, 30day
  • 1hour, 2hours
  • 1min, 30min
  • 1sec, 60sec
  • unlimited, permanent

┌─ 📝 EXAMPLES
│
  • /approve 123456789 1day
  • /approve @username 30min
  • /approve 123456789 unlimited
  • /approve @user 2hours
└─"""
        )
        return

    user_identifier = context.args[0]
    time_str = " ".join(context.args[1:])

    # Try to get user ID
    user_id = None
    username = None
    
    try:
        # If it's a username (starts with @)
        if user_identifier.startswith("@"):
            username = user_identifier[1:]
            # Try to resolve username
            tg = await ensure_client()
            if tg:
                try:
                    entity = await tg.get_entity(username)
                    user_id = entity.id
                except:
                    pass
        
        # If it's a numeric ID
        if not user_id:
            user_id = int(user_identifier)
            
    except ValueError:
        await update.message.reply_text(
            format_error(f"Invalid user identifier: {user_identifier}")
        )
        return

    if not user_id:
        await update.message.reply_text(
            format_error("Could not resolve user. Make sure the username is correct.")
        )
        return

    # Check if trying to approve owner
    if user_id == config.OWNER_ID:
        await update.message.reply_text(
            format_info("Owner is always approved! No need to approve.")
        )
        return

    # Approve the user
    result = approve_user(user_id, time_str)
    
    if result["success"]:
        await update.message.reply_text(
            f"""{format_success("User Approved")}

┌─ 👤 USER INFO
│
  • User ID: {user_id}
  • Duration: {result.get('duration', 'N/A')}
  • Expiry: {result.get('expiry', 'Never')}
└─

✅ User can now use the bot!"""
        )
    else:
        await update.message.reply_text(
            format_error(f"Approval failed: {result['message']}")
        )


# ============================================================
# /REVOKE - Owner only command to revoke user access
# ============================================================

async def revoke_command(update, context):
    """Revoke a user's access to the bot."""
    if not await owner_only(update):
        return

    if not context.args:
        await update.message.reply_text(
            format_error("Usage: /revoke <user_id>")
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            format_error("Invalid user ID. Please provide a numeric ID.")
        )
        return

    if user_id == config.OWNER_ID:
        await update.message.reply_text(
            format_info("Cannot revoke owner's access!")
        )
        return

    if revoke_user(user_id):
        await update.message.reply_text(
            f"""{format_success("Access Revoked")}

┌─ 👤 USER
│
  • User ID: {user_id}
  • Status: Revoked
└─

❌ User can no longer use the bot."""
        )
    else:
        await update.message.reply_text(
            format_error(f"User {user_id} was not approved.")
        )


# ============================================================
# /APPROVED - Show all approved users
# ============================================================

async def approved_list_command(update, context):
    """Show list of all approved users."""
    if not await owner_only(update):
        return

    approved_data = load_approved_users()
    
    if not approved_data:
        await update.message.reply_text(
            format_info("No users are approved yet.")
        )
        return

    lines = []
    for user_id_str, data in approved_data.items():
        user_id = int(user_id_str)
        if data.get("unlimited", False):
            status = "♾️ Unlimited"
        else:
            expiry = data.get("expiry", "Unknown")
            try:
                expiry_time = datetime.fromisoformat(expiry)
                remaining = expiry_time - datetime.now()
                if remaining.total_seconds() <= 0:
                    status = "⏰ Expired"
                else:
                    status = f"⏳ {format_delay(int(remaining.total_seconds()))} left"
            except:
                status = "❓ Unknown"
        
        lines.append(f"  • ID: {user_id} | {status}")

    text = f"""{format_header("Approved Users List", "👥")}

{chr(10).join(lines)}

📊 Total: {len(lines)} users"""
    
    await update.message.reply_text(text)


# ============================================================
# /MYSTATUS - Show user's own approval status
# ============================================================

async def mystatus_command(update, context):
    """Show user's own approval status."""
    if not update.effective_user:
        return
    
    user = update.effective_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "No username"
    
    info = get_user_approval_info(user_id)
    
    if info["is_owner"]:
        status_text = "👑 Owner (Full Access)"
    elif info["approved"]:
        if info["unlimited"]:
            status_text = "♾️ Unlimited Access"
        else:
            expiry = info["expiry"]
            try:
                expiry_time = datetime.fromisoformat(expiry)
                remaining = expiry_time - datetime.now()
                if remaining.total_seconds() <= 0:
                    status_text = "⏰ Expired (Contact Owner)"
                else:
                    status_text = f"✅ Approved ({format_delay(int(remaining.total_seconds()))} left)"
            except:
                status_text = "✅ Approved"
    else:
        status_text = "❌ Not Approved"

    text = f"""{format_header("Your Status", "📊")}

┌─ 👤 USER INFO
│
  • ID: {user_id}
  • Username: {username}
  • Status: {status_text}
└─

💡 If not approved, contact @oyeeee"""
    
    await update.message.reply_text(text)


# ============================================================
# COMMAND HANDLERS
# ============================================================

# ============================================================
# /START - WITH IMAGE AND 3 INLINE BUTTONS (STYLISH)
# ============================================================

async def start_command(update, context):
    if not await authorized_only(update):
        return

    # Get user's first name
    first_name = update.effective_user.first_name or "User"

    # Stylish caption
    caption = f"""
👋 Hey **{first_name}**,
This is **⏤͟͞ 𝙇𝙄𝙉𝙆 𝘾𝙃𝘼𝙉𝙂𝙀𝙍 𝘽𝙊𝙏** !

🔄 A powerful username rotation bot with some awesome and useful features.

***ℹ️ Click on the help button for more info.***

┌─ 🚀 COMMANDS
│
│  🔐 **SESSION**
│    /connect <session>
│
│  🎯 **TARGET**
│    /addchannel <link>
│    /addgroup <link>
│
│  📝 **USERNAMES**
│    /addusername @name1, @name2
│    /done
│    /setdelay 20min
│
│  ⚙️ **CONTROL**
│    /forcestart
│    /forcestop
│    /change_now
│
│  📊 **INFO**
│    /status
│    /list
│    /clear
│    /current
│    /mystatus
└─

💡 **Tip:** Use /status to check current configuration"""

    # 3 Inline Buttons - Developer, Channel, Support
    keyboard = [
        [
            InlineKeyboardButton("👨‍💻 𝘿𝙀𝙑𝙀𝙇𝙊𝙋𝙀𝙍", url=f"tg://user?id={config.OWNER_ID}"),
            InlineKeyboardButton("📢 𝘾𝙃𝘼𝙉𝙉𝙀𝙇", url=config.CHANNEL_LINK),
        ],
        [
            InlineKeyboardButton("🆘 𝙃𝙀𝙇𝙋", url=config.SUPPORT_LINK),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Image URL
    image_url = "https://files.catbox.moe/rbalef.jpg"

    # Send photo with caption and buttons
    await update.message.reply_photo(
        photo=image_url,
        caption=caption,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# ============================================================
# /CONNECT - Only authorized users can connect
# ============================================================

async def connect_command(update, context):
    global client, entity_cache_loaded

    if not await authorized_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/connect <session_string>"))
        return

    session_string = context.args[0].strip()

    try:
        test_client = TelegramClient(
            StringSession(session_string),
            config.API_ID,
            config.API_HASH
        )

        await test_client.connect()

        if not await test_client.is_user_authorized():
            await test_client.disconnect()
            await update.message.reply_text(format_error("Invalid session string."))
            return

        me = await test_client.get_me()

        session_data["session"] = session_string
        save_json(config.SESSION_FILE, session_data)

        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

        client = test_client
        entity_cache_loaded = False
        
        await load_entity_cache()

        await update.message.reply_text(
            f"""{format_success("Session Connected")}

┌─ 👤 ACCOUNT INFO
│
  • ID: {me.id}
  • Name: {me.first_name or 'Unknown'}
  • Username: @{me.username if me.username else 'N/A'}
└─"""
        )

    except Exception as e:
        await update.message.reply_text(format_error(f"Connection failed:\n{e}"))


# ============================================================
# /ADDCHANNEL
# ============================================================

async def addchannel_command(update, context):
    if not await authorized_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/addchannel https://t.me/channelname"))
        return

    link = context.args[0]

    try:
        entity = await set_target(link, "channel")

        await update.message.reply_text(
            f"""{format_success("Channel Added")}

┌─ 📺 CHANNEL INFO
│
  • ID: {entity.id}
  • Link: {link}
  • Type: Broadcast Channel
└─

💡 Ready for username rotation!"""
        )

    except Exception as e:
        await update.message.reply_text(format_error(f"Failed to add channel:\n{e}"))


# ============================================================
# /ADDGROUP
# ============================================================

async def addgroup_command(update, context):
    if not await authorized_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/addgroup https://t.me/groupname"))
        return

    link = context.args[0]

    try:
        entity = await set_target(link, "group")

        await update.message.reply_text(
            f"""{format_success("Group Added")}

┌─ 👥 GROUP INFO
│
  • ID: {entity.id}
  • Link: {link}
  • Type: Group
└─

⚠️ Note: Ordinary groups do not support 
   username updates via API."""
        )

    except Exception as e:
        await update.message.reply_text(format_error(f"Failed to add group:\n{e}"))


# ============================================================
# /ADDUSERNAME
# ============================================================

async def addusername_command(update, context):
    global usernames

    if not await authorized_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/addusername @name1, @name2"))
        return

    raw = " ".join(context.args)
    names = [normalize_username(x) for x in raw.split(",") if x.strip()]

    added = 0
    skipped = 0
    for name in names:
        if name and name not in usernames:
            usernames.append(name)
            added += 1
        else:
            skipped += 1

    save_usernames(usernames)

    await update.message.reply_text(
        f"""{format_success("Usernames Added")}

┌─ 📝 SUMMARY
│
  • Added: {added}
  • Skipped (duplicates): {skipped}
  • Total usernames: {len(usernames)}
└─

💡 Use /list to view all usernames"""
    )


# ============================================================
# /DONE
# ============================================================

async def done_command(update, context):
    global usernames

    if not await authorized_only(update):
        return

    usernames = load_usernames()

    await update.message.reply_text(
        f"""{format_success("Username List Finalized")}

┌─ 📊 STATS
│
  • Total usernames: {len(usernames)}
  • Status: Ready for rotation
└─

💡 Use /forcestart to begin rotation"""
    )


# ============================================================
# /SETDELAY
# ============================================================

async def setdelay_command(update, context):
    global delay_seconds

    if not await authorized_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error(
            "Usage:\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 1h 30m 10s"
        ))
        return

    text = " ".join(context.args)

    try:
        delay_seconds = parse_delay(text)

        await update.message.reply_text(
            f"""{format_success("Delay Updated")}

┌─ ⏱️ NEW DELAY
│
  • Value: {format_delay(delay_seconds)}
  • Seconds: {delay_seconds}s
└─"""
        )

    except ValueError as e:
        await update.message.reply_text(format_error(str(e)))


# ============================================================
# /FORCESTART
# ============================================================

async def forcestart_command(update, context):
    global rotation_task

    if not await authorized_only(update):
        return

    if not target_data.get("target_id"):
        await update.message.reply_text(
            format_error("No target set!\nUse /addgroup or /addchannel")
        )
        return

    if not usernames:
        await update.message.reply_text(
            format_error("No usernames added.\nUse /addusername")
        )
        return

    tg = await ensure_client()

    if not tg:
        await update.message.reply_text(
            format_error("Telegram session not connected.\nUse /connect")
        )
        return

    if rotation_task and not rotation_task.done():
        await update.message.reply_text(
            format_info("Rotation is already running.")
        )
        return

    rotation_task = asyncio.create_task(rotation_loop())

    await update.message.reply_text(
        f"""{format_header("🚀 Rotation Started", "🚀")}

┌─ 📊 CONFIGURATION
│
  • Target ID: {target_data['target_id']}
  • Target Type: {target_data.get('target_type', 'N/A')}
  • Usernames: {len(usernames)}
  • Delay: {format_delay(delay_seconds)}
  • Starting Index: {current_index + 1}
└─

💡 Use /status to monitor progress"""
    )


# ============================================================
# /FORCESTOP
# ============================================================

async def forcestop_command(update, context):
    global rotation_task

    if not await authorized_only(update):
        return

    if rotation_task and not rotation_task.done():
        rotation_task.cancel()
        try:
            await rotation_task
        except asyncio.CancelledError:
            pass

        rotation_task = None

        await update.message.reply_text(
            f"""{format_header("⏹️ Rotation Stopped", "⏹️")}

┌─ ℹ️ STATUS
│
  • Rotation has been stopped successfully
  • Current index: {current_index + 1}
└─"""
        )
    else:
        await update.message.reply_text(format_info("Rotation is not running."))


# ============================================================
# /CHANGE_NOW
# ============================================================

async def change_now_command(update, context):
    global current_index

    if not await authorized_only(update):
        return

    if not target_data.get("target_id"):
        await update.message.reply_text(
            format_error("No target set!\nUse /addgroup or /addchannel")
        )
        return

    if not usernames:
        await update.message.reply_text(
            format_error("Username list is empty.\nUse /addusername")
        )
        return

    await load_entity_cache()

    username = usernames[current_index]

    status_msg = await update.message.reply_text(
        f"""┌─ 🔄 CHANGING USERNAME
│
  • Username: @{username}
  • Index: {current_index + 1}/{len(usernames)}
└─
⏳ Please wait..."""
    )

    success, result = await change_username(username)

    if success:
        current_index = (current_index + 1) % len(usernames)
        await status_msg.edit_text(
            f"""{format_success("Username Changed Successfully")}

┌─ ✅ UPDATE COMPLETE
│
  • New Username: @{result}
  • Next Index: {current_index + 1}/{len(usernames)}
└─"""
        )
    else:
        await status_msg.edit_text(
            f"""{format_error("Username Change Failed")}

┌─ ❌ ERROR DETAILS
│
  • Username: @{username}
  • Error: {result}
└─"""
        )


# ============================================================
# /STATUS
# ============================================================

async def status_command(update, context):
    if not await authorized_only(update):
        return

    tg = await ensure_client()

    session_connected = tg is not None
    session_status = format_status("Connected", session_connected) if session_connected else format_status("Not Connected", False)

    target_set = target_data.get("target_id") is not None
    target_status = format_status("Set", target_set) if target_set else format_status("Not Set", False)

    running = rotation_task is not None and not rotation_task.done()
    rotation_status = format_status("Running", running) if running else format_status("Stopped", False)

    await update.message.reply_text(
        f"""{format_header("📊 System Status", "📊")}

┌─ 🔐 SESSION
│  {session_status}
│
├─ 🎯 TARGET
│  {target_status}
│  • ID: {target_data.get('target_id') or 'N/A'}
│  • Type: {target_data.get('target_type') or 'N/A'}
│  • Link: {target_data.get('target_link') or 'N/A'}
│
├─ 📝 USERNAMES
│  • Count: {len(usernames)}
│  • Current Index: {current_index + 1}/{len(usernames) if usernames else '0'}
│  • Next: @{usernames[current_index] if usernames else 'N/A'}
│
├─ ⏱️ DELAY
│  • {format_delay(delay_seconds)}
│
└─ 🔄 ROTATION
   {rotation_status}
   • Task: {'Active' if running else 'Idle'}"""
    )


# ============================================================
# /LIST
# ============================================================

async def list_command(update, context):
    if not await authorized_only(update):
        return

    if not usernames:
        await update.message.reply_text(
            f"""{format_info("Username List")}

┌─ 📭 EMPTY
│
  • No usernames have been added yet.
  • Use /addusername to add some.
└─"""
        )
        return

    # Split into chunks to avoid message length limits
    chunk_size = 30
    chunks = [usernames[i:i + chunk_size] for i in range(0, len(usernames), chunk_size)]
    
    for idx, chunk in enumerate(chunks, 1):
        formatted_list = []
        for i, name in enumerate(chunk, 1):
            formatted_list.append(f"  {i + (idx-1) * chunk_size}. @{name}")
        
        text = f"""{format_header(f"Username List {idx}/{len(chunks)}", "📋")}

{chr(10).join(formatted_list)}
"""
        await update.message.reply_text(text)


# ============================================================
# /CLEAR
# ============================================================

async def clear_command(update, context):
    global usernames, current_index

    if not await authorized_only(update):
        return

    usernames = []
    current_index = 0
    save_usernames(usernames)

    await update.message.reply_text(
        f"""{format_success("List Cleared")}

┌─ 🗑️ COMPLETE
│
  • All usernames have been removed.
  • Current index reset to 0.
└─"""
    )


# ============================================================
# /CURRENT
# ============================================================

async def current_command(update, context):
    if not await authorized_only(update):
        return

    current_username = "Unknown"
    current_title = "N/A"

    tg = await ensure_client()

    if tg and target_data.get("target_id"):
        try:
            entity = await tg.get_entity(target_data["target_id"])
            username = getattr(entity, "username", None)
            if username:
                current_username = f"@{username}"
            title = getattr(entity, "title", None)
            if title:
                current_title = title
        except Exception:
            pass

    await update.message.reply_text(
        f"""{format_header("🎯 Current Target", "🎯")}

┌─ ℹ️ DETAILS
│
  • ID: {target_data.get('target_id')}
  • Type: {target_data.get('target_type')}
  • Link: {target_data.get('target_link') or 'N/A'}
  • Title: {current_title}
  • Username: {current_username}
└─"""
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    print("Bot error:", context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            format_error(f"An unexpected error occurred:\n{context.error}")
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("""
╔═══════════════════════════════════════╗
║     Telegram Link Changer Bot         ║
║          Version 3.0                  ║
║     With Approval System              ║
╚═══════════════════════════════════════╝
    """)

    application = Application.builder().token(config.BOT_TOKEN).build()

    # Approval commands (Owner only)
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("revoke", revoke_command))
    application.add_handler(CommandHandler("approved", approved_list_command))
    
    # Main commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mystatus", mystatus_command))
    application.add_handler(CommandHandler("connect", connect_command))
    application.add_handler(CommandHandler("addchannel", addchannel_command))
    application.add_handler(CommandHandler("addgroup", addgroup_command))
    application.add_handler(CommandHandler("addusername", addusername_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("setdelay", setdelay_command))
    application.add_handler(CommandHandler("forcestart", forcestart_command))
    application.add_handler(CommandHandler("forcestop", forcestop_command))
    application.add_handler(CommandHandler("change_now", change_now_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("current", current_command))

    application.add_error_handler(error_handler)

    print("🤖 Bot is running... Press Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()