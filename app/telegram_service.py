import os
import re

import requests
from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_bot_username():
    """Return only the public bot handle; never expose the bot token."""
    if not BOT_TOKEN:
        return None
    try:
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        response.raise_for_status()
        username = response.json().get("result", {}).get("username", "")
        return username if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else None
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def send_telegram_message(message, chat_id=None):
    """
    发送 Telegram 消息
    """

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN 未配置")
        return False

    target_chat_id = chat_id or CHAT_ID
    if not target_chat_id:
        print("❌ TELEGRAM_CHAT_ID 未配置")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": target_chat_id,
                "text": message,
            },
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("ok"):
            return True

        print("Telegram sendMessage returned an unsuccessful response")

        return False

    except Exception as error:
        # requests exceptions can include the bot token in the request URL.
        print(f"Telegram sendMessage failed: {type(error).__name__}")

        return False
