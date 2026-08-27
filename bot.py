import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
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
from telegram.error import RetryAfter

import config


# ============================================================
# USER MANAGEMENT
# ============================================================

class UserManager:
    def __init__(self):
        self.users_file = "users.json"
        self.pending_file = "pending_payments.json"
        self.sudo_file = "sudo_users.json"
        self.load_data()
    
    def load_data(self):
        """Load all data from JSON files"""
        if not os.path.exists(self.users_file):
            self.users = {}
            self.save_users()
        else:
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    self.users = json.load(f)
            except:
                self.users = {}
        
        if not os.path.exists(self.pending_file):
            self.pending = {}
            self.save_pending()
        else:
            try:
                with open(self.pending_file, "r", encoding="utf-8") as f:
                    self.pending = json.load(f)
            except:
                self.pending = {}
        
        if not os.path.exists(self.sudo_file):
            self.sudo_users = []
            self.save_sudo()
        else:
            try:
                with open(self.sudo_file, "r", encoding="utf-8") as f:
                    self.sudo_users = json.load(f)
            except:
                self.sudo_users = []
    
    def save_users(self):
        with open(self.users_file, "w", encoding="utf-8") as f:
            json.dump(self.users, f, indent=4)
    
    def save_pending(self):
        with open(self.pending_file, "w", encoding="utf-8") as f:
            json.dump(self.pending, f, indent=4)
    
    def save_sudo(self):
        with open(self.sudo_file, "w", encoding="utf-8") as f:
            json.dump(self.sudo_users, f, indent=4)
    
    def is_owner(self, user_id: int) -> bool:
        return user_id == config.OWNER_ID
    
    def is_sudo(self, user_id: int) -> bool:
        return str(user_id) in self.sudo_users
    
    def is_registered(self, user_id: int) -> bool:
        return str(user_id) in self.users
    
    def is_active(self, user_id: int) -> bool:
        if not self.is_registered(user_id):
            return False
        if self.is_sudo(user_id):
            return True
        user_data = self.users[str(user_id)]
        expiry = user_data.get("expiry", 0)
        return time.time() < expiry
    
    def register_user(self, user_id: int, username: str = None, first_name: str = None):
        user_id_str = str(user_id)
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                "username": username,
                "first_name": first_name,
                "joined": time.time(),
                "expiry": 0,
                "plan": None,
                "active": False,
                "is_sudo": False
            }
            self.save_users()
    
    def activate_user(self, user_id: int, plan_days: int):
        user_id_str = str(user_id)
        if user_id_str in self.users:
            current_expiry = self.users[user_id_str].get("expiry", 0)
            new_expiry = max(current_expiry, time.time()) + (plan_days * 24 * 3600)
            self.users[user_id_str]["expiry"] = new_expiry
            self.users[user_id_str]["plan"] = self.get_plan_name(plan_days)
            self.users[user_id_str]["active"] = True
            self.save_users()
            return True
        return False
    
    def add_sudo_user(self, user_id: int) -> bool:
        user_id_str = str(user_id)
        if user_id_str not in self.sudo_users:
            self.sudo_users.append(user_id_str)
            self.save_sudo()
            if user_id_str in self.users:
                self.users[user_id_str]["is_sudo"] = True
                self.users[user_id_str]["plan"] = "Sudo Unlimited"
                self.users[user_id_str]["active"] = True
                self.users[user_id_str]["expiry"] = float('inf')
                self.save_users()
            return True
        return False
    
    def remove_sudo_user(self, user_id: int) -> bool:
        user_id_str = str(user_id)
        if user_id_str in self.sudo_users:
            self.sudo_users.remove(user_id_str)
            self.save_sudo()
            if user_id_str in self.users:
                self.users[user_id_str]["is_sudo"] = False
                self.users[user_id_str]["plan"] = None
                self.save_users()
            return True
        return False
    
    def get_sudo_users(self) -> List[str]:
        return self.sudo_users
    
    def add_pending_payment(self, user_id: int, plan_days: int, username: str = None):
        user_id_str = str(user_id)
        payment_id = f"pay_{int(time.time())}_{user_id_str}"
        self.pending[payment_id] = {
            "user_id": user_id_str,
            "username": username,
            "plan_days": plan_days,
            "amount": self.get_plan_price(plan_days),
            "plan_name": self.get_plan_name(plan_days),
            "timestamp": time.time(),
            "status": "pending"
        }
        self.save_pending()
        return payment_id
    
    def get_pending_payments(self):
        return {k: v for k, v in self.pending.items() if v.get("status") == "pending"}
    
    def approve_payment(self, payment_id: str):
        if payment_id in self.pending:
            payment = self.pending[payment_id]
            if payment.get("status") == "pending":
                user_id = int(payment["user_id"])
                plan_days = payment["plan_days"]
                self.activate_user(user_id, plan_days)
                self.pending[payment_id]["status"] = "approved"
                self.pending[payment_id]["approved_at"] = time.time()
                self.save_pending()
                return True
        return False
    
    def reject_payment(self, payment_id: str):
        if payment_id in self.pending:
            self.pending[payment_id]["status"] = "rejected"
            self.save_pending()
            return True
        return False
    
    def get_plan_price(self, plan_days: int) -> float:
        prices = {
            7: 150.0,
            14: 260.0,
            30: 500.0,
            -1: 900.0
        }
        return prices.get(plan_days, 0)
    
    def get_plan_name(self, plan_days: int) -> str:
        if plan_days == -1:
            return "Unlimited Plan"
        return f"{plan_days} Days Plan"
    
    def get_remaining_time(self, user_id: int) -> int:
        if self.is_sudo(user_id):
            return -1
        if not self.is_registered(user_id):
            return 0
        user_data = self.users[str(user_id)]
        expiry = user_data.get("expiry", 0)
        remaining = max(0, expiry - time.time())
        return int(remaining)
    
    def format_remaining_time(self, user_id: int) -> str:
        if self.is_sudo(user_id):
            return "♾️ Unlimited"
        remaining = self.get_remaining_time(user_id)
        if remaining <= 0:
            return "Expired"
        days = remaining // 86400
        hours = (remaining % 86400) // 3600
        minutes = (remaining % 3600) // 60
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "0m"


# ============================================================
# UI HELPERS
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


def format_waiting(message: str) -> str:
    return f"""
┌─ ⏳ WAITING
│
{message}
└─"""


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
# SAFE MESSAGE FUNCTIONS
# ============================================================

