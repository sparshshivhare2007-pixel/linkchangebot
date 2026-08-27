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

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config


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

        json.dump(
            data,
            f,
            indent=4
        )


def load_usernames():

    if not os.path.exists(config.USERNAMES_FILE):
        return []

    with open(
        config.USERNAMES_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return [
            line.strip()
            for line in f
            if line.strip()
        ]


def save_usernames(names):

    with open(
        config.USERNAMES_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        for name in names:
            f.write(name + "\n")


# ============================================================
# GLOBAL DATA
# ============================================================

session_data = load_json(
    config.SESSION_FILE,
    {
        "session": ""
    }
)

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


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(update):

    if not update.effective_user:
        return False

    return (
        update.effective_user.id
        == config.OWNER_ID
    )


async def owner_only(update):

    if not is_owner(update):

        if update.message:

            await update.message.reply_text(
                "❌ You are not authorized."
            )

        return False

    return True


# ============================================================
# TELETHON SESSION
# ============================================================

async def connect_saved_session():

    global client

    session = session_data.get(
        "session",
        ""
    )

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

        return client

    except Exception as e:

        print(
            "Session connection failed:",
            e
        )

        return None


async def ensure_client():

    global client

    if client:

        try:

            if client.is_connected():

                if await client.is_user_authorized():

                    return client

        except Exception:
            pass

    return await connect_saved_session()


# ============================================================
# DELAY PARSER
# ============================================================

def parse_delay(text):

    text = text.lower().strip()

    pattern = (
        r"(\d+)\s*"
        r"(hour|hours|hr|hrs|"
        r"min|mins|minute|minutes|"
        r"sec|secs|second|seconds)"
    )

    matches = re.findall(
        pattern,
        text
    )

    if not matches:

        raise ValueError(
            "Invalid delay format.\n\n"
            "Examples:\n"
            "20min\n"
            "1hour\n"
            "30sec\n"
            "1hour 30min\n"
            "1hour 30min 10sec"
        )

    total = 0

    for value, unit in matches:

        value = int(value)

        if unit in [
            "hour",
            "hours",
            "hr",
            "hrs"
        ]:

            total += value * 3600

        elif unit in [
            "min",
            "mins",
            "minute",
            "minutes"
        ]:

            total += value * 60

        elif unit in [
            "sec",
            "secs",
            "second",
            "seconds"
        ]:

            total += value

    if total <= 0:

        raise ValueError(
            "Delay must be greater than zero."
        )

    return total


def format_delay(seconds):

    hours = seconds // 3600

    seconds %= 3600

    minutes = seconds // 60

    seconds %= 60

    result = []

    if hours:
        result.append(f"{hours}h")

    if minutes:
        result.append(f"{minutes}m")

    if seconds:
        result.append(f"{seconds}s")

    return " ".join(result) or "0s"


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

        raise RuntimeError(
            "No Telegram session connected."
        )

    link = link.strip()

    try:

        if "t.me/" in link:

            username = link.split(
                "t.me/",
                1
            )[1]

            username = username.split(
                "?",
                1
            )[0]

            username = username.rstrip("/")

            entity = await tg.get_entity(
                username
            )

        else:

            entity = await tg.get_entity(
                link
            )

        return entity

    except Exception as e:

        raise RuntimeError(
            f"Could not resolve target: {e}"
        )


# ============================================================
# SAVE TARGET
# ============================================================

async def set_target(
    link,
    target_type
):

    entity = await resolve_target(link)

    target_id = entity.id

    target_data.update(
        {
            "target_id": target_id,
            "target_type": target_type,
            "target_link": link
        }
    )

    save_json(
        config.TARGET_FILE,
        target_data
    )

    return entity


# ============================================================
# CHANGE USERNAME
# ============================================================

async def change_username(username):

    tg = await ensure_client()

    if not tg:

        return (
            False,
            "Telegram session not connected."
        )

    target_id = target_data.get(
        "target_id"
    )

    if not target_id:

        return (
            False,
            "No target set."
        )

    username = normalize_username(
        username
    )

    try:

        entity = await tg.get_entity(
            target_id
        )

        # Telegram username update is supported
        # for channel-type entities.
        if not getattr(
            entity,
            "broadcast",
            False
        ):

            return (
                False,
                "Target is not a broadcast channel. "
                "Telegram does not allow this "
                "username operation on an ordinary group."
            )

        await tg(
            UpdateUsernameRequest(
                entity,
                username
            )
        )

        return (
            True,
            username
        )

    except FloodWaitError as e:

        return (
            False,
            f"FloodWait: wait {e.seconds} seconds."
        )

    except UsernameOccupiedError:

        return (
            False,
            f"@{username} is already occupied."
        )

    except UsernameInvalidError:

        return (
            False,
            f"@{username} is invalid."
        )

    except RPCError as e:

        return (
            False,
            f"Telegram error: {e}"
        )

    except Exception as e:

        return (
            False,
            str(e)
        )


# ============================================================
# ROTATION
# ============================================================

async def rotation_loop():

    global current_index

    print("Rotation started.")

    while True:

        if not usernames:

            print(
                "No usernames available."
            )

            break

        if not target_data.get(
            "target_id"
        ):

            print(
                "No target configured."
            )

            break

        username = usernames[
            current_index
        ]

        success, result = (
            await change_username(
                username
            )
        )

        if success:

            print(
                f"Username changed: "
                f"@{result}"
            )

            current_index = (
                current_index + 1
            ) % len(usernames)

            await asyncio.sleep(
                delay_seconds
            )

        else:

            print(
                "Username change failed:",
                result
            )

            # If Telegram explicitly asks us to wait,
            # respect that wait.
            if "FloodWait" in result:

                match = re.search(
                    r"(\d+)\s+seconds",
                    result
                )

                if match:

                    wait = int(
                        match.group(1)
                    )

                    await asyncio.sleep(
                        wait
                    )

                    continue

            await asyncio.sleep(
                max(
                    delay_seconds,
                    60
                )
            )

    print("Rotation stopped.")


# ============================================================
# /START
# ============================================================

async def start_command(
    update,
    context
):

    if not await owner_only(update):
        return

    text = """
🤖 Telegram Link Changer Bot

SESSION:
/connect <session>

TARGET:
/addchannel <link>
/addgroup <link>

/addusername @name1, @name2
/done
/setdelay 20min

CONTROL:
/forcestart
/forcestop
/change_now

INFO:
/status
/list
/clear
/current
"""

    await update.message.reply_text(
        text
    )


# ============================================================
# /CONNECT
# ============================================================

async def connect_command(
    update,
    context
):

    global client

    if not await owner_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/connect <session_string>"
        )

        return

    session_string = (
        context.args[0].strip()
    )

    try:

        test_client = TelegramClient(
            StringSession(
                session_string
            ),
            config.API_ID,
            config.API_HASH
        )

        await test_client.connect()

        if not await test_client.is_user_authorized():

            await test_client.disconnect()

            await update.message.reply_text(
                "❌ Invalid session."
            )

            return

        me = await test_client.get_me()

        session_data[
            "session"
        ] = session_string

        save_json(
            config.SESSION_FILE,
            session_data
        )

        if client:

            try:
                await client.disconnect()
            except Exception:
                pass

        client = test_client

        await update.message.reply_text(
            "✅ Session connected.\n\n"
            f"Account ID: {me.id}\n"
            f"Name: {me.first_name or 'Unknown'}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Connection failed:\n{e}"
        )


# ============================================================
# /ADDCHANNEL
# ============================================================

async def addchannel_command(
    update,
    context
):

    if not await owner_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/addchannel https://t.me/channelname"
        )

        return

    link = context.args[0]

    try:

        entity = await set_target(
            link,
            "channel"
        )

        await update.message.reply_text(
            "✅ Channel added!\n\n"
            f"ID: {entity.id}\n"
            f"Link: {link}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Failed:\n{e}"
        )


