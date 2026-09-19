import asyncio
import json
import os
import re
import io
import time
import imaplib
import email as email_module
import threading
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

from kurigram import Client, filters
from kurigram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton as _KButton,
)

import qrcode

import config


# ============================================================
# COLORED BUTTON WRAPPER (kurigram ButtonStyle)
# Kurigram supports colored buttons natively. Agar ButtonStyle
# available nahi hai (purana version), style gracefully ignore hota hai.
# ============================================================

try:
    from kurigram.types import ButtonStyle
    _HAS_STYLE = True
except ImportError:
    ButtonStyle = None
    _HAS_STYLE = False


def InlineKeyboardButton(text, style=None, **kwargs):
    """Colored-button wrapper (kurigram-compatible API).
    Kurigram me style pass hota hai — colored buttons render honge."""
    if _HAS_STYLE and style is not None:
        try:
            return _KButton(text, style=style, **kwargs)
        except TypeError:
            return _KButton(text, **kwargs)
    return _KButton(text, **kwargs)


# Style shorthands (kurigram ke default styles)
BTN_DEFAULT   = ButtonStyle.DEFAULT if _HAS_STYLE else None
BTN_PRIMARY   = ButtonStyle.PRIMARY if _HAS_STYLE else None
BTN_SECONDARY = ButtonStyle.SECONDARY if _HAS_STYLE else None
BTN_SUCCESS   = ButtonStyle.SUCCESS if _HAS_STYLE else None
BTN_DANGER    = ButtonStyle.DANGER if _HAS_STYLE else None


# ============================================================
# UI HELPERS (unchanged)
# ============================================================

def format_header(title: str, emoji: str = "🤖") -> str:
    border = "═" * 38
    return f"""
┌{border}┐
│ {emoji}  {title}  │
└{border}┘
"""


def format_success(message: str) -> str:
    return f"""
┌─ ✅ SUCCESS
│
{message}
└─"""


def format_error(message: str) -> str:
    return f"""
┌─ ❌ ERROR
│
{message}
└─"""


def format_info(message: str) -> str:
    return f"""
┌─ ℹ️ INFO
│
{message}
└─"""


def format_status(status: str, is_good: bool = True) -> str:
    icon = "🟢" if is_good else "🔴"
    return f"{icon} {status}"


def format_delay(seconds: int) -> str:
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
# FILE FUNCTIONS (unchanged)
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
# APPROVAL SYSTEM (unchanged)
# ============================================================

APPROVED_FILE = "approved_users.json"

