import os

import requests
from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message):
    """
    发送 Telegram 消息
    """

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN 未配置")
        return False

    if not CHAT_ID:
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
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("ok"):
            return True

        print("❌ Telegram 返回失败：")
        print(data)

        return False

    except Exception as error:
        print(
            f"❌ Telegram 发送异常：{error}"
        )

        return False