# ============================================================
# /ADDGROUP
# ============================================================

async def addgroup_command(
    update,
    context
):

    if not await owner_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/addgroup https://t.me/groupname"
        )

        return

    link = context.args[0]

    try:

        entity = await set_target(
            link,
            "group"
        )

        await update.message.reply_text(
            "✅ Group added!\n\n"
            f"ID: {entity.id}\n"
            f"Link: {link}\n\n"
            "⚠️ Target is saved, but ordinary "
            "groups do not support the same "
            "username-update API as broadcast channels."
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Failed:\n{e}"
        )


# ============================================================
# /ADDUSERNAME
# ============================================================

async def addusername_command(
    update,
    context
):

    global usernames

    if not await owner_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/addusername @name1, @name2"
        )

        return

    raw = " ".join(
        context.args
    )

    names = [
        normalize_username(x)
        for x in raw.split(",")
        if x.strip()
    ]

    added = 0

    for name in names:

        if name and name not in usernames:

            usernames.append(name)

            added += 1

    save_usernames(usernames)

    await update.message.reply_text(
        f"✅ Added: {added}\n"
        f"Total: {len(usernames)}"
    )


# ============================================================
# /DONE
# ============================================================

async def done_command(
    update,
    context
):

    global usernames

    if not await owner_only(update):
        return

    usernames = load_usernames()

    await update.message.reply_text(
        "✅ Username list finalized.\n\n"
        f"Total usernames: {len(usernames)}"
    )