def load_approved_users():
    if not os.path.exists(APPROVED_FILE):
        save_approved_users({})
        return {}

    try:
        with open(APPROVED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_approved_users(data):
    with open(APPROVED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def parse_approve_time(time_str: str) -> Optional[int]:
    time_str = time_str.lower().strip()

    if time_str in ["unlimited", "infinite", "forever", "permanent"]:
        return -1

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
    if user_id == config.OWNER_ID:
        return True

    approved_data = load_approved_users()
    user_data = approved_data.get(str(user_id))

    if not user_data:
        return False

    if user_data.get("unlimited", False):
        return True

    expiry = user_data.get("expiry")
    if not expiry:
        return False

    try:
        expiry_time = datetime.fromisoformat(expiry)
        return datetime.now() < expiry_time
    except:
        return False


def get_user_approval_info(user_id: int) -> Dict:
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
    approved_data = load_approved_users()
    user_id_str = str(user_id)

    seconds = parse_approve_time(time_str)

    if seconds is None:
        return {"success": False, "message": "Invalid time format!"}

    if seconds == -1:
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
    approved_data = load_approved_users()
    user_id_str = str(user_id)

    if user_id_str in approved_data:
        del approved_data[user_id_str]
        save_approved_users(approved_data)
        return True
    return False


# ============================================================
# PROFILES / PLANS / ADMINS / SETTINGS DB (unchanged)
# ============================================================

def get_profile(user_id: int) -> Dict:
    profiles = load_json("profiles.json", {})
    p = profiles.get(str(user_id))
    if not p:
        p = {"premium_expiry": None, "purchases": 0, "total_spent": 0.0,
             "is_banned": False, "ban_reason": ""}
        profiles[str(user_id)] = p
        save_json("profiles.json", profiles)
    return p


def save_profile(user_id: int, p: Dict):
    profiles = load_json("profiles.json", {})
    profiles[str(user_id)] = p
    save_json("profiles.json", profiles)


def is_premium(user_id: int) -> bool:
    p = get_profile(user_id)
    exp = p.get("premium_expiry")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(exp) > datetime.now()
    except:
        return False


def premium_left(user_id: int):
    p = get_profile(user_id)
    exp = p.get("premium_expiry")
    if not exp:
        return None
    try:
        rem = datetime.fromisoformat(exp) - datetime.now()
        return rem if rem.total_seconds() > 0 else None
    except:
        return None


def fmt_td(td) -> str:
    if not td:
        return "expired"
    d = td.days
    h, rem = divmod(td.seconds, 3600)
    m = rem // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or "expired"


def activate_plan(user_id: int, days: int, price: float):
    p = get_profile(user_id)
    base = datetime.now()
    if p.get("premium_expiry"):
        try:
            old = datetime.fromisoformat(p["premium_expiry"])
            if old > base:
                base = old
        except:
            pass
    new_exp = base + timedelta(days=days)
    p["premium_expiry"] = new_exp.isoformat()
    p["purchases"] = p.get("purchases", 0) + 1
    p["total_spent"] = round(p.get("total_spent", 0.0) + price, 2)
    save_profile(user_id, p)
    return new_exp


def load_admins() -> set:
    data = load_json(config.ADMINS_FILE, {})
    return set(int(k) for k in data.keys())


def get_powers(user_id: int) -> Dict:
    if user_id == config.OWNER_ID:
        return {"can_ban": True, "can_deposit": True, "can_broadcast": True,
                "can_maintain": True, "can_plans": True}
    data = load_json(config.ADMINS_FILE, {})
    return data.get(str(user_id), {}).get("powers", {})


def has_power(user_id: int, power: str) -> bool:
    return get_powers(user_id).get(power, False)


def add_admin(user_id: int):
    data = load_json(config.ADMINS_FILE, {})
    data[str(user_id)] = {"powers": {"can_ban": True, "can_deposit": True,
                                     "can_broadcast": True, "can_maintain": True,
                                     "can_plans": True}}
    save_json(config.ADMINS_FILE, data)


def remove_admin(user_id: int):
    if user_id == config.OWNER_ID:
        return
    data = load_json(config.ADMINS_FILE, {})
    data.pop(str(user_id), None)
    save_json(config.ADMINS_FILE, data)


def toggle_power(user_id: int, power: str) -> bool:
    data = load_json(config.ADMINS_FILE, {})
    doc = data.setdefault(str(user_id), {"powers": {}})
    doc["powers"][power] = not doc["powers"].get(power, False)
    save_json(config.ADMINS_FILE, data)
    return doc["powers"][power]


def get_plans() -> Dict:
    plans = load_json(config.PLANS_FILE, {})
    if not plans:
        plans = {
            "basic": {"name": "Basic", "days": 7, "price": 49.0},
            "pro": {"name": "Pro", "days": 30, "price": 149.0},
            "elite": {"name": "Elite", "days": 90, "price": 349.0},
        }
        save_json(config.PLANS_FILE, plans)
    return plans


def get_maintenance() -> tuple:
    s = load_json(config.SETTINGS_FILE, {})
    m = s.get("maintenance")
    if not m:
        return False, "System upgrade in progress."
    return m.get("is_active", False), m.get("reason", "")


def set_maintenance(active: bool, reason: str = None):
    s = load_json(config.SETTINGS_FILE, {})
    m = s.setdefault("maintenance", {})
    m["is_active"] = active
    if reason is not None:
        m["reason"] = reason
    save_json(config.SETTINGS_FILE, s)


# ============================================================
# GMAIL IMAP WATCHER (unchanged)
# ============================================================

_FAMPAY_LOCK = threading.Lock()

_INCOMING_KEYWORDS = ("successfully received", "money received", "amount received",
                      "has been credited", "credited to your account",
                      "you have received", "payment received", "received via")


def _parse_receipt(body: str):
    b = body.lower()
    if re.search(r"\b(paid\s+to|debited|money\s+sent|successfully\s+paid)\b", b):
        return None, None
    if not any(k in b for k in _INCOMING_KEYWORDS) and not re.search(r"\breceived\b", b):
        return None, None
    m_amt = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", body)
    if not m_amt:
        return None, None
    amount = float(m_amt.group(1).replace(",", ""))
    m_utr = re.search(r"(?:utr|upi\s*ref(?:erence)?|transaction\s*id|txn\s*id|rrn)\s*[:\-#]?\s*([A-Za-z0-9\-]{6,40})", body, re.I)
    if not m_utr:
        m12 = re.search(r"\b(\d{12})\b", body)
        if not m12:
            return None, None
        utr = m12.group(1)
    else:
        utr = m_utr.group(1)
    return amount, utr


def _fetch_receipts():
    if not (getattr(config, "IMAP_EMAIL", "") and getattr(config, "IMAP_PASSWORD", "")):
        return
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(config.IMAP_EMAIL, config.IMAP_PASSWORD)
        conn.select("INBOX")
        sender = getattr(config, "FAMPAY_SENDER", "")
        q = f'(UNSEEN FROM "{sender}")' if sender else "UNSEEN"
        typ, data = conn.search(None, q)
        if typ == "OK":
            for num in (data[0].split() if data and data[0] else []):
                try:
                    typ, msg_data = conn.fetch(num, "(RFC822)")
                    if typ != "OK":
                        continue
                    msg = email_module.message_from_bytes(msg_data[0][1])
                    body = ""
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html"):
                            try:
                                body += part.get_payload(decode=True).decode(
                                    part.get_content_charset() or "utf-8",
                                    errors="ignore") + "\n"
                            except:
                                pass
                    amount, utr = _parse_receipt(body)
                    if not amount or not utr:
                        continue
                    utr_norm = re.sub(r"[^A-Za-z0-9]", "", utr).upper()
                    with _FAMPAY_LOCK:
                        credits = load_json("fampay_credits.json", [])
                        if not any(c.get("utr_norm") == utr_norm for c in credits):
                            credits.append({"utr": utr, "utr_norm": utr_norm,
                                            "amount": amount, "used": False,
                                            "received_at": time.time()})
                            save_json("fampay_credits.json", credits)
                            conn.store(num, "+FLAGS", "\\Seen")
                except Exception as e:
                    print("IMAP parse error:", e)
        conn.logout()
    except Exception as e:
        print("IMAP error:", e)


def _email_watcher_loop():
    while True:
        try:
            _fetch_receipts()
        except Exception as e:
            print("watcher error:", e)
        time.sleep(20)


def verify_utr(txn_id: str, amount: float) -> bool:
    txn_norm = re.sub(r"[^A-Za-z0-9]", "", txn_id).upper()
    if not txn_norm:
        return False
    with _FAMPAY_LOCK:
        credits = load_json("fampay_credits.json", [])
        rec = None
        for c in credits:
            if not c.get("used") and c.get("utr_norm") == txn_norm:
                rec = c
                break
        if not rec and len(txn_norm) >= 6:
            for c in credits:
                if not c.get("used") and txn_norm in c.get("utr_norm", ""):
                    rec = c
                    break
        if not rec:
            day_ago = time.time() - 86400
            for c in credits:
                if (not c.get("used") and abs(c.get("amount", 0) - amount) <= 0.01
                        and c.get("received_at", 0) >= day_ago):
                    rec = c
                    break
        if not rec or abs(rec.get("amount", 0) - amount) > 0.01:
            return False
        rec["used"] = True
        rec["used_at"] = time.time()
        save_json("fampay_credits.json", credits)
        return True


def generate_upi_qr(amount: float) -> io.BytesIO:
    name = config.PAYEE_NAME.replace(" ", "%20")
    url = f"upi://pay?pa={config.UPI_ID}&pn={name}&am={amount:.2f}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    bio = io.BytesIO()
    bio.name = "qr.png"
    qr.make_image(fill_color="black", back_color="white").save(bio, "PNG")
    bio.seek(0)
    return bio


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

ADMIN_IDS = load_admins()

# PTB context.user_data replacement (kurigram)
USER_STATE: Dict[int, Dict] = {}


def _ud(user_id: int) -> Dict:
    return USER_STATE.setdefault(user_id, {})


def is_staff(user_id: int) -> bool:
    return user_id == config.OWNER_ID or user_id in ADMIN_IDS


# ============================================================
# OWNER CHECK WITH APPROVAL SYSTEM (kurigram version)
# ============================================================

def is_owner(message: Message) -> bool:
    if not message or not message.from_user:
        return False
    return message.from_user.id == config.OWNER_ID


def is_authorized(message: Message) -> bool:
    if not message or not message.from_user:
        return False
    user_id = message.from_user.id
    return user_id == config.OWNER_ID or is_user_approved(user_id)


async def owner_only(message: Message) -> bool:
    if not is_owner(message):
        if message:
            owner_contact = """
┌─ ❌ ERROR
│
You are not authorized to use this bot.

┌─ CONTACT OWNER
│
  • Owner: @oye_se
  • Click below to contact the owner
  • Ask for approval to use this bot
└─"""

            keyboard = [
                [InlineKeyboardButton("📩 Contact Owner", style=BTN_PRIMARY, url=f"tg://user?id={config.OWNER_ID}")],
                [InlineKeyboardButton("📢 Join Channel", style=BTN_SECONDARY, url=config.CHANNEL_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await message.reply_text(owner_contact, reply_markup=reply_markup)
        return False
    return True


async def authorized_only(message: Message) -> bool:
    if not is_authorized(message):
        if message:
            user = message.from_user
            user_id = user.id
            username = f"@{user.username}" if user.username else f"ID: {user_id}"

            owner_contact = f"""
┌─ ❌ ACCESS DENIED
│
You are not authorized to use this bot!

┌─ YOUR INFO
│
  • User: {username}
  • ID: {user_id}
  • Status: Not Approved

┌─ CONTACT OWNER
│
  • Owner: @oye_se
  • Click below to request access
└─"""

            keyboard = [
                [InlineKeyboardButton("📩 Request Access", style=BTN_PRIMARY, url=f"tg://user?id={config.OWNER_ID}")],
                [InlineKeyboardButton("📢 Join Channel", style=BTN_SECONDARY, url=config.CHANNEL_LINK)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await message.reply_text(owner_contact, reply_markup=reply_markup)
        return False
    return True


# ============================================================
# TELETHON SESSION (unchanged)
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
        print(f"Entity cache loaded with {len(dialogs)} dialogs.")

        target_id = target_data.get("target_id")
        if target_id:
            try:
                await client.get_entity(target_id)
                print(f"Target entity {target_id} found in cache.")
            except Exception as e:
                print(f"Target entity {target_id} not found in cache: {e}")
    except Exception as e:
        print(f"Failed to load entity cache: {e}")


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
# DELAY PARSER (unchanged)
# ============================================================

def parse_delay(text):
    text = text.lower().strip()

    pattern = r"(\d+)\s*(hour|hours|hr|hrs|min|mins|minute|minutes|sec|secs|second|seconds)"
    matches = re.findall(pattern, text)

    if not matches:
        raise ValueError(
            "Invalid delay format.\n\n"
            "Examples:\n"
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
# USERNAME / TARGET / CHANGE / ROTATION (unchanged)
# ============================================================

def normalize_username(username):
    username = username.strip()
    if username.startswith("@"):
        username = username[1:]
    return username


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


async def rotation_loop():
    global current_index

    print("Rotation started.")

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
            print(f"Username changed: @{result}")
            current_index = (current_index + 1) % len(usernames)
            await asyncio.sleep(delay_seconds)
        else:
            print(f"Username change failed: {result}")

            if "FloodWait" in result:
                match = re.search(r"(\d+)\s+seconds", result)
                if match:
                    wait = int(match.group(1))
                    await asyncio.sleep(wait)
                    continue

            await asyncio.sleep(max(delay_seconds, 60))

    print("Rotation stopped.")


# ============================================================
# MENUS (kurigram, colored buttons)
# ============================================================

def main_menu_keyboard(user_id: int):
    rows = [
        [InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit")],
        [InlineKeyboardButton("👤 My Profile", style=BTN_PRIMARY, callback_data="menu_profile"),
         InlineKeyboardButton("❓ Help", style=BTN_SECONDARY, callback_data="help")],
    ]
    if is_staff(user_id):
        rows.append([InlineKeyboardButton("⚙️ Admin Panel", style=BTN_DANGER, callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Add Admins", style=BTN_PRIMARY, callback_data="adm_manage_admins"),
         InlineKeyboardButton("🏷️ Edit Plans", style=BTN_PRIMARY, callback_data="adm_plans")],
        [InlineKeyboardButton("🚫 Ban User", style=BTN_DANGER, callback_data="adm_ban"),
         InlineKeyboardButton("🟢 Unban User", style=BTN_SUCCESS, callback_data="adm_unban")],
        [InlineKeyboardButton("🛠️ Maintenance", style=BTN_SECONDARY, callback_data="adm_maint"),
         InlineKeyboardButton("📢 Broadcast (DM)", style=BTN_SECONDARY, callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 User Premium Stats", style=BTN_DEFAULT, callback_data="adm_userstats"),
         InlineKeyboardButton("➕ Add Premium Free", style=BTN_DEFAULT, callback_data="adm_addprem")],
        [InlineKeyboardButton("🔙 Main Menu", style=BTN_DANGER, callback_data="back_to_start")],
    ])


def manage_admins_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Admin", style=BTN_SUCCESS, callback_data="adm_addadmin")]]
    data = load_json(config.ADMINS_FILE, {})
    for k in data.keys():
        if int(k) != config.OWNER_ID:
            rows.append([InlineKeyboardButton(f"⚙️ Powers: {k}", style=BTN_PRIMARY, callback_data=f"adm_powers_{k}")])
            rows.append([InlineKeyboardButton(f"🗑 Remove Admin {k}", style=BTN_DANGER, callback_data=f"adm_deladmin_{k}")])
    rows.append([InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def powers_keyboard(target_id: int):
    p = get_powers(target_id)
    def lbl(name, val):
        return ("🟢 " if val else "🔴 ") + name
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("Ban/Unban", p.get("can_ban")), style=BTN_PRIMARY, callback_data=f"adm_tgl_{target_id}_can_ban"),
         InlineKeyboardButton(lbl("Deposit", p.get("can_deposit")), style=BTN_PRIMARY, callback_data=f"adm_tgl_{target_id}_can_deposit")],
        [InlineKeyboardButton(lbl("Broadcast", p.get("can_broadcast")), style=BTN_PRIMARY, callback_data=f"adm_tgl_{target_id}_can_broadcast"),
         InlineKeyboardButton(lbl("Maintenance", p.get("can_maintain")), style=BTN_PRIMARY, callback_data=f"adm_tgl_{target_id}_can_maintain")],
        [InlineKeyboardButton(lbl("Edit Plans", p.get("can_plans")), style=BTN_PRIMARY, callback_data=f"adm_tgl_{target_id}_can_plans")],
        [InlineKeyboardButton("🔙 Manage Admins", style=BTN_SECONDARY, callback_data="adm_manage_admins")],
    ])


# ============================================================
# COMMAND HANDLERS (kurigram: (client, message), message.command)
# ============================================================

async def approve_command(client, message):
    if not await owner_only(message):
        return

    args = message.command[1:]

    if not args or len(args) < 2:
        await message.reply_text(
            f"""{format_error("Invalid Usage")}

┌─ USAGE
│
  /approve <user_id_or_username> <time>

┌─ TIME FORMATS
│
  • 1day, 30day
  • 1hour, 2hours
  • 1min, 30min
  • 1sec, 60sec
  • unlimited, permanent

┌─ EXAMPLES
│
  • /approve 123456789 1day
  • /approve @username 30min
  • /approve 123456789 unlimited
└─"""
        )
        return

    user_identifier = args[0]
    time_str = " ".join(args[1:])

    user_id = None

    try:
        if user_identifier.startswith("@"):
            username = user_identifier[1:]
            tg = await ensure_client()
            if tg:
                try:
                    entity = await tg.get_entity(username)
                    user_id = entity.id
                except:
                    pass

        if not user_id:
            user_id = int(user_identifier)

    except ValueError:
        await message.reply_text(
            format_error(f"Invalid user identifier: {user_identifier}")
        )
        return

    if not user_id:
        await message.reply_text(format_error("Could not resolve user."))
        return

    if user_id == config.OWNER_ID:
        await message.reply_text(format_info("Owner is always approved!"))
        return

    result = approve_user(user_id, time_str)

    if result["success"]:
        await message.reply_text(
            f"""{format_success("User Approved")}

┌─ USER INFO
│
  • User ID: {user_id}
  • Duration: {result.get('duration', 'N/A')}
  • Expiry: {result.get('expiry', 'Never')}
└─

✅ User can now use the bot!"""
        )
    else:
        await message.reply_text(format_error(f"Approval failed: {result['message']}"))


async def revoke_command(client, message):
    if not await owner_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error("Usage: /revoke <user_id>"))
        return

    try:
        user_id = int(args[0])
    except ValueError:
        await message.reply_text(format_error("Invalid user ID."))
        return

    if user_id == config.OWNER_ID:
        await message.reply_text(format_info("Cannot revoke owner's access!"))
        return

    if revoke_user(user_id):
        await message.reply_text(
            f"""{format_success("Access Revoked")}

┌─ USER
│
  • User ID: {user_id}
  • Status: Revoked
└─

❌ User can no longer use the bot."""
        )
    else:
        await message.reply_text(format_error(f"User {user_id} was not approved."))


async def approved_list_command(client, message):
    if not await owner_only(message):
        return

    approved_data = load_approved_users()

    if not approved_data:
        await message.reply_text(format_info("No users are approved yet."))
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

    text = f"""👥 Approved Users List

{chr(10).join(lines)}

📊 Total: {len(lines)} users"""

    await message.reply_text(text)


async def mystatus_command(client, message):
    if not message.from_user:
        return

    user = message.from_user
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

    text = f"""📊 Your Status

┌─ USER INFO
│
  • ID: {user_id}
  • Username: {username}
  • Status: {status_text}
└─

💡 If not approved, contact @oye_se"""

    await message.reply_text(text)


# ============================================================
# CALLBACK HANDLER (help + admin/deposit routing)
# ============================================================

async def button_callback(client: Client, query: CallbackQuery):
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data
    user = query.from_user
    uid = user.id

    # ---------- BAN CHECK ----------
    prof = get_profile(uid)
    if prof.get("is_banned") and data not in ("back_to_start",):
        try:
            await query.answer(f"🚫 Banned! Reason: {prof.get('ban_reason')}", show_alert=True)
        except Exception:
            pass
        return

    # ---------- MAINTENANCE CHECK ----------
    maint_active, maint_reason = get_maintenance()
    if maint_active and not is_staff(uid) and not data.startswith("adm_"):
        try:
            await query.answer(f"🚧 Under maintenance: {maint_reason}", show_alert=True)
        except Exception:
            pass
        return

    # ---------- HELP ----------
    if data == "help":
        help_text = """
❓ How Link Changer Bot Works

🤖 What is this bot?
This bot automatically rotates usernames for your Telegram channels.

⚙️ How it works:
1. Connect Session - Connect your Telegram account
2. Set Target - Choose a channel to rotate usernames
3. Add Usernames - Add list of usernames to rotate
4. Start Rotation - Bot will automatically change usernames

📋 Commands:
/connect - Connect your Telegram session
/addchannel - Set target channel
/addgroup - Set target group (not supported for username changes)
/addusername - Add usernames to rotate
/done - Finalize username list
/setdelay - Set rotation delay (e.g., /setdelay 20min)
/forcestart - Start automatic rotation
/forcestop - Stop rotation
/change_now - Change username immediately
/status - Check system status
/list - View all usernames
/clear - Clear all usernames
/current - View current target

🔐 Important:
• Only channel owners/admins can change usernames
• Telegram has rate limits (FloodWait)
• Groups do NOT support username changes via API

💡 Tip: Use /status to monitor the rotation progress!
"""
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text(help_text)
        keyboard = [[InlineKeyboardButton("🔙 Back", style=BTN_SECONDARY, callback_data="back_to_start")]]
        await query.message.reply_text("🔙 Click below to go back:", reply_markup=InlineKeyboardMarkup(keyboard))

    # ---------- BACK TO START ----------
    elif data == "back_to_start":
        try:
            await query.message.delete()
        except Exception:
            pass

        caption = """
Welcome, ⏤͟͞ 𝙎𝙋𝘼𝙍𝙎𝙃 𝘽𝘼𝙉𝙄𝙔𝘼! 👋

Link Changer Bot automatically rotates usernames for your channels — from your username list, with customizable delays and full control.

Supported features: Auto-rotation, Custom delays, Channel management, Username lists and more.

Use the buttons below to add Link Changer Bot to your channel, or explore everything it can do."""

        keyboard = [
            [
                InlineKeyboardButton("👨‍💻 Developer", style=BTN_PRIMARY, url=f"tg://user?id={config.OWNER_ID}"),
                InlineKeyboardButton("📢 Channel", style=BTN_SECONDARY, url=config.CHANNEL_LINK),
            ],
            [
                InlineKeyboardButton("🆘 Support", style=BTN_SECONDARY, url=config.SUPPORT_LINK),
                InlineKeyboardButton("❓ Help", style=BTN_DEFAULT, callback_data="help"),
            ],
            [
                InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit"),
                InlineKeyboardButton("👤 My Profile", style=BTN_PRIMARY, callback_data="menu_profile"),
            ],
        ]
        if is_staff(uid):
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", style=BTN_DANGER, callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        image_url = "https://files.catbox.moe/rbalef.jpg"

        await query.message.reply_photo(
            photo=image_url,
            caption=caption,
            reply_markup=reply_markup
        )

    # ================= DEPOSIT / PLANS =================

    elif data == "menu_deposit":
        plans = get_plans()
        rows = []
        for pid, p in plans.items():
            rows.append([InlineKeyboardButton(
                f"💎 {p['name']} — {p['days']} days — ₹{p['price']:.0f}",
                style=BTN_PRIMARY,
                callback_data=f"buy_{pid}")])
        rows.append([InlineKeyboardButton("🔙 Main Menu", style=BTN_DANGER, callback_data="back_to_start")])
        await query.message.reply_text(
            "🛒 **BUY PREMIUM PLAN**\n\nChoose a plan — premium activates instantly after auto UTR verification:",
            reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("buy_"):
        pid = data.split("_", 1)[1]
        plans = get_plans()
        plan = plans.get(pid)
        if not plan:
            try:
                await query.answer("❌ Plan not found!", show_alert=True)
            except Exception:
                pass
            return
        pay_id = f"{uid}_{int(time.time())}"
        payments = load_json(config.PAYMENTS_FILE, {})
        payments[pay_id] = {"user_id": uid, "plan_id": pid, "amount": plan["price"],
                            "status": "PENDING", "created_at": time.time()}
        save_json(config.PAYMENTS_FILE, payments)
        _ud(uid)["state"] = f"WAIT_UTR_{pay_id}"

        await query.message.reply_photo(
            photo=generate_upi_qr(plan["price"]),
            caption=f"💳 **PAY ₹{plan['price']:.0f} via UPI**\n\n"
                    f"📌 UPI ID: `{config.UPI_ID}`\n"
                    f"💎 Plan: {plan['name']} ({plan['days']} days)\n\n"
                    f"Pay via FamPay/any UPI app, then send the **UTR / Transaction ID** here.\n"
                    f"✅ Auto-verified within seconds!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", style=BTN_DANGER, callback_data="menu_deposit")]]))

    elif data == "menu_profile":
        p = get_profile(uid)
        left = premium_left(uid)
        exp = p.get("premium_expiry")
        exp_str = datetime.fromisoformat(exp).strftime("%d-%m-%Y") if exp else "N/A"
        await query.message.reply_text(
            f"👤 **My Profile**\n\n"
            f"🆔 ID: `{uid}`\n"
            f"💎 Premium: **{'♾️ ' + fmt_td(left) + ' left' if left else '❌ Inactive'}**\n"
            f"⏳ Expiry: {exp_str}\n"
            f"🛍️ Plans Bought: **{p.get('purchases', 0)}**\n"
            f"💵 Total Spent: **₹{p.get('total_spent', 0.0):.2f}**",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit")],
                 [InlineKeyboardButton("🔙 Main Menu", style=BTN_DANGER, callback_data="back_to_start")]]))

    # ================= ADMIN PANEL =================

    elif data == "admin_panel":
        if not is_staff(uid):
            try:
                await query.answer("🚫 Unauthorized!", show_alert=True)
            except Exception:
                pass
            return
        _ud(uid).pop("state", None)
        await query.message.reply_text("⚙️ **ADMIN PANEL**", reply_markup=admin_panel_keyboard())

    elif data == "adm_manage_admins":
        if uid != config.OWNER_ID:
            try:
                await query.answer("👑 Owner only!", show_alert=True)
            except Exception:
                pass
            return
        await query.message.reply_text("👥 **MANAGE ADMINS**", reply_markup=manage_admins_keyboard())

    elif data == "adm_addadmin":
        if uid != config.OWNER_ID:
            return
        _ud(uid)["state"] = "ADM_ADDADMIN"
        await query.message.reply_text(
            "➕ **ADD ADMIN**\n\nSend the **User ID**:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", style=BTN_SECONDARY, callback_data="adm_manage_admins")]]))

    elif data.startswith("adm_deladmin_"):
        if uid != config.OWNER_ID:
            return
        tid = int(data.split("_")[2])
        remove_admin(tid)
        global ADMIN_IDS
        ADMIN_IDS = load_admins()
        try:
            await query.answer(f"🗑 Admin {tid} removed!", show_alert=True)
        except Exception:
            pass
        await query.message.reply_text("👥 **MANAGE ADMINS**", reply_markup=manage_admins_keyboard())

    elif data.startswith("adm_powers_"):
        if uid != config.OWNER_ID:
            return
        tid = int(data.split("_")[2])
        await query.message.reply_text(
            f"⚙️ **POWERS — {tid}**\n\nTap to toggle:",
            reply_markup=powers_keyboard(tid))

    elif data.startswith("adm_tgl_"):
        if uid != config.OWNER_ID:
            return
        _, _, tid_s, power = data.split("_")
        tid = int(tid_s)
        toggle_power(tid, power)
        await query.message.reply_text(
            f"⚙️ **POWERS — {tid}**\n\nTap to toggle:",
            reply_markup=powers_keyboard(tid))
        try:
            await query.answer("✅ Toggled!")
        except Exception:
            pass

    # ---------- MAINTENANCE ----------
    elif data == "adm_maint":
        if not has_power(uid, "can_maintain"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        active, reason = get_maintenance()
        status = "🔴 MAINTENANCE ON" if active else "🟢 ONLINE"
        await query.message.reply_text(
            f"🛠️ **MAINTENANCE PANEL**\n\nStatus: **{status}**\nReason: `{reason}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 Turn OFF" if active else "🟢 Turn ON (asks reason)",
                                      style=BTN_DANGER if active else BTN_SUCCESS,
                                      callback_data="adm_maint_toggle")],
                [InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")]]))

    elif data == "adm_maint_toggle":
        if not has_power(uid, "can_maintain"):
            return
        active, _ = get_maintenance()
        if active:
            set_maintenance(False)
            try:
                await query.answer("✅ Maintenance OFF!", show_alert=True)
            except Exception:
                pass
            await query.message.reply_text("🟢 **Maintenance turned OFF**",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")]]))
        else:
            _ud(uid)["state"] = "ADM_MAINT_REASON"
            await query.message.reply_text(
                "🛠️ **Turn ON maintenance**\n\n📝 Send the reason/message to show users:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Cancel", style=BTN_DANGER, callback_data="adm_maint")]]))

    # ---------- BAN / UNBAN ----------
    elif data == "adm_ban":
        if not has_power(uid, "can_ban"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        _ud(uid)["state"] = "ADM_BAN_ID"
        await query.message.reply_text(
            "🚫 Send **User ID** to ban:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Cancel", style=BTN_DANGER, callback_data="admin_panel")]]))

    elif data == "adm_unban":
        if not has_power(uid, "can_ban"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        _ud(uid)["state"] = "ADM_UNBAN_ID"
        await query.message.reply_text(
            "🟢 Send **User ID** to unban:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Cancel", style=BTN_DANGER, callback_data="admin_panel")]]))

    # ---------- BROADCAST ----------
    elif data == "adm_broadcast":
        if not has_power(uid, "can_broadcast"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        _ud(uid)["state"] = "ADM_BROADCAST"
        await query.message.reply_text(
            "📢 Send the message to broadcast (**DM only**):",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Cancel", style=BTN_DANGER, callback_data="admin_panel")]]))

    # ---------- PLANS EDITOR ----------
    elif data == "adm_plans":
        if not has_power(uid, "can_plans"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        plans = get_plans()
        rows = []
        for pid, p in plans.items():
            rows.append([InlineKeyboardButton(
                f"✏️ {p['name']} — {p['days']}d — ₹{p['price']:.0f}",
                style=BTN_PRIMARY,
                callback_data=f"pln_edit_{pid}")])
        rows.append([InlineKeyboardButton("➕ Add New Plan", style=BTN_SUCCESS, callback_data="pln_new")])
        rows.append([InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")])
        await query.message.reply_text(
            "🏷️ **EDIT PLANS**\n\nTap a plan to edit days/price:",
            reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("pln_edit_"):
        if not has_power(uid, "can_plans"):
            return
        pid = data.split("_", 2)[2]
        p = get_plans().get(pid)
        if not p:
            return
        _ud(uid)["state"] = f"PLN_PRICE_{pid}"
        await query.message.reply_text(
            f"✏️ **EDIT {p['name']}**\n\nCurrent: {p['days']} days — ₹{p['price']:.0f}\n\n"
            f"Send: `<days> <price>`\nExample: `30 199`",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", style=BTN_SECONDARY, callback_data="adm_plans")]]))

    elif data == "pln_new":
        if not has_power(uid, "can_plans"):
            return
        _ud(uid)["state"] = "PLN_NEW"
        await query.message.reply_text(
            "➕ **NEW PLAN**\n\nSend: `<name> <days> <price>`\nExample: `Ultra 180 599`",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", style=BTN_SECONDARY, callback_data="adm_plans")]]))

    # ---------- USER STATS ----------
    elif data == "adm_userstats":
        if not is_staff(uid):
            return
        profiles = load_json("profiles.json", {})
        lines = []
        for k, p in sorted(profiles.items(), key=lambda x: -x[1].get("total_spent", 0))[:20]:
            if p.get("total_spent", 0) <= 0:
                continue
            left = None
            if p.get("premium_expiry"):
                try:
                    rem = datetime.fromisoformat(p["premium_expiry"]) - datetime.now()
                    left = rem if rem.total_seconds() > 0 else None
                except:
                    pass
            lines.append(f"• `{k}` | Spent ₹{p.get('total_spent', 0):.0f} | "
                         f"{p.get('purchases', 0)}× | {'♾️ ' + fmt_td(left) if left else '⏰ Expired'}")
        await query.message.reply_text(
            "📊 **TOP USERS (Premium Stats)**\n\n" + ("\n".join(lines) if lines else "No data yet."),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")]]))

    # ---------- FREE PREMIUM ----------
    elif data == "adm_addprem":
        if not has_power(uid, "can_deposit"):
            try:
                await query.answer("🚫 No permission!", show_alert=True)
            except Exception:
                pass
            return
        _ud(uid)["state"] = "ADM_ADDPREM"
        await query.message.reply_text(
            "➕ **ADD FREE PREMIUM**\n\nFormat: `UserID Days`\nExample: `123456789 30`",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Admin Panel", style=BTN_SECONDARY, callback_data="admin_panel")]]))


# ============================================================
# TEXT STATE ROUTER
# ============================================================

async def state_router(client: Client, message: Message):
    if not message or not message.from_user or not message.text:
        return
    uid = message.from_user.id
    ud = _ud(uid)
    state = ud.get("state")
    if not state:
        return
    text = message.text.strip()

    # --- UTR verification (auto deposit) ---
    if state.startswith("WAIT_UTR_"):
        pay_id = state.replace("WAIT_UTR_", "")
        payments = load_json(config.PAYMENTS_FILE, {})
        pay = payments.get(pay_id)
        if not pay or pay["status"] != "PENDING":
            await message.reply_text("❌ Payment session expired! Use 🛒 Deposit Fund again.")
            ud.pop("state", None)
            return
        await message.reply_text("🔍 **Checking payment automatically...**")
        if verify_utr(text, pay["amount"]):
            plan = get_plans()[pay["plan_id"]]
            new_exp = activate_plan(uid, plan["days"], plan["price"])
            pay["status"] = "SUCCESS"
            pay["txn"] = text
            save_json(config.PAYMENTS_FILE, payments)
            ud.pop("state", None)
            await message.reply_text(
                f"🎉 **PAYMENT VERIFIED — PREMIUM ACTIVATED!**\n\n"
                f"💎 {plan['name']} ({plan['days']} days)\n"
                f"⏳ Valid till: `{new_exp.strftime('%d-%m-%Y')}`")
            for aid in {config.OWNER_ID} | ADMIN_IDS:
                try:
                    await client.send_message(
                        aid, f"💳 **NEW DEPOSIT**\n👤 `{uid}`\n"
                             f"💎 {plan['name']} — ₹{plan['price']:.0f}\n🧾 `{text}`")
                except Exception:
                    pass
        else:
            await message.reply_text(
                "❌ **Not verified!**\n\nCheck UTR and send again.")
        return

    # --- Add admin ---
    if state == "ADM_ADDADMIN":
        if uid != config.OWNER_ID:
            return
        try:
            tid = int(text)
            add_admin(tid)
            global ADMIN_IDS
            ADMIN_IDS = load_admins()
            ud.pop("state", None)
            await message.reply_text(f"✅ Admin `{tid}` added!",
                reply_markup=manage_admins_keyboard())
        except ValueError:
            await message.reply_text("❌ Numeric User ID bhejo:")
        return

    # --- Free premium ---
    if state == "ADM_ADDPREM":
        if not has_power(uid, "can_deposit"):
            return
        parts = text.split()
        if len(parts) != 2:
            await message.reply_text("❌ Format: `UserID Days`")
            return
        try:
            tid, days = int(parts[0]), int(parts[1])
            exp = activate_plan(tid, days, 0.0)
            ud.pop("state", None)
            await message.reply_text(
                f"✅ `{tid}` ko **{days} days premium** mil gaya!\n"
                f"⏳ Valid till: `{exp.strftime('%d-%m-%Y')}`",
                reply_markup=admin_panel_keyboard())
        except ValueError:
            await message.reply_text("❌ Invalid input!")
        return

    # --- Maintenance reason ---
    if state == "ADM_MAINT_REASON":
        if not has_power(uid, "can_maintain"):
            return
        set_maintenance(True, text)
        ud.pop("state", None)
        await message.reply_text("🔴 **Maintenance ON!** Users ko ye dikhega:\n\n"
                           f"`{text}`", reply_markup=admin_panel_keyboard())
        return

    # --- Ban flow ---
    if state == "ADM_BAN_ID":
        if not has_power(uid, "can_ban"):
            return
        try:
            target = int(text)
        except ValueError:
            await message.reply_text("❌ Numeric User ID bhejo:")
            return
        if target == config.OWNER_ID or target in ADMIN_IDS:
            await message.reply_text("❌ Admin/Owner ko ban nahi kar sakte!")
            ud.pop("state", None)
            return
        ud["ban_target"] = target
        ud["state"] = "ADM_BAN_REASON"
        await message.reply_text(f"👤 Target: `{target}`\n\n📝 **Ban reason bhejo:**")
        return

    if state == "ADM_BAN_REASON":
        if not has_power(uid, "can_ban"):
            return
        target = ud.pop("ban_target")
        p = get_profile(target)
        p["is_banned"] = True
        p["ban_reason"] = text
        save_profile(target, p)
        ud.pop("state", None)
        await message.reply_text(f"🚫 `{target}` banned!\n**Reason:** {text}",
            reply_markup=admin_panel_keyboard())
        try:
            await client.send_message(target, f"🚫 **You are banned.**\nReason: {text}")
        except Exception:
            pass
        return

    if state == "ADM_UNBAN_ID":
        if not has_power(uid, "can_ban"):
            return
        try:
            target = int(text)
            p = get_profile(target)
            p["is_banned"] = False
            p["ban_reason"] = ""
            save_profile(target, p)
            ud.pop("state", None)
            await message.reply_text(f"🟢 `{target}` unbanned!",
                reply_markup=admin_panel_keyboard())
        except ValueError:
            await message.reply_text("❌ Numeric User ID bhejo:")
        return

    # --- Broadcast DM only ---
    if state == "ADM_BROADCAST":
        if not has_power(uid, "can_broadcast"):
            return
        ud.pop("state", None)
        profiles = load_json("profiles.json", {})
        approved = load_approved_users()
        targets = set(int(k) for k in profiles.keys()) | set(int(k) for k in approved.keys()) | {config.OWNER_ID} | ADMIN_IDS
        ok = fail = 0
        status = await message.reply_text(f"⏳ **Broadcasting to {len(targets)} users...**")
        for t in targets:
            try:
                await client.send_message(t, text)
                ok += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail += 1
        await status.edit_text(f"📢 **Broadcast done!**\n\n🟢 Delivered: {ok}\n🔴 Failed: {fail}",
            reply_markup=admin_panel_keyboard())
        return

    # --- Plan edit ---
    if state.startswith("PLN_PRICE_"):
        if not has_power(uid, "can_plans"):
            return
        pid = state.replace("PLN_PRICE_", "")
        parts = text.split()
        if len(parts) != 2:
            await message.reply_text("❌ Format: `<days> <price>` e.g. `30 199`")
            return
        try:
            days, price = int(parts[0]), float(parts[1])
            plans = get_plans()
            if pid in plans:
                plans[pid]["days"] = days
                plans[pid]["price"] = price
                save_json(config.PLANS_FILE, plans)
            ud.pop("state", None)
            await message.reply_text(f"✅ Plan updated: {days} days — ₹{price:.0f}",
                reply_markup=admin_panel_keyboard())
        except ValueError:
            await message.reply_text("❌ Numbers only!")
        return

    if state == "PLN_NEW":
        if not has_power(uid, "can_plans"):
            return
        parts = text.split()
        if len(parts) != 3:
            await message.reply_text("❌ Format: `<name> <days> <price>`")
            return
        try:
            name, days, price = parts[0], int(parts[1]), float(parts[2])
            plans = get_plans()
            plans[name.lower()] = {"name": name, "days": days, "price": price}
            save_json(config.PLANS_FILE, plans)
            ud.pop("state", None)
            await message.reply_text(f"✅ Plan **{name}** added: {days}d — ₹{price:.0f}",
                reply_markup=admin_panel_keyboard())
        except ValueError:
            await message.reply_text("❌ Invalid!")
        return


# ============================================================
# MAIN COMMANDS
# ============================================================

async def start_command(client, message):
    uid = message.from_user.id

    # --- ban + maintenance gate ---
    prof = get_profile(uid)
    if prof.get("is_banned"):
        await message.reply_text(
            f"🚫 **You are banned.**\n\n**Reason:** {prof.get('ban_reason')}")
        return
    maint_active, maint_reason = get_maintenance()
    if maint_active and not is_staff(uid):
        await message.reply_text(f"🚧 **MAINTENANCE MODE**\n\n{maint_reason}")
        return

    caption = """
Welcome, ⏤͟͞ 𝙎𝙋𝘼𝙍𝙎𝙃 𝘽𝘼𝙉𝙄𝙔𝘼! 👋

Link Changer Bot automatically rotates usernames for your channels — from your username list, with customizable delays and full control.

Supported features: Auto-rotation, Custom delays, Channel management, Username lists and more.

Use the buttons below to add Link Changer Bot to your channel, or explore everything it can do."""

    keyboard = [
        [
            InlineKeyboardButton("👨‍💻 Developer", style=BTN_PRIMARY, url=f"tg://user?id={config.OWNER_ID}"),
            InlineKeyboardButton("📢 Channel", style=BTN_SECONDARY, url=config.CHANNEL_LINK),
        ],
        [
            InlineKeyboardButton("🆘 Support", style=BTN_SECONDARY, url=config.SUPPORT_LINK),
            InlineKeyboardButton("❓ Help", style=BTN_DEFAULT, callback_data="help"),
        ],
        [
            InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit"),
            InlineKeyboardButton("👤 My Profile", style=BTN_PRIMARY, callback_data="menu_profile"),
        ],
    ]
    if is_staff(uid):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", style=BTN_DANGER, callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    image_url = "https://files.catbox.moe/rbalef.jpg"

    await message.reply_photo(
        photo=image_url,
        caption=caption,
        reply_markup=reply_markup
    )


async def connect_command(client, message):
    global client_telethon, entity_cache_loaded  # noqa (client here = bot client)

    if not await authorized_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error("Usage:\n/connect <session_string>"))
        return

    session_string = args[0].strip()

    try:
        test_client = TelegramClient(
            StringSession(session_string),
            config.API_ID,
            config.API_HASH
        )

        await test_client.connect()

        if not await test_client.is_user_authorized():
            await test_client.disconnect()
            await message.reply_text(format_error("Invalid session string."))
            return

        me = await test_client.get_me()

        session_data["session"] = session_string
        save_json(config.SESSION_FILE, session_data)

        if globals()["client"]:
            try:
                await globals()["client"].disconnect()
            except Exception:
                pass

        globals()["client"] = test_client
        entity_cache_loaded = False

        await load_entity_cache()

        await message.reply_text(
            f"""{format_success("Session Connected")}

┌─ ACCOUNT INFO
│
  • ID: {me.id}
  • Name: {me.first_name or 'Unknown'}
  • Username: @{me.username if me.username else 'N/A'}
└─"""
        )

    except Exception as e:
        await message.reply_text(format_error(f"Connection failed:\n{e}"))


async def addchannel_command(client, message):
    if not await authorized_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error("Usage:\n/addchannel https://t.me/channelname"))
        return

    link = args[0]

    try:
        entity = await set_target(link, "channel")

        await message.reply_text(
            f"""{format_success("Channel Added")}

┌─ CHANNEL INFO
│
  • ID: {entity.id}
  • Link: {link}
  • Type: Broadcast Channel
└─

Ready for username rotation!"""
        )

    except Exception as e:
        await message.reply_text(format_error(f"Failed to add channel:\n{e}"))


async def addgroup_command(client, message):
    if not await authorized_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error("Usage:\n/addgroup https://t.me/groupname"))
        return

    link = args[0]

    try:
        entity = await set_target(link, "group")

        await message.reply_text(
            f"""{format_success("Group Added")}

┌─ GROUP INFO
│
  • ID: {entity.id}
  • Link: {link}
  • Type: Group
└─

Note: Ordinary groups do not support username updates via API."""
        )

    except Exception as e:
        await message.reply_text(format_error(f"Failed to add group:\n{e}"))


async def addusername_command(client, message):
    global usernames

    if not await authorized_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error("Usage:\n/addusername @name1, @name2"))
        return

    raw = " ".join(args)
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

    await message.reply_text(
        f"""{format_success("Usernames Added")}

┌─ SUMMARY
│
  • Added: {added}
  • Skipped (duplicates): {skipped}
  • Total usernames: {len(usernames)}
└─

Use /list to view all usernames"""
    )


async def done_command(client, message):
    global usernames

    if not await authorized_only(message):
        return

    usernames = load_usernames()

    await message.reply_text(
        f"""{format_success("Username List Finalized")}

┌─ STATS
│
  • Total usernames: {len(usernames)}
  • Status: Ready for rotation
└─

Use /forcestart to begin rotation"""
    )


async def setdelay_command(client, message):
    global delay_seconds

    if not await authorized_only(message):
        return

    args = message.command[1:]

    if not args:
        await message.reply_text(format_error(
            "Usage:\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 1h 30m 10s"
        ))
        return

    text = " ".join(args)

    try:
        delay_seconds = parse_delay(text)

        await message.reply_text(
            f"""{format_success("Delay Updated")}

┌─ NEW DELAY
│
  • Value: {format_delay(delay_seconds)}
  • Seconds: {delay_seconds}s
└─"""
        )

    except ValueError as e:
        await message.reply_text(format_error(str(e)))


async def forcestart_command(client, message):
    global rotation_task

    if not await authorized_only(message):
        return

    # --- premium gate ---
    uid = message.from_user.id
    if not is_staff(uid) and not is_premium(uid):
        await message.reply_text(
            "🔒 **Premium required!**\n\n🛒 Buy a plan from 🛒 Deposit Fund button.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit")]]))
        return

    if not target_data.get("target_id"):
        await message.reply_text(
            format_error("No target set!\nUse /addgroup or /addchannel")
        )
        return

    if not usernames:
        await message.reply_text(
            format_error("No usernames added.\nUse /addusername")
        )
        return

    tg = await ensure_client()

    if not tg:
        await message.reply_text(
            format_error("Telegram session not connected.\nUse /connect")
        )
        return

    if rotation_task and not rotation_task.done():
        await message.reply_text(format_info("Rotation is already running."))
        return

    rotation_task = asyncio.create_task(rotation_loop())

    await message.reply_text(
        f"""🚀 Rotation Started

┌─ CONFIGURATION
│
  • Target ID: {target_data['target_id']}
  • Target Type: {target_data.get('target_type', 'N/A')}
  • Usernames: {len(usernames)}
  • Delay: {format_delay(delay_seconds)}
  • Starting Index: {current_index + 1}
└─

Use /status to monitor progress"""
    )


async def forcestop_command(client, message):
    global rotation_task

    if not await authorized_only(message):
        return

    if rotation_task and not rotation_task.done():
        rotation_task.cancel()
        try:
            await rotation_task
        except asyncio.CancelledError:
            pass

        rotation_task = None

        await message.reply_text(
            f"""⏹️ Rotation Stopped

┌─ STATUS
│
  • Rotation has been stopped successfully
  • Current index: {current_index + 1}
└─"""
        )
    else:
        await message.reply_text(format_info("Rotation is not running."))


async def change_now_command(client, message):
    global current_index

    if not await authorized_only(message):
        return

    # --- premium gate ---
    uid = message.from_user.id
    if not is_staff(uid) and not is_premium(uid):
        await message.reply_text(
            "🔒 **Premium required!**\n\n🛒 Buy a plan from 🛒 Deposit Fund button.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛒 Deposit Fund", style=BTN_SUCCESS, callback_data="menu_deposit")]]))
        return

    if not target_data.get("target_id"):
        await message.reply_text(
            format_error("No target set!\nUse /addgroup or /addchannel")
        )
        return

    if not usernames:
        await message.reply_text(
            format_error("Username list is empty.\nUse /addusername")
        )
        return

    await load_entity_cache()

    username = usernames[current_index]

    status_msg = await message.reply_text(
        f"""┌─ CHANGING USERNAME
│
  • Username: @{username}
  • Index: {current_index + 1}/{len(usernames)}
└─
Please wait..."""
    )

    success, result = await change_username(username)

    if success:
        current_index = (current_index + 1) % len(usernames)
        await status_msg.edit_text(
            f"""{format_success("Username Changed Successfully")}

┌─ UPDATE COMPLETE
│
  • New Username: @{result}
  • Next Index: {current_index + 1}/{len(usernames)}
└─"""
        )
    else:
        await status_msg.edit_text(
            f"""{format_error("Username Change Failed")}

┌─ ERROR DETAILS
│
  • Username: @{username}
  • Error: {result}
└─"""
        )


