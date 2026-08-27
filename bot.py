import asyncio
import json
import os
import re
from typing import Optional
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
    CallbackQueryHandler,
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
# ANIMATION HELPERS
# ============================================================

async def animate_initialization(update, context):
    """Create an animated initialization sequence with character-by-character reveal."""
    
    # The initialization text with the exact font you requested
    init_text = "𝒾𝓃𝒾𝓉𝒾𝒶𝓁𝒾𝓏𝒾𝓃𝑔"
    
    # Create inline keyboard buttons
    keyboard = [
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("📝 List", callback_data="list"),
        ],
        [
            InlineKeyboardButton("🚀 Start Rotation", callback_data="start_rotation"),
            InlineKeyboardButton("⏹️ Stop Rotation", callback_data="stop_rotation"),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="help"),
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Create the full welcome message template with image
    welcome_template = f"""
╔═══════════════════════════════════════════╗
║                                           ║
║    {init_text}    ║
║                                           ║
║          ⚡ SYSTEM LOADING ⚡              ║
║                                           ║
╚═══════════════════════════════════════════╝

┌─ 🤖 BOT INITIALIZATION
│
  • Loading configuration...
  • Establishing connection...
  • Loading modules...
  • Ready!

┌─ 🚀 COMMANDS
│
│  🔐 SESSION
│    /connect <session>
│
│  🎯 TARGET
│    /addchannel <link>
│    /addgroup <link>
│
│  📝 USERNAMES
│    /addusername @name1, @name2
│    /done
│    /setdelay 20min
│
│  ⚙️ CONTROL
│    /forcestart
│    /forcestop
│    /change_now
│
│  📊 INFO
│    /status
│    /list
│    /clear
│    /current
└─

💡 Use buttons below for quick access!"""

    # Split the welcome template into parts
    parts = welcome_template.split(init_text)
    
    # Send initial message with just the first part
    initial_message = parts[0] + " " * len(init_text) + parts[1]
    
    # Send with image and inline buttons
    image_url = "https://telegra.ph/file/your-image-link-here.jpg"  # Replace with your image URL
    message = await update.message.reply_photo(
        photo=image_url,
        caption=initial_message,
        reply_markup=reply_markup
    )
    
    # Animate the initialization text character by character
    for i in range(1, len(init_text) + 1):
        # Build the text with current progress
        animated_text = parts[0] + init_text[:i] + " " * (len(init_text) - i) + parts[1]
        
        # Add a loading indicator
        loading_chars = ["|", "/", "-", "\\"]
        loading = loading_chars[i % len(loading_chars)]
        
        # Update the message caption
        await message.edit_caption(
            caption=animated_text,
            reply_markup=reply_markup
        )
        
        # Small delay for smooth animation
        await asyncio.sleep(0.12)
    
    # Final animation with glow effect
    for _ in range(3):
        # Glow on
        glow_text = parts[0] + f"✨{init_text}✨" + parts[1]
        await message.edit_caption(
            caption=glow_text,
            reply_markup=reply_markup
        )
        await asyncio.sleep(0.2)
        
        # Glow off
        normal_text = parts[0] + init_text + parts[1]
        await message.edit_caption(
            caption=normal_text,
            reply_markup=reply_markup
        )
        await asyncio.sleep(0.2)
    
    # Final message with complete initialization
    final_message = welcome_template.replace(init_text, f"✅ {init_text} ✅")
    await message.edit_caption(
        caption=final_message,
        reply_markup=reply_markup
    )


async def animate_loading(update, context, duration=3):
    """Show a loading animation with progress dots."""
    loading_steps = ["●○○○", "○●○○", "○○●○", "○○○●"]
    message = await update.message.reply_text("⏳ Loading")
    
    for i in range(duration * 5):  # 5 updates per second
        step = loading_steps[i % len(loading_steps)]
        await message.edit_text(f"⏳ Loading {step}")
        await asyncio.sleep(0.2)
    
    return message


async def animate_text_sequence(update, context, text_sequence, delay=0.15):
    """Animate a sequence of texts in a single message."""
    message = await update.message.reply_text(text_sequence[0])
    
    for text in text_sequence[1:]:
        await asyncio.sleep(delay)
        await message.edit_text(text)
    
    return message


