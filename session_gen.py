import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

import config


async def main():

    print("================================")
    print(" Telegram String Session Maker")
    print("================================")

    client = TelegramClient(
        StringSession(),
        config.API_ID,
        config.API_HASH
    )

    await client.start()

    session = client.session.save()

    print("\nYOUR SESSION STRING:\n")
    print(session)

    print(
        "\nWARNING:"
        "\nDo NOT share this session string."
        "\nIt gives access to the Telegram account."
    )

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