async def status_command(client, message):
    if not await authorized_only(message):
        return

    tg = await ensure_client()

    session_connected = tg is not None
    session_status = format_status("Connected", session_connected) if session_connected else format_status("Not Connected", False)

    target_set = target_data.get("target_id") is not None
    target_status = format_status("Set", target_set) if target_set else format_status("Not Set", False)

    running = rotation_task is not None and not rotation_task.done()
    rotation_status = format_status("Running", running) if running else format_status("Stopped", False)

    await message.reply_text(
        f"""📊 System Status

┌─ SESSION
│  {session_status}
│
├─ TARGET
│  {target_status}
│  • ID: {target_data.get('target_id') or 'N/A'}
│  • Type: {target_data.get('target_type') or 'N/A'}
│  • Link: {target_data.get('target_link') or 'N/A'}
│
├─ USERNAMES
│  • Count: {len(usernames)}
│  • Current Index: {current_index + 1}/{len(usernames) if usernames else '0'}
│  • Next: @{usernames[current_index] if usernames else 'N/A'}
│
├─ DELAY
│  • {format_delay(delay_seconds)}
│
└─ ROTATION
   {rotation_status}
   • Task: {'Active' if running else 'Idle'}"""
    )


async def list_command(client, message):
    if not await authorized_only(message):
        return

    if not usernames:
        await message.reply_text(
            f"""{format_info("Username List")}

┌─ EMPTY
│
  • No usernames have been added yet.
  • Use /addusername to add some.
└─"""
        )
        return

    chunk_size = 30
    chunks = [usernames[i:i + chunk_size] for i in range(0, len(usernames), chunk_size)]

    for idx, chunk in enumerate(chunks, 1):
        formatted_list = []
        for i, name in enumerate(chunk, 1):
            formatted_list.append(f"  {i + (idx-1) * chunk_size}. @{name}")

        text = f"""📋 Username List {idx}/{len(chunks)}

{chr(10).join(formatted_list)}
"""
        await message.reply_text(text)