# ============================================================
# /SETDELAY
# ============================================================

async def setdelay_command(
    update,
    context
):

    global delay_seconds

    if not await owner_only(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Examples:\n"
            "/setdelay 20min\n"
            "/setdelay 1hour\n"
            "/setdelay 1hour 30min 10sec"
        )

        return

    text = " ".join(
        context.args
    )

    try:

        delay_seconds = parse_delay(
            text
        )

        await update.message.reply_text(
            "✅ Delay set.\n\n"
            f"Delay: {format_delay(delay_seconds)}"
        )

    except ValueError as e:

        await update.message.reply_text(
            f"❌ {e}"
        )


# ============================================================
# /FORCESTART
# ============================================================

async def forcestart_command(
    update,
    context
):

    global rotation_task

    if not await owner_only(update):
        return

    if not target_data.get(
        "target_id"
    ):

        await update.message.reply_text(
            "❌ No target set!\n"
            "Use /addgroup or /addchannel"
        )

        return

    if not usernames:

        await update.message.reply_text(
            "❌ No usernames added."
        )

        return

    tg = await ensure_client()

    if not tg:

        await update.message.reply_text(
            "❌ Telegram session not connected."
        )

        return

    if (
        rotation_task
        and not rotation_task.done()
    ):

        await update.message.reply_text(
            "⚠️ Rotation already running."
        )

        return

    rotation_task = asyncio.create_task(
        rotation_loop()
    )

    await update.message.reply_text(
        "🚀 Rotation started!\n\n"
        f"Target ID: {target_data['target_id']}\n"
        f"Usernames: {len(usernames)}\n"
        f"Delay: {format_delay(delay_seconds)}"
    )


# ============================================================
# /FORCESTOP
# ============================================================

async def forcestop_command(
    update,
    context
):

    global rotation_task

    if not await owner_only(update):
        return

    if (
        rotation_task
        and not rotation_task.done()
    ):

        rotation_task.cancel()

        try:
            await rotation_task
        except asyncio.CancelledError:
            pass

        rotation_task = None

        await update.message.reply_text(
            "🛑 Rotation stopped."
        )

    else:

        await update.message.reply_text(
            "ℹ️ Rotation is not running."
        )


# ============================================================
# /CHANGE_NOW
# ============================================================

