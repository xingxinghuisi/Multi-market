import os

import requests
from dotenv import load_dotenv


# 读取 .env 文件
load_dotenv()


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


if not BOT_TOKEN:
    raise ValueError(
        "没有找到 TELEGRAM_BOT_TOKEN，请检查 .env 文件。"
    )


BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def find_chat_id():
    """
    从 Telegram 最近消息中找到 chat_id
    """

    response = requests.get(
        f"{BASE_URL}/getUpdates",
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        print("Telegram API 返回失败：")
        print(data)
        return

    updates = data.get("result", [])

    if not updates:
        print("没有找到任何消息。")
        print("请先打开 Telegram，给机器人发送 /start")
        return

    print("=" * 60)
    print("找到以下 Telegram 聊天：")
    print("=" * 60)

    found = set()

    for update in updates:

        message = update.get("message")

        if not message:
            continue

        chat = message.get("chat", {})

        chat_id = chat.get("id")

        if chat_id in found:
            continue

        found.add(chat_id)

        username = chat.get("username", "")
        first_name = chat.get("first_name", "")
        chat_type = chat.get("type", "")

        print()
        print(f"Chat ID：{chat_id}")
        print(f"用户名：{username}")
        print(f"名称：{first_name}")
        print(f"类型：{chat_type}")

    print()
    print("=" * 60)


def send_test_message():
    """
    给 Telegram 发送测试消息
    """

    message = (
        "📈 Korea Market Radar\n\n"
        "Telegram 通知测试成功。\n\n"
        "下一步将接入韩国股票行情提醒。"
    )

    response = requests.post(
        f"{BASE_URL}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if data.get("ok"):
        print("✅ Telegram 消息发送成功")
    else:
        print("❌ Telegram 消息发送失败")
        print(data)


def main():

    if not CHAT_ID:
        print("目前还没有配置 TELEGRAM_CHAT_ID。")
        print("正在自动查找...")
        print()

        find_chat_id()

    else:
        send_test_message()


if __name__ == "__main__":
    main()