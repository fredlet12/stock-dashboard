import requests

# 請填入你的實際 Token 與 Chat ID
TOKEN = "8680874924:AAGkX321FVoKiPgeqd79KWYRltEuwZkHMlM"
CHAT_ID = "7791139302"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "🧪 Telegram 測試訊息：設定成功！"}

try:
    response = requests.post(url, data=payload)
    print("API 回傳結果:", response.json())
except Exception as e:
    print("連線失敗:", e)