async def safe_edit_message(message, text, reply_markup=None, max_retries=3):
    """Safely edit message with retry on flood error"""
    for attempt in range(max_retries):
        try:
            if reply_markup:
                await message.edit_text(text=text, reply_markup=reply_markup)
            else:
                await message.edit_text(text=text)
            return True
        except RetryAfter as e:
            wait_time = e.retry_after
            print(f"Flood control: waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time + 1)
        except Exception as e:
            error_str = str(e)
            if "Message is not modified" in error_str:
                return True
            if "There is no text in the message to edit" in error_str:
                return False
            print(f"Edit error: {e}")
            if attempt == max_retries - 1:
                return False
            await asyncio.sleep(1)
    return False


async def safe_reply_text(update, text, reply_markup=None, max_retries=3):
    """Safely reply with retry on flood error"""
    for attempt in range(max_retries):
        try:
            if reply_markup:
                return await update.message.reply_text(text=text, reply_markup=reply_markup)
            else:
                return await update.message.reply_text(text=text)
        except RetryAfter as e:
            wait_time = e.retry_after
            print(f"Flood control: waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time + 1)
        except Exception as e:
            print(f"Reply error: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
    return None


async def safe_send_message(context, chat_id, text, reply_markup=None, max_retries=3):
    """Safely send message with retry on flood error"""
    for attempt in range(max_retries):
        try:
            if reply_markup:
                return await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup
                )
            else:
                return await context.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )
        except RetryAfter as e:
            wait_time = e.retry_after
            print(f"Flood control: waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time + 1)
        except Exception as e:
            print(f"Send message error: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
    return None


# ============================================================
# ANIMATION HELPERS
# ============================================================

async def animate_initialization(update, context, user_manager):
    """Create an animated initialization sequence for non-owners."""
    
    init_text = "𝒾𝓃𝒾𝓉𝒾𝒶𝓁𝒾𝓏𝒾𝓃𝑔"
    
    welcome_template = f"""
╔═══════════════════════════════════════════╗
║                                           ║
║    {init_text}    ║
║                                           ║
║       🔐 RESTRICTED ACCESS               ║
║                                           ║
╚═══════════════════════════════════════════╝

┌─ 🔒 ACCESS DENIED
│
  • This bot is for authorized users only.
  • Please purchase a plan to use the bot.
  • Contact owner for more information.

┌─ 💳 BUY PLAN
│
  • 7 Days Plan - ₹150
  • 14 Days Plan - ₹260  
  • 30 Days Plan - ₹500
  • Unlimited Plan - ₹900

└─

💡 Click the buttons below to get started!"""

    keyboard = [
        [
            InlineKeyboardButton("💳 Buy Plan", callback_data="buy_plan"),
            InlineKeyboardButton("📋 Plans", callback_data="plans"),
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
            InlineKeyboardButton("📞 Contact", callback_data="contact"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    parts = welcome_template.split(init_text)
    initial_message = parts[0] + " " * len(init_text) + parts[1]
    
    message = await safe_reply_text(update, initial_message, reply_markup)
    if not message:
        return
    
    for i in range(1, len(init_text) + 1):
        animated_text = parts[0] + init_text[:i] + " " * (len(init_text) - i) + parts[1]
        success = await safe_edit_message(message, animated_text, reply_markup)
        if not success:
            break
        await asyncio.sleep(0.15)
    
    for _ in range(3):
        glow_text = parts[0] + f"✨{init_text}✨" + parts[1]
        await safe_edit_message(message, glow_text, reply_markup)
        await asyncio.sleep(0.2)
        normal_text = parts[0] + init_text + parts[1]
        await safe_edit_message(message, normal_text, reply_markup)
        await asyncio.sleep(0.2)
    
    final_message = welcome_template.replace(init_text, f"🔒 {init_text} 🔒")
    await safe_edit_message(message, final_message, reply_markup)


async def animate_owner_start(update, context, user_manager):
    """Animated start for owner with full access."""
    
    init_text = "𝒾𝓃𝒾𝓉𝒾𝒶𝓁𝒾𝓏𝒾𝓃𝑔"
    
    welcome_template = f"""
╔═══════════════════════════════════════════╗
║                                           ║
║    {init_text}    ║
║                                           ║
║       👑 OWNER ACCESS                    ║
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
│
│  💳 PAYMENTS
│    /pending - View pending payments
│    /approve <id> - Approve payment
│    /reject <id> - Reject payment
│    /users - List all users
│
│  👑 SUDO MANAGEMENT
│    /addsudo <user_id> - Add sudo user
│    /rmsudo <user_id> - Remove sudo user
│    /sudolist - List sudo users
└─

💡 Use buttons below for quick access!"""

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
            InlineKeyboardButton("💳 Pending", callback_data="pending_payments"),
            InlineKeyboardButton("👥 Users", callback_data="list_users"),
        ],
        [
            InlineKeyboardButton("👑 Sudo Users", callback_data="list_sudo"),
            InlineKeyboardButton("📖 Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    parts = welcome_template.split(init_text)
    initial_message = parts[0] + " " * len(init_text) + parts[1]
    
    message = await safe_reply_text(update, initial_message, reply_markup)
    if not message:
        return
    
    for i in range(1, len(init_text) + 1):
        animated_text = parts[0] + init_text[:i] + " " * (len(init_text) - i) + parts[1]
        success = await safe_edit_message(message, animated_text, reply_markup)
        if not success:
            break
        await asyncio.sleep(0.15)
    
    for _ in range(3):
        glow_text = parts[0] + f"✨{init_text}✨" + parts[1]
        await safe_edit_message(message, glow_text, reply_markup)
        await asyncio.sleep(0.2)
        normal_text = parts[0] + init_text + parts[1]
        await safe_edit_message(message, normal_text, reply_markup)
        await asyncio.sleep(0.2)
    
    final_message = welcome_template.replace(init_text, f"✅ {init_text} ✅")
    await safe_edit_message(message, final_message, reply_markup)


async def animate_user_start(update, context, user_manager, user_id):
    """Animated start for active users."""
    
    init_text = "𝒾𝓃𝒾𝓉𝒾𝒶𝓁𝒾𝓏𝒾𝓃𝑔"
    
    remaining = user_manager.format_remaining_time(user_id)
    plan = user_manager.users[str(user_id)].get('plan', 'N/A')
    
    welcome_template = f"""
╔═══════════════════════════════════════════╗
║                                           ║
║    {init_text}    ║
║                                           ║
║       ✅ ACCESS GRANTED                   ║
║                                           ║
╚═══════════════════════════════════════════╝

┌─ 👤 USER INFO
│
  • ID: {user_id}
  • Plan: {plan}
  • Remaining: {remaining}
  • Status: 🟢 Active
│
├─ 🚀 COMMANDS
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
│
└─

💡 You have full access! Use buttons below."""

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
        [
            InlineKeyboardButton("💳 Renew Plan", callback_data="buy_plan"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    parts = welcome_template.split(init_text)
    initial_message = parts[0] + " " * len(init_text) + parts[1]
    
    message = await safe_reply_text(update, initial_message, reply_markup)
    if not message:
        return
    
    for i in range(1, len(init_text) + 1):
        animated_text = parts[0] + init_text[:i] + " " * (len(init_text) - i) + parts[1]
        success = await safe_edit_message(message, animated_text, reply_markup)
        if not success:
            break
        await asyncio.sleep(0.15)
    
    for _ in range(3):
        glow_text = parts[0] + f"✨{init_text}✨" + parts[1]
        await safe_edit_message(message, glow_text, reply_markup)
        await asyncio.sleep(0.2)
        normal_text = parts[0] + init_text + parts[1]
        await safe_edit_message(message, normal_text, reply_markup)
        await asyncio.sleep(0.2)
    
    final_message = welcome_template.replace(init_text, f"✅ {init_text} ✅")
    await safe_edit_message(message, final_message, reply_markup)


# ============================================================
# PAYMENT HANDLERS
# ============================================================

async def show_plans(update, context):
    """Show available plans with prices."""
    query = update.callback_query
    
    if not query or not query.message:
        return
    
    keyboard = [
        [
            InlineKeyboardButton("📅 7 Days - ₹150", callback_data="plan_7"),
            InlineKeyboardButton("📅 14 Days - ₹260", callback_data="plan_14"),
        ],
        [
            InlineKeyboardButton("📅 30 Days - ₹500", callback_data="plan_30"),
            InlineKeyboardButton("♾️ Unlimited - ₹900", callback_data="plan_-1"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_to_menu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_header("💳 Choose Your Plan", "💳")}

┌─ 📋 PLANS
│
│  📅 7 Days Plan
│    • Price: ₹150
│    • Full bot access
│    • Priority support
│    • Unlimited username rotation
│
│  📅 14 Days Plan
│    • Price: ₹260
│    • Full bot access
│    • Priority support
│    • Unlimited username rotation
│    • Early features access
│
│  📅 30 Days Plan
│    • Price: ₹500
│    • Full bot access
│    • Priority support
│    • Unlimited username rotation
│    • Early features access
│    • Best value!
│
│  ♾️ Unlimited Plan
│    • Price: ₹900
│    • Lifetime access
│    • Premium support
│    • All features included
│    • Best for long-term users!
│
└─

💳 Select a plan to proceed with payment."""
    
    try:
        await query.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        error_str = str(e)
        if "Message is not modified" in error_str:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
        elif "There is no text in the message to edit" in error_str:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
        else:
            print(f"Error showing plans: {e}")


async def show_payment(update, context, plan_days):
    """Show payment details with QR code."""
    query = update.callback_query
    
    if not query or not query.message:
        return
    
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    
    user_manager = context.bot_data.get('user_manager')
    payment_id = user_manager.add_pending_payment(user_id, plan_days, username)
    
    amount = user_manager.get_plan_price(plan_days)
    plan_name = user_manager.get_plan_name(plan_days)
    
    qr_path = "qr.jpg"
    qr_exists = os.path.exists(qr_path)
    
    keyboard = [
        [
            InlineKeyboardButton("✅ I've Paid", callback_data=f"paid_{payment_id}"),
            InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{payment_id}"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Plans", callback_data="plans"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = f"""{format_header("💳 Payment Details", "💳")}

┌─ 📝 PAYMENT INFO
│
  • Plan: {plan_name}
  • Amount: ₹{amount:.0f}
  • Payment ID: `{payment_id}`
│
├─ 📋 INSTRUCTIONS
│  1. Scan the QR code below
│  2. Send payment of ₹{amount:.0f}
│  3. Click "I've Paid" button
│  4. Wait for owner verification (1 hour max)
│
└─

⏳ Waiting for payment verification...
Owner will approve your payment shortly."""
    
    try:
        if qr_exists:
            try:
                await query.message.delete()
            except:
                pass
            
            with open(qr_path, "rb") as f:
                await query.message.reply_photo(
                    photo=f,
                    caption=message_text,
                    reply_markup=reply_markup
                )
        else:
            try:
                await query.message.edit_text(
                    text=f"""{message_text}

⚠️ QR code not found. Please contact owner for payment details.""",
                    reply_markup=reply_markup
                )
            except Exception as e:
                if "There is no text in the message to edit" in str(e):
                    await query.message.reply_text(
                        text=f"""{message_text}

⚠️ QR code not found. Please contact owner for payment details.""",
                        reply_markup=reply_markup
                    )
                else:
                    raise
    except Exception as e:
        print(f"Error showing payment: {e}")


async def send_to_logger_group(context, text, photo_path=None):
    """Send message to logger group with QR code"""
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=config.LOGGER_GROUP_ID,
                    photo=f,
                    caption=text
                )
        else:
            await context.bot.send_message(
                chat_id=config.LOGGER_GROUP_ID,
                text=text
            )
        print(f"✅ Sent to logger group: {config.LOGGER_GROUP_ID}")
    except Exception as e:
        print(f"❌ Failed to send to logger group: {e}")


async def go_back_to_menu(update, context):
    """Go back to main menu based on user type."""
    query = update.callback_query
    user_id = query.from_user.id
    user_manager = context.bot_data.get('user_manager')
    
    try:
        if user_manager.is_owner(user_id):
            await animate_owner_start(update, context, user_manager)
        elif user_manager.is_active(user_id):
            await animate_user_start(update, context, user_manager, user_id)
        else:
            await animate_initialization(update, context, user_manager)
    except Exception as e:
        print(f"Error going back: {e}")
        # Fallback: send simple message
        try:
            if user_manager.is_owner(user_id):
                await query.message.reply_text("👑 Welcome back, Owner!")
            elif user_manager.is_active(user_id):
                await query.message.reply_text("✅ Welcome back! Use /start for menu.")
            else:
                await query.message.reply_text("🔒 Please purchase a plan to use the bot.")
        except:
            pass


async def handle_payment_callback(update, context):
    """Handle payment-related callbacks."""
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception as e:
        print(f"Error answering callback: {e}")
    
    user_manager = context.bot_data.get('user_manager')
    data = query.data
    user_id = query.from_user.id
    
    print(f"Callback received: {data}")
    
    # Back to main menu
    if data == "back_to_menu" or data == "back":
        await go_back_to_menu(update, context)
        return
    
    # Buy plan
    if data == "buy_plan":
        await show_plans(update, context)
        return
    
    # Show plans
    if data == "plans":
        await show_plans(update, context)
        return
    
    # Select plan
    if data.startswith("plan_"):
        plan_days = int(data.split("_")[1])
        await show_payment(update, context, plan_days)
        return
    
    # I've Paid button
    if data.startswith("paid_"):
        payment_id = data.split("_")[1]
        print(f"Payment clicked: {payment_id}")
        
        if payment_id in user_manager.pending:
            payment = user_manager.pending[payment_id]
            
            if payment.get("status") == "pending":
                # Send waiting message to user
                try:
                    try:
                        await query.message.delete()
                    except:
                        pass
                    
                    await query.message.reply_text(
                        text=f"""{format_waiting("⏳ Payment Submitted!")}

┌─ 📤 WAITING FOR APPROVAL
│
  • Payment ID: `{payment_id}`
  • Status: ⏳ Waiting for owner approval
│
├─ 📋 WHAT HAPPENS NEXT
│  1. ✅ Owner has been notified
│  2. 👀 Owner will verify your payment
│  3. 🔔 You will be notified when approved
│
└─

⏱️ Please wait for owner to approve your payment.
📢 This usually takes a few minutes to 1 hour."""
                    )
                except Exception as e:
                    print(f"Error sending waiting message: {e}")
                
                # Send to logger group with QR code
                qr_path = "qr.jpg"
                
                logger_text = f"""
┌─ 💳 NEW PAYMENT REQUEST
│
  • Payment ID: `{payment_id}`
  • User: @{payment['username']}
  • User ID: {payment['user_id']}
  • Plan: {payment['plan_name']}
  • Amount: ₹{payment['amount']:.0f}
  • Time: {datetime.fromtimestamp(payment['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}
│
├─ 📋 ACTIONS
│  Use these commands in bot:
│  /approve {payment_id} - ✅ Approve Payment
│  /reject {payment_id} - ❌ Reject Payment
│
└─

⏳ Waiting for owner approval..."""
                
                # Send to logger group
                await send_to_logger_group(context, logger_text, qr_path)
                
                return
    
    # Refresh payment status
    if data.startswith("refresh_"):
        payment_id = data.split("_")[1]
        if payment_id in user_manager.pending:
            payment = user_manager.pending[payment_id]
            status = payment.get("status", "pending")
            
            try:
                if status == "approved":
                    await query.message.edit_text(
                        text=f"""{format_success("🎉 Payment Approved!")}

┌─ ✅ ACCESS GRANTED
│
  • Your payment has been verified!
  • You now have full access to the bot.
  • Use /start to get started.
│
└─

🎊 Welcome aboard!"""
                    )
                elif status == "rejected":
                    await query.message.edit_text(
                        text=f"""{format_error("❌ Payment Rejected")}

┌─ ❌ PAYMENT FAILED
│
  • Your payment was rejected.
  • Please contact owner for assistance.
  • You can try again with a new payment.
│
└─

💡 Contact @owner for help."""
                    )
                else:
                    await query.message.edit_text(
                        text=f"""{format_waiting("⏳ Still Waiting")}

┌─ ⏳ PENDING
│
  • Payment ID: `{payment_id}`
  • Status: Waiting for verification
  • Owner has been notified
│
└─

⏱️ Please wait for owner to verify your payment."""
                    )
            except Exception as e:
                print(f"Error refreshing status: {e}")
        return
    
    # Pending payments list (owner only)
    if data == "pending_payments":
        if not user_manager.is_owner(user_id):
            await query.message.edit_text(
                text=format_error("❌ You are not authorized to view pending payments.")
            )
            return
        
        pending = user_manager.get_pending_payments()
        if pending:
            text = f"""{format_header("💳 Pending Payments", "💳")}

┌─ 📋 LIST
│"""
            for pid, payment in pending.items():
                text += f"""
│  • ID: `{pid}`
│    User: @{payment['username']}
│    Plan: {payment['plan_name']}
│    Amount: ₹{payment['amount']:.0f}
│    Time: {datetime.fromtimestamp(payment['timestamp']).strftime('%Y-%m-%d %H:%M')}
│"""
            
            text += """
└─

📌 Use /approve <id> or /reject <id> to manage payments."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_pending")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.message.edit_text(text=text, reply_markup=reply_markup)
            except Exception as e:
                print(f"Error showing pending: {e}")
        else:
            try:
                await query.message.edit_text(
                    text=f"""{format_info("No Pending Payments")}

┌─ 📭 EMPTY
│
  • There are no pending payments.
  • All payments have been processed.
└─""",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
                    ])
                )
            except Exception as e:
                print(f"Error showing empty pending: {e}")
        return
    
    # List users (owner only)
    if data == "list_users":
        if not user_manager.is_owner(user_id):
            await query.message.edit_text(
                text=format_error("❌ You are not authorized to view users.")
            )
            return
        
        users = user_manager.users
        if users:
            text = f"""{format_header("👥 Registered Users", "👥")}

┌─ 📋 LIST
│"""
            for uid, user in users.items():
                remaining = user_manager.format_remaining_time(int(uid))
                status = "🟢 Active" if user_manager.is_active(int(uid)) else "🔴 Expired"
                is_sudo = "👑" if user_manager.is_sudo(int(uid)) else ""
                text += f"""
│  {is_sudo} ID: {uid}
│    User: @{user.get('username', 'N/A')}
│    Plan: {user.get('plan', 'None')}
│    Status: {status}
│    Remaining: {remaining}
│"""
            
            text += """
└─"""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_users")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.message.edit_text(text=text, reply_markup=reply_markup)
            except Exception as e:
                print(f"Error showing users: {e}")
        else:
            try:
                await query.message.edit_text(
                    text=f"""{format_info("No Users")}

┌─ 📭 EMPTY
│
  • No users have registered yet.
└─""",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
                    ])
                )
            except Exception as e:
                print(f"Error showing empty users: {e}")
        return
    
    # List sudo users (owner only)
    if data == "list_sudo":
        if not user_manager.is_owner(user_id):
            await query.message.edit_text(
                text=format_error("❌ You are not authorized to view sudo users.")
            )
            return
        
        sudo_users = user_manager.get_sudo_users()
        if sudo_users:
            text = f"""{format_header("👑 Sudo Users", "👑")}

┌─ 📋 LIST
│"""
            for uid in sudo_users:
                user = user_manager.users.get(uid, {})
                text += f"""
│  • ID: {uid}
│    User: @{user.get('username', 'N/A')}
│    Plan: {user.get('plan', 'Sudo Unlimited')}
│    Status: 🟢 Active (Unlimited)
│"""
            
            text += """
└─

📌 Sudo users have unlimited lifetime access."""
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_sudo")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.message.edit_text(text=text, reply_markup=reply_markup)
            except Exception as e:
                print(f"Error showing sudo users: {e}")
        else:
            try:
                await query.message.edit_text(
                    text=f"""{format_info("No Sudo Users")}

┌─ 📭 EMPTY
│
  • There are no sudo users.
  • Use /addsudo to add one.
└─""",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
                    ])
                )
            except Exception as e:
                print(f"Error showing empty sudo: {e}")
        return
    
    # Refresh handlers
    if data == "refresh_pending":
        try:
            await query.message.delete()
        except:
            pass
        await pending_command(update, context)
        return
    
    if data == "refresh_users":
        try:
            await query.message.delete()
        except:
            pass
        await users_command(update, context)
        return
    
    if data == "refresh_sudo":
        try:
            await query.message.delete()
        except:
            pass
        await sudo_list_command(update, context)
        return
    
    # Help
    if data == "help":
        if user_manager.is_owner(user_id):
            await show_owner_help(update, context)
        else:
            await show_public_help(update, context)
        return
    
    # About
    if data == "about":
        await show_about(update, context)
        return
    
    # Contact
    if data == "contact":
        await show_contact(update, context)
        return
    
    # Status
    if data == "status":
        await status_command(update, context)
        return
    
    # List
    if data == "list":
        await list_command(update, context)
        return
    
    # Start rotation
    if data == "start_rotation":
        await forcestart_command(update, context)
        return
    
    # Stop rotation
    if data == "stop_rotation":
        await forcestop_command(update, context)
        return


async def show_owner_help(update, context):
    """Show help for owner."""
    query = update.callback_query
    if not query or not query.message:
        return
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_header("📖 Owner Help", "📖")}

┌─ 📚 COMMANDS
│
│  🔐 SESSION
│    /connect <session> - Connect Telegram session
│
│  🎯 TARGET
│    /addchannel <link> - Set channel target
│    /addgroup <link> - Set group target
│
│  📝 USERNAMES
│    /addusername @name1, @name2 - Add usernames
│    /done - Finalize username list
│    /setdelay 20min - Set rotation delay
│    /list - View all usernames
│    /clear - Clear username list
│    /current - Show current username
│
│  ⚙️ ROTATION
│    /forcestart - Start rotation
│    /forcestop - Stop rotation
│    /change_now - Change to next username
│
│  💳 PAYMENTS
│    /pending - View pending payments
│    /approve <id> - Approve payment
│    /reject <id> - Reject payment
│    /users - List all users
│
│  👑 SUDO MANAGEMENT
│    /addsudo <user_id> - Add sudo user
│    /rmsudo <user_id> - Remove sudo user
│    /sudolist - List sudo users
│
│  📊 INFO
│    /status - Show bot status
│
└─

💡 Use buttons for quick access!"""
    
    try:
        await query.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error showing owner help: {e}")


async def show_public_help(update, context):
    """Show help for public users."""
    query = update.callback_query
    if not query or not query.message:
        return
    
    keyboard = [
        [InlineKeyboardButton("💳 Buy Plan", callback_data="buy_plan")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_header("📖 Help", "📖")}

┌─ ℹ️ INFORMATION
│
  • This bot is for authorized users only.
  • Purchase a plan to get access.
  • Contact owner for support.
│
├─ 💳 PLANS
│  • 7 Days - ₹150
│  • 14 Days - ₹260
│  • 30 Days - ₹500
│  • Unlimited - ₹900
│
└─

📌 Click "Buy Plan" to get started!"""
    
    try:
        await query.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error showing public help: {e}")


async def show_about(update, context):
    """Show about information."""
    query = update.callback_query
    if not query or not query.message:
        return
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_header("ℹ️ About Bot", "ℹ️")}

┌─ 🤖 BOT INFO
│
  • Name: Telegram Link Changer Bot
  • Version: 3.0
  • Language: Python
  • Library: python-telegram-bot
  • Framework: Telethon
│
├─ ⚡ FEATURES
  • Automatic username rotation
  • Multiple username support
  • Customizable delay
  • Session management
  • Real-time status
  • Payment system (₹)
  • User management
  • Sudo users
  • Unlimited plans
  • Logger group integration
│
└─

Made with ❤️ using Python"""
    
    try:
        await query.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error showing about: {e}")


async def show_contact(update, context):
    """Show contact information."""
    query = update.callback_query
    if not query or not query.message:
        return
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_header("📞 Contact", "📞")}

┌─ 📬 CONTACT INFO
│
  • For support: Contact @owner
  • For issues: Contact @owner
  • For payments: Contact @owner
│
└─

📌 Owner will respond within 24 hours."""
    
    try:
        await query.message.edit_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error showing contact: {e}")


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
target_data = load_json(config.TARGET_FILE, {"target_id": config.DEFAULT_TARGET_ID, "target_type": "channel", "target_link": ""})
usernames = load_usernames()
delay_seconds = 60
rotation_task: Optional[asyncio.Task] = None
client: Optional[TelegramClient] = None
current_index = 0
entity_cache_loaded = False


# ============================================================
# ACCESS CONTROL
# ============================================================

def is_owner(update):
    if not update.effective_user:
        return False
    return update.effective_user.id == config.OWNER_ID


async def check_access(update, context):
    user_id = update.effective_user.id
    user_manager = context.bot_data.get('user_manager')
    if user_manager.is_owner(user_id):
        return True
    if user_manager.is_sudo(user_id):
        return True
    if user_manager.is_active(user_id):
        return True
    return False


async def owner_only(update):
    if not is_owner(update):
        if update.message:
            await safe_reply_text(update, format_error("❌ You are not authorized.\nThis command is for the bot owner only."))
        return False
    return True


async def require_access(update, context):
    if not await check_access(update, context):
        await safe_reply_text(
            update,
            f"""{format_error("Access Denied")}

┌─ 🔒 RESTRICTED
│
  • You don't have an active subscription.
  • Please purchase a plan to use the bot.
│
├─ 💳 PLANS
│  • 7 Days - ₹150
│  • 14 Days - ₹260
│  • 30 Days - ₹500
│  • Unlimited - ₹900
│
└─

💡 Use /start to buy a plan."""
        )
        return False
    return True


# ============================================================
# /START COMMAND
# ============================================================

async def start_command(update, context):
    """Handle /start command with user management."""
    user = update.effective_user
    user_id = user.id
    user_manager = context.bot_data.get('user_manager')
    
    user_manager.register_user(user_id, user.username, user.first_name)
    
    # Owner gets full access
    if user_manager.is_owner(user_id):
        await animate_owner_start(update, context, user_manager)
        return
    
    # Sudo users get full access
    if user_manager.is_sudo(user_id):
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
            [
                InlineKeyboardButton("🔙 Back", callback_data="back_to_menu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_reply_text(
            update,
            f"""{format_header("👑 Sudo User Access", "👑")}

┌─ 👤 USER INFO
│
  • ID: {user_id}
  • Name: {user.first_name or 'Unknown'}
  • Status: 🟢 Active (Unlimited)
  • Plan: Sudo Unlimited
  • Remaining: ♾️ Unlimited
│
├─ 🚀 GET STARTED
│
  • You have unlimited lifetime access!
  • Use the buttons below to control the bot
  • Check /help for commands
│
└─

💡 You have full access to all features!""",
            reply_markup=reply_markup
        )
        return
    
    # Active users get access
    if user_manager.is_active(user_id):
        await animate_user_start(update, context, user_manager, user_id)
        return
    
    # User is not active - show restricted access
    await animate_initialization(update, context, user_manager)


# ============================================================
# SUDO COMMANDS
# ============================================================

async def add_sudo_command(update, context):
    if not await owner_only(update):
        return
    
    if not context.args:
        await safe_reply_text(
            update,
            f"""{format_error("Usage Error")}

┌─ 📝 USAGE
│
  /addsudo <user_id>
│
├─ 📋 EXAMPLE
│  /addsudo 123456789
│
└─

💡 User will get unlimited lifetime access."""
        )
        return
    
    user_manager = context.bot_data.get('user_manager')
    user_id_str = context.args[0].strip()
    
    try:
        user_id = int(user_id_str)
    except ValueError:
        await safe_reply_text(update, format_error("Invalid user ID. Please provide a numeric ID."))
        return
    
    if user_manager.is_owner(user_id):
        await safe_reply_text(update, format_error("Cannot add owner as sudo."))
        return
    
    if user_manager.is_sudo(user_id):
        await safe_reply_text(update, format_info(f"User {user_id} is already a sudo user."))
        return
    
    user_manager.add_sudo_user(user_id)
    user_data = user_manager.users.get(str(user_id), {})
    username = user_data.get('username', 'Unknown')
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""{format_success("🎉 You've been promoted to Sudo!")}

┌─ 👑 SUDO ACCESS
│
  • You now have unlimited lifetime access!
  • All features are available to you.
  • You don't need to pay for any plan.
│
└─

💡 Use /start to get started!"""
        )
    except:
        pass
    
    await send_to_logger_group(
        context,
        f"""
┌─ 👑 NEW SUDO USER ADDED
│
  • User ID: {user_id}
  • Username: @{username}
  • Added by: @{update.effective_user.username or 'Owner'}
  • Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
└─"""
    )
    
    await safe_reply_text(
        update,
        f"""{format_success("Sudo User Added")}

┌─ 👑 SUDO INFO
│
  • User ID: {user_id}
  • Username: @{username}
  • Status: 🟢 Active (Unlimited)
  • Access: Lifetime
│
└─

✅ User now has unlimited lifetime access!"""
    )


async def remove_sudo_command(update, context):
    if not await owner_only(update):
        return
    
    if not context.args:
        await safe_reply_text(
            update,
            f"""{format_error("Usage Error")}

┌─ 📝 USAGE
│
  /rmsudo <user_id>
│
├─ 📋 EXAMPLE
│  /rmsudo 123456789
│
└─

💡 This will remove unlimited access from the user."""
        )
        return
    
    user_manager = context.bot_data.get('user_manager')
    user_id_str = context.args[0].strip()
    
    try:
        user_id = int(user_id_str)
    except ValueError:
        await safe_reply_text(update, format_error("Invalid user ID. Please provide a numeric ID."))
        return
    
    if user_manager.is_owner(user_id):
        await safe_reply_text(update, format_error("Cannot remove owner from sudo."))
        return
    
    if not user_manager.is_sudo(user_id):
        await safe_reply_text(update, format_info(f"User {user_id} is not a sudo user."))
        return
    
    user_manager.remove_sudo_user(user_id)
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""{format_error("Sudo Access Removed")}

┌─ 🔒 ACCESS REVOKED
│
  • Your unlimited lifetime access has been removed.
  • You now need to purchase a plan.
  • Contact owner for more information.
│
└─

💡 Use /start to view available plans."""
        )
    except:
        pass
    
    await send_to_logger_group(
        context,
        f"""
┌─ 🔒 SUDO USER REMOVED
│
  • User ID: {user_id}
  • Removed by: @{update.effective_user.username or 'Owner'}
  • Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
└─"""
    )
    
    await safe_reply_text(
        update,
        f"""{format_success("Sudo User Removed")}

┌─ 👑 SUDO INFO
│
  • User ID: {user_id}
  • Status: 🔴 Removed
  • Access: Revoked
│
└─

✅ User no longer has unlimited access."""
    )


async def sudo_list_command(update, context):
    if not await owner_only(update):
        return
    
    user_manager = context.bot_data.get('user_manager')
    sudo_users = user_manager.get_sudo_users()
    
    if not sudo_users:
        await safe_reply_text(
            update,
            f"""{format_info("No Sudo Users")}

┌─ 📭 EMPTY
│
  • There are no sudo users.
  • Use /addsudo to add one.
└─"""
        )
        return
    
    text = f"""{format_header("👑 Sudo Users", "👑")}

┌─ 📋 LIST
│"""
    for uid in sudo_users:
        user = user_manager.users.get(uid, {})
        username = user.get('username', 'N/A')
        text += f"""
│  • ID: {uid}
│    User: @{username}
│    Plan: Sudo Unlimited
│    Status: 🟢 Active
│"""
    
    text += """
└─

📌 Sudo users have unlimited lifetime access."""
    
    await safe_reply_text(update, text)


# ============================================================
# PAYMENT MANAGEMENT COMMANDS
# ============================================================

async def pending_command(update, context):
    if not await owner_only(update):
        return
    
    user_manager = context.bot_data.get('user_manager')
    pending = user_manager.get_pending_payments()
    
    if not pending:
        await safe_reply_text(
            update,
            f"""{format_info("No Pending Payments")}

┌─ 📭 EMPTY
│
  • There are no pending payments.
  • All payments have been processed.
└─"""
        )
        return
    
    text = f"""{format_header("💳 Pending Payments", "💳")}

┌─ 📋 LIST
│"""
    for pid, payment in pending.items():
        text += f"""
│  • ID: `{pid}`
│    User: @{payment['username']}
│    Plan: {payment['plan_name']}
│    Amount: ₹{payment['amount']:.0f}
│    Time: {datetime.fromtimestamp(payment['timestamp']).strftime('%Y-%m-%d %H:%M')}
│"""
    
    text += """
└─

📌 Use /approve <id> or /reject <id> to manage payments."""
    
    await safe_reply_text(update, text)


async def approve_command(update, context):
    if not await owner_only(update):
        return
    
    if not context.args:
        await safe_reply_text(
            update,
            f"""{format_error("Usage Error")}

┌─ 📝 USAGE
│
  /approve <payment_id>
│
├─ 📋 EXAMPLE
│  /approve pay_1234567890_123
│
└─

💡 Use /pending to see all payment IDs."""
        )
        return
    
    user_manager = context.bot_data.get('user_manager')
    payment_id = context.args[0].strip()
    
    if payment_id not in user_manager.pending:
        await safe_reply_text(update, format_error("Invalid payment ID."))
        return
    
    payment = user_manager.pending[payment_id]
    if payment.get("status") != "pending":
        await safe_reply_text(update, format_info(f"This payment is already {payment.get('status')}."))
        return
    
    # Approve payment
    user_manager.approve_payment(payment_id)
    user_id = int(payment["user_id"])
    plan_name = payment["plan_name"]
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""{format_success("🎉 Payment Approved!")}

┌─ ✅ ACCESS GRANTED
│
  • Your {plan_name} has been activated!
  • You now have full access to the bot.
  • Use /start to get started.
│
└─

🎊 Thank you for your purchase!"""
        )
    except Exception as e:
        print(f"Failed to notify user: {e}")
    
    # Send to logger group
    await send_to_logger_group(
        context,
        f"""
┌─ ✅ PAYMENT APPROVED ✅
│
  • Payment ID: `{payment_id}`
  • User: @{payment['username']}
  • User ID: {user_id}
  • Plan: {plan_name}
  • Amount: ₹{payment['amount']:.0f}
  • Approved by: @{update.effective_user.username or 'Owner'}
  • Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
└─

✅ Transaction successful! User has been activated."""
    )
    
    await safe_reply_text(
        update,
        f"""{format_success("✅ Payment Approved Successfully!")}

┌─ ✅ APPROVED
│
  • Payment ID: `{payment_id}`
  • User: @{payment['username']}
  • Plan: {plan_name}
  • Amount: ₹{payment['amount']:.0f}
│
└─

✅ User has been activated successfully!
📢 Notification sent to user and logger group."""
    )


async def reject_command(update, context):
    if not await owner_only(update):
        return
    
    if not context.args:
        await safe_reply_text(
            update,
            f"""{format_error("Usage Error")}

┌─ 📝 USAGE
│
  /reject <payment_id>
│
├─ 📋 EXAMPLE
│  /reject pay_1234567890_123
│
└─

💡 Use /pending to see all payment IDs."""
        )
        return
    
    user_manager = context.bot_data.get('user_manager')
    payment_id = context.args[0].strip()
    
    if payment_id not in user_manager.pending:
        await safe_reply_text(update, format_error("Invalid payment ID."))
        return
    
    payment = user_manager.pending[payment_id]
    if payment.get("status") != "pending":
        await safe_reply_text(update, format_info(f"This payment is already {payment.get('status')}."))
        return
    
    # Reject payment
    user_manager.reject_payment(payment_id)
    user_id = int(payment["user_id"])
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""{format_error("❌ Payment Rejected")}

┌─ ❌ REJECTED
│
  • Your payment was rejected.
  • Please contact owner for assistance.
  • You can try again with a new payment.
│
└─

💡 Contact @owner for help."""
        )
    except Exception as e:
        print(f"Failed to notify user: {e}")
    
    # Send to logger group
    await send_to_logger_group(
        context,
        f"""
┌─ ❌ PAYMENT REJECTED ❌
│
  • Payment ID: `{payment_id}`
  • User: @{payment['username']}
  • User ID: {user_id}
  • Plan: {payment['plan_name']}
  • Amount: ₹{payment['amount']:.0f}
  • Rejected by: @{update.effective_user.username or 'Owner'}
  • Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
└─

❌ Payment has been rejected."""
    )
    
    await safe_reply_text(
        update,
        f"""{format_success("✅ Payment Rejected")}

┌─ ❌ REJECTED
│
  • Payment ID: `{payment_id}`
  • User: @{payment['username']}
  • Plan: {payment['plan_name']}
  • Amount: ₹{payment['amount']:.0f}
│
└─

✅ Payment has been rejected.
📢 Notification sent to user and logger group."""
    )


async def users_command(update, context):
    if not await owner_only(update):
        return
    
    user_manager = context.bot_data.get('user_manager')
    users = user_manager.users
    
    if not users:
        await safe_reply_text(
            update,
            f"""{format_info("No Users")}

┌─ 📭 EMPTY
│
  • No users have registered yet.
└─"""
        )
        return
    
    text = f"""{format_header("👥 All Users", "👥")}

┌─ 📋 LIST
│"""
    for uid, user in users.items():
        remaining = user_manager.format_remaining_time(int(uid))
        status = "🟢 Active" if user_manager.is_active(int(uid)) else "🔴 Expired"
        is_sudo = "👑 " if user_manager.is_sudo(int(uid)) else ""
        text += f"""
│  {is_sudo}ID: {uid}
│    User: @{user.get('username', 'N/A')}
│    Plan: {user.get('plan', 'None')}
│    Status: {status}
│    Remaining: {remaining}
│"""
    
    text += """
└─"""
    
    await safe_reply_text(update, text)


# ============================================================
# TELETHON SESSION FUNCTIONS
# ============================================================

async def connect_saved_session():
    global client
    session = session_data.get("session", "")
    if not session:
        return None
    try:
        new_client = TelegramClient(StringSession(session), config.API_ID, config.API_HASH)
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
# CORE COMMAND HANDLERS
# ============================================================

async def connect_command(update, context):
    if not await owner_only(update):
        return
    global client, entity_cache_loaded
    if not context.args:
        await safe_reply_text(update, format_error("Usage:\n/connect <session_string>"))
        return
    session_string = context.args[0].strip()
    try:
        test_client = TelegramClient(StringSession(session_string), config.API_ID, config.API_HASH)
        await test_client.connect()
        if not await test_client.is_user_authorized():
            await test_client.disconnect()
            await safe_reply_text(update, format_error("Invalid session string."))
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
        await safe_reply_text(
            update,
            f"""{format_success("Session Connected")}

┌─ 👤 ACCOUNT INFO
│
  • ID: {me.id}
  • Name: {me.first_name or 'Unknown'}
  • Username: @{me.username if me.username else 'N/A'}
└─"""
        )
    except Exception as e:
        await safe_reply_text(update, format_error(f"Connection failed:\n{e}"))


async def set_target(link, target_type):
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
    except Exception as e:
        raise RuntimeError(f"Could not resolve target: {e}")


async def addchannel_command(update, context):
    if not await require_access(update, context):
        return
    if not context.args:
        await safe_reply_text(update, format_error("Usage:\n/addchannel https://t.me/channelname"))
        return
    link = context.args[0]
    try:
        entity = await set_target(link, "channel")
        await safe_reply_text(
            update,
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
        await safe_reply_text(update, format_error(f"Failed to add channel:\n{e}"))


async def addgroup_command(update, context):
    if not await require_access(update, context):
        return
    if not context.args:
        await safe_reply_text(update, format_error("Usage:\n/addgroup https://t.me/groupname"))
        return
    link = context.args[0]
    try:
        entity = await set_target(link, "group")
        await safe_reply_text(
            update,
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
        await safe_reply_text(update, format_error(f"Failed to add group:\n{e}"))


async def addusername_command(update, context):
    if not await require_access(update, context):
        return
    global usernames
    if not context.args:
        await safe_reply_text(update, format_error("Usage:\n/addusername @name1, @name2"))
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
    await safe_reply_text(
        update,
        f"""{format_success("Usernames Added")}

┌─ 📝 SUMMARY
│
  • Added: {added}
  • Skipped (duplicates): {skipped}
  • Total usernames: {len(usernames)}
└─

💡 Use /list to view all usernames"""
    )


async def done_command(update, context):
    if not await require_access(update, context):
        return
    global usernames
    usernames = load_usernames()
    await safe_reply_text(
        update,
        f"""{format_success("Username List Finalized")}

┌─ 📊 STATS
│
  • Total usernames: {len(usernames)}
  • Status: Ready for rotation
└─

💡 Use /forcestart to begin rotation"""
    )


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


def normalize_username(username):
    username = username.strip()
    if username.startswith("@"):
        username = username[1:]
    return username


async def setdelay_command(update, context):
    if not await require_access(update, context):
        return
    global delay_seconds
    if not context.args:
        await safe_reply_text(update, format_error(
            "Usage:\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 1h 30m 10s"
        ))
        return
    text = " ".join(context.args)
    try:
        delay_seconds = parse_delay(text)
        await safe_reply_text(
            update,
            f"""{format_success("Delay Updated")}

┌─ ⏱️ NEW DELAY
│
  • Value: {format_delay(delay_seconds)}
  • Seconds: {delay_seconds}s
└─"""
        )
    except ValueError as e:
        await safe_reply_text(update, format_error(str(e)))


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
            return (False, "Target is not a broadcast channel.\nTelegram does not allow username operations on ordinary groups.")
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


async def forcestart_command(update, context):
    if not await require_access(update, context):
        return
    global rotation_task
    if not target_data.get("target_id"):
        await safe_reply_text(update, format_error("No target set!\nUse /addgroup or /addchannel"))
        return
    if not usernames:
        await safe_reply_text(update, format_error("No usernames added.\nUse /addusername"))
        return
    tg = await ensure_client()
    if not tg:
        await safe_reply_text(update, format_error("Telegram session not connected.\nUse /connect"))
        return
    if rotation_task and not rotation_task.done():
        await safe_reply_text(update, format_info("Rotation is already running."))
        return
    rotation_task = asyncio.create_task(rotation_loop())
    await safe_reply_text(
        update,
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


async def forcestop_command(update, context):
    if not await require_access(update, context):
        return
    global rotation_task
    if rotation_task and not rotation_task.done():
        rotation_task.cancel()
        try:
            await rotation_task
        except asyncio.CancelledError:
            pass
        rotation_task = None
        await safe_reply_text(
            update,
            f"""{format_header("⏹️ Rotation Stopped", "⏹️")}

┌─ ℹ️ STATUS
│
  • Rotation has been stopped successfully
  • Current index: {current_index + 1}
└─"""
        )
    else:
        await safe_reply_text(update, format_info("Rotation is not running."))


async def change_now_command(update, context):
    if not await require_access(update, context):
        return
    global current_index
    if not target_data.get("target_id"):
        await safe_reply_text(update, format_error("No target set!\nUse /addgroup or /addchannel"))
        return
    if not usernames:
        await safe_reply_text(update, format_error("Username list is empty.\nUse /addusername"))
        return
    await load_entity_cache()
    username = usernames[current_index]
    status_msg = await safe_reply_text(
        update,
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
        if status_msg:
            await safe_edit_message(
                status_msg,
                f"""{format_success("Username Changed Successfully")}

┌─ ✅ UPDATE COMPLETE
│
  • New Username: @{result}
  • Next Index: {current_index + 1}/{len(usernames)}
└─"""
            )
    else:
        if status_msg:
            await safe_edit_message(
                status_msg,
                f"""{format_error("Username Change Failed")}

┌─ ❌ ERROR DETAILS
│
  • Username: @{username}
  • Error: {result}
└─"""
            )


async def status_command(update, context):
    if not await require_access(update, context):
        return
    tg = await ensure_client()
    session_connected = tg is not None
    session_status = "🟢 Connected" if session_connected else "🔴 Not Connected"
    target_set = target_data.get("target_id") is not None
    target_status = "🟢 Set" if target_set else "🔴 Not Set"
    running = rotation_task is not None and not rotation_task.done()
    rotation_status = "🟢 Running" if running else "🔴 Stopped"
    await safe_reply_text(
        update,
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


async def list_command(update, context):
    if not await require_access(update, context):
        return
    if not usernames:
        await safe_reply_text(
            update,
            f"""{format_info("Username List")}

┌─ 📭 EMPTY
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
        text = f"""{format_header(f"Username List {idx}/{len(chunks)}", "📋")}

{chr(10).join(formatted_list)}
"""
        await safe_reply_text(update, text)


async def clear_command(update, context):
    if not await require_access(update, context):
        return
    global usernames, current_index
    usernames = []
    current_index = 0
    save_usernames(usernames)
    await safe_reply_text(
        update,
        f"""{format_success("List Cleared")}

┌─ 🗑️ COMPLETE
│
  • All usernames have been removed.
  • Current index reset to 0.
└─"""
    )


async def current_command(update, context):
    if not await require_access(update, context):
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
    await safe_reply_text(
        update,
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
    """Handle errors globally with flood control."""
    error = context.error
    error_str = str(error)
    
    harmless_errors = [
        "Message is not modified",
        "Query is too old",
        "Query_id_invalid",
        "Message to edit not found",
        "Message can't be edited",
        "There is no text in the message to edit"
    ]
    
    for harmless in harmless_errors:
        if harmless in error_str:
            print(f"⚠️ Ignored harmless error: {error_str[:100]}...")
            return
    
    print(f"❌ Bot error: {error}")
    
    if isinstance(error, RetryAfter):
        wait_time = error.retry_after
        print(f"⏳ Flood control: Need to wait {wait_time} seconds")
        context.bot_data['flood_wait'] = wait_time
        return
    
    try:
        if update and update.effective_message:
            await safe_reply_text(
                update,
                format_error(f"An error occurred. Please try again later.")
            )
    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main():
    print("""
╔═══════════════════════════════════════╗
║     Telegram Link Changer Bot         ║
║          Version 3.0                  ║
║     With Payment & Sudo System        ║
╚═══════════════════════════════════════╝
    """)
    
    if not os.path.exists("qr.jpg"):
        print("⚠️ Warning: qr.jpg not found in root directory!")
        print("   Please add qr.jpg for payment QR code.")
    else:
        print("✅ QR Code found!")
    
    user_manager = UserManager()
    application = Application.builder().token(config.BOT_TOKEN).build()
    application.bot_data['user_manager'] = user_manager
    application.bot_data['flood_wait'] = 0
    
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
    
    # Payment management commands
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(CommandHandler("users", users_command))
    
    # Sudo management commands
    application.add_handler(CommandHandler("addsudo", add_sudo_command))
    application.add_handler(CommandHandler("rmsudo", remove_sudo_command))
    application.add_handler(CommandHandler("sudolist", sudo_list_command))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_payment_callback))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    print("🤖 Bot is running... Press Ctrl+C to stop.")
    print(f"📊 Logger Group ID: {config.LOGGER_GROUP_ID}")
    print(f"👑 Owner ID: {config.OWNER_ID}")
    print(f"💳 QR Code: {'✅ Found' if os.path.exists('qr.jpg') else '❌ Not Found'}")
    print("=" * 50)
    
    application.run_polling()


if __name__ == "__main__":
    main()