# ============================================================
# INLINE BUTTON HANDLERS
# ============================================================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "status":
        # Call status command
        await status_command(update, context)
    
    elif query.data == "list":
        # Call list command
        await list_command(update, context)
    
    elif query.data == "start_rotation":
        # Call forcestart command
        await forcestart_command(update, context)
    
    elif query.data == "stop_rotation":
        # Call forcestop command
        await forcestop_command(update, context)
    
    elif query.data == "help":
        # Show help menu
        await query.edit_message_text(
            f"""{format_header("📖 Help Menu", "📖")}

┌─ 📚 COMMANDS
│
│  🔐 SESSION MANAGEMENT
│    /connect <session> - Connect Telegram session
│
│  🎯 TARGET MANAGEMENT  
│    /addchannel <link> - Set channel target
│    /addgroup <link> - Set group target
│
│  📝 USERNAME MANAGEMENT
│    /addusername @name1, @name2 - Add usernames
│    /done - Finalize username list
│    /setdelay 20min - Set rotation delay
│    /list - View all usernames
│    /clear - Clear username list
│    /current - Show current username
│
│  ⚙️ ROTATION CONTROL
│    /forcestart - Start rotation
│    /forcestop - Stop rotation
│    /change_now - Change to next username
│
│  📊 INFORMATION
│    /status - Show bot status
│
└─

💡 Tip: Use buttons for quick access!""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Main", callback_data="back")]
            ])
        )
    
    elif query.data == "about":
        # Show about information
        await query.edit_message_text(
            f"""{format_header("ℹ️ About Bot", "ℹ️")}

┌─ 🤖 BOT INFO
│
  • Name: Telegram Link Changer Bot
  • Version: 2.0
  • Language: Python
  • Library: python-telegram-bot
  • Framework: Telethon
│
├─ ⚡ FEATURES
│  • Automatic username rotation
│  • Multiple username support
│  • Customizable delay
│  • Session management
│  • Real-time status
│
└─

Made with ❤️ using Python""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Main", callback_data="back")]
            ])
        )
    
    elif query.data == "back":
        # Go back to main menu
        await start_command(update, context)


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
# OWNER CHECK
# ============================================================

def is_owner(update):
    if not update.effective_user:
        return False
    return update.effective_user.id == config.OWNER_ID


async def owner_only(update):
    if not is_owner(update):
        if update.message:
            await update.message.reply_text(format_error("You are not authorized to use this bot."))
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
# COMMAND HANDLERS - WITH ENHANCED UI
# ============================================================

# ============================================================
# /START - WITH ANIMATION, IMAGE, AND INLINE BUTTONS
# ============================================================

async def start_command(update, context):
    if not await owner_only(update):
        return

    # Show the animated initialization with image and buttons
    await animate_initialization(update, context)


# ============================================================
# /CONNECT
# ============================================================

async def connect_command(update, context):
    global client, entity_cache_loaded

    if not await owner_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/connect <session_string>"))
        return

    # Show loading animation while connecting
    loading_msg = await animate_loading(update, context, duration=2)

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
            await loading_msg.edit_text(format_error("Invalid session string."))
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

        await loading_msg.edit_text(
            f"""{format_success("Session Connected")}

┌─ 👤 ACCOUNT INFO
│
  • ID: {me.id}
  • Name: {me.first_name or 'Unknown'}
  • Username: @{me.username if me.username else 'N/A'}
└─"""
        )

    except Exception as e:
        await loading_msg.edit_text(format_error(f"Connection failed:\n{e}"))


# ============================================================
# /ADDCHANNEL
# ============================================================

async def addchannel_command(update, context):
    if not await owner_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/addchannel https://t.me/channelname"))
        return

    link = context.args[0]
    
    # Show loading animation
    loading_msg = await animate_loading(update, context, duration=1)

    try:
        entity = await set_target(link, "channel")

        await loading_msg.edit_text(
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
        await loading_msg.edit_text(format_error(f"Failed to add channel:\n{e}"))


# ============================================================
# /ADDGROUP
# ============================================================

async def addgroup_command(update, context):
    if not await owner_only(update):
        return

    if not context.args:
        await update.message.reply_text(format_error("Usage:\n/addgroup https://t.me/groupname"))
        return

    link = context.args[0]
    
    # Show loading animation
    loading_msg = await animate_loading(update, context, duration=1)

    try:
        entity = await set_target(link, "group")

        await loading_msg.edit_text(
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
        await loading_msg.edit_text(format_error(f"Failed to add group:\n{e}"))


# ============================================================
# /ADDUSERNAME
# ============================================================

async def addusername_command(update, context):
    global usernames

    if not await owner_only(update):
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

    if not await owner_only(update):
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

    if not await owner_only(update):
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

    if not await owner_only(update):
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

    if not await owner_only(update):
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

    if not await owner_only(update):
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
    if not await owner_only(update):
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
    if not await owner_only(update):
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

    if not await owner_only(update):
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
    if not await owner_only(update):
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
║          Version 2.0                  ║
╚═══════════════════════════════════════╝
    """)

    application = Application.builder().token(config.BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
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
    
    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button_callback))

    application.add_error_handler(error_handler)

    print("🤖 Bot is running... Press Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()