async def clear_command(client, message):
    global usernames, current_index

    if not await authorized_only(message):
        return

    usernames = []
    current_index = 0
    save_usernames(usernames)

    await message.reply_text(
        f"""{format_success("List Cleared")}

┌─ COMPLETE
│
  • All usernames have been removed.
  • Current index reset to 0.
└─"""
    )


async def current_command(client, message):
    if not await authorized_only(message):
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

    await message.reply_text(
        f"""🎯 Current Target

┌─ DETAILS
│
  • ID: {target_data.get('target_id')}
  • Type: {target_data.get('target_type')}
  • Link: {target_data.get('target_link') or 'N/A'}
  • Title: {current_title}
  • Username: {current_username}
└─"""
    )


# ============================================================
# MAIN
# ============================================================

app = Client(
    "link_changer_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)


def main():
    print("""
╔═══════════════════════════════════════╗
║     Telegram Link Changer Bot         ║
║          Version 5.0 (Kurigram)       ║
║  Admin Panel + Plans + Auto Deposit   ║
╚═══════════════════════════════════════╝
    """)

    # ---- Approval commands (Owner only) ----
    app.add_handler(MessageHandler(approved_list_command, filters.command("approved") & filters.private))
    app.add_handler(MessageHandler(approve_command, filters.command("approve") & filters.private))
    app.add_handler(MessageHandler(revoke_command, filters.command("revoke") & filters.private))

    # ---- Main commands ----
    commands = {
        "start": start_command,
        "mystatus": mystatus_command,
        "connect": connect_command,
        "addchannel": addchannel_command,
        "addgroup": addgroup_command,
        "addusername": addusername_command,
        "done": done_command,
        "setdelay": setdelay_command,
        "forcestart": forcestart_command,
        "forcestop": forcestop_command,
        "change_now": change_now_command,
        "status": status_command,
        "list": list_command,
        "clear": clear_command,
        "current": current_command,
    }
    for cmd, fn in commands.items():
        app.add_handler(MessageHandler(fn, filters.command(cmd) & filters.private))

    # ---- Callback handler (colored buttons) ----
    app.add_handler(CallbackQueryHandler(button_callback))

    # ---- Text state router (UTR, admin flows) — commands excluded ----
    app.add_handler(MessageHandler(
        filters.text & filters.private & ~filters.command(
            list(commands.keys()) + ["approve", "revoke", "approved"]),
        state_router))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run()


if __name__ == "__main__":
    threading.Thread(target=_email_watcher_loop, daemon=True).start()
    main()