async def change_now_command(
    update,
    context
):

    global current_index

    if not await owner_only(update):
        return

    if not target_data.get(
        "target_id"
    ):

        await update.message.reply_text(
            "❌ No target set!"
        )

        return

    if not usernames:

        await update.message.reply_text(
            "❌ Username list is empty."
        )

        return

    username = usernames[
        current_index
    ]

    await update.message.reply_text(
        f"🔄 Changing to @{username}..."
    )

    success, result = (
        await change_username(
            username
        )
    )

    if success:

        current_index = (
            current_index + 1
        ) % len(usernames)

        await update.message.reply_text(
            f"✅ Username changed to @{result}"
        )

    else:

        await update.message.reply_text(
            f"❌ Failed:\n{result}"
        )


# ============================================================
# /STATUS
# ============================================================

async def status_command(
    update,
    context
):

    if not await owner_only(update):
        return

    tg = await ensure_client()

    session_status = (
        "✅ Connected"
        if tg
        else
        "❌ Not connected"
    )

    running = (
        rotation_task is not None
        and not rotation_task.done()
    )

    target_status = (
        "✅ Set"
        if target_data.get("target_id")
        else
        "❌ Not set"
    )

    await update.message.reply_text(
        "📊 STATUS\n\n"
        f"Session: {session_status}\n"
        f"Target: {target_status}\n"
        f"Target ID: {target_data.get('target_id')}\n"
        f"Type: {target_data.get('target_type')}\n"
        f"Usernames: {len(usernames)}\n"
        f"Delay: {format_delay(delay_seconds)}\n"
        f"Rotation: "
        f"{'🟢 Running' if running else '🔴 Stopped'}"
    )


# ============================================================
# /LIST
# ============================================================

async def list_command(
    update,
    context
):

    if not await owner_only(update):
        return

    if not usernames:

        await update.message.reply_text(
            "📭 List is empty."
        )

        return

    text = "\n".join(
        f"{i + 1}. @{name}"
        for i, name in enumerate(
            usernames
        )
    )

    await update.message.reply_text(
        "📋 USERNAME LIST\n\n"
        + text
    )


# ============================================================
# /CLEAR
# ============================================================

async def clear_command(
    update,
    context
):

    global usernames
    global current_index

    if not await owner_only(update):
        return

    usernames = []

    current_index = 0

    save_usernames(usernames)

    await update.message.reply_text(
        "🗑️ Username list cleared."
    )


# ============================================================
# /CURRENT
# ============================================================

async def current_command(
    update,
    context
):

    if not await owner_only(update):
        return

    current_username = "Unknown"

    tg = await ensure_client()

    if tg and target_data.get(
        "target_id"
    ):

        try:

            entity = await tg.get_entity(
                target_data["target_id"]
            )

            username = getattr(
                entity,
                "username",
                None
            )

            if username:

                current_username = (
                    f"@{username}"
                )

        except Exception:
            pass

    await update.message.reply_text(
        "🎯 CURRENT TARGET\n\n"
        f"ID: {target_data.get('target_id')}\n"
        f"Type: {target_data.get('target_type')}\n"
        f"Link: {target_data.get('target_link') or 'N/A'}\n"
        f"Username: {current_username}"
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    print(
        "Bot error:",
        context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("Starting Telegram Link Changer...")

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "connect",
            connect_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addchannel",
            addchannel_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addgroup",
            addgroup_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addusername",
            addusername_command
        )
    )

    application.add_handler(
        CommandHandler(
            "done",
            done_command
        )
    )

    application.add_handler(
        CommandHandler(
            "setdelay",
            setdelay_command
        )
    )

    application.add_handler(
        CommandHandler(
            "forcestart",
            forcestart_command
        )
    )

    application.add_handler(
        CommandHandler(
            "forcestop",
            forcestop_command
        )
    )

    application.add_handler(
        CommandHandler(
            "change_now",
            change_now_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    application.add_handler(
        CommandHandler(
            "clear",
            clear_command
        )
    )

    application.add_handler(
        CommandHandler(
            "current",
            current_command
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("Bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
