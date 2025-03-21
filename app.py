import os
import logging
import requests
import time
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 引入 v3 Messaging API 所需的模組
from linebot.v3.messaging import ApiClient
from linebot.v3.messaging.configuration import Configuration as MessagingConfiguration
from linebot.v3.messaging.api.messaging_api import MessagingApi
from linebot.v3.messaging.models.show_loading_animation_request import ShowLoadingAnimationRequest

# 建立 Flask 應用程式
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# 取得環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
XAI_API_KEY = os.getenv("XAI_API_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not XAI_API_KEY:
    logging.error("請確認環境變數 LINE_CHANNEL_ACCESS_TOKEN、LINE_CHANNEL_SECRET 與 XAI_API_KEY 均已設定。")
    exit(1)

# 初始化 LINE SDK (v2)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 更新後的系統提示 (角色設定)
SYSTEM_PROMPT = (
    "請扮演 PMP 學習助教，用專業又可愛的語氣，提供專案管理議題的解釋與建議。"
    "當回答 PMP 相關問題時，請參考最新 PMBOK 指南，並以 PMP 考試答題邏輯說明專案管理概念與最佳實踐。"
    "請在情境式解釋之前，先提供所有在回應中涉及的相關名詞定義（若 PMBOK 有定義）；若無，則不需提供。"
    "請使用情境式解釋，例如：如果你是一位專案經理，遇到ＯＯＯ（user提問主題），該如何處理？"
    "提供 PMP 答題思維，確認回應是否符合 PMP 最佳實踐；"
    "並請提供具體 PMBOK 章節參考（例如：根據 PMBOK 第六版第 4 章，專案整合管理...）。"
    "在回應中請務必設置 max_tokens 至 700 或更高，temperature 為 0.7，以確保生成詳細且完整的回應。"
    "若用戶要求「請提供一個非常詳細的回應」，請務必完整說明並分段回覆（每段不超過 700 字），"
    "避免訊息因長度而被截斷。"
)

def send_loading_animation(user_id: str, loading_seconds: int = 10):
    """
    呼叫 LINE Messaging API 顯示等待動畫。
    loading_seconds 必須為 5 的倍數，且最大值為 60 秒。
    """
    config = MessagingConfiguration(
        access_token=LINE_CHANNEL_ACCESS_TOKEN,
        host="https://api.line.me"
    )
    try:
        with ApiClient(config) as api_client:
            messaging_api = MessagingApi(api_client)
            request_body = ShowLoadingAnimationRequest(
                chat_id=user_id,
                loading_seconds=loading_seconds
            )
            messaging_api.show_loading_animation(request_body)
            logging.info("成功發送等待動畫給用戶：%s", user_id)
    except Exception as e:
        logging.error("發送等待動畫錯誤：%s", e)

def call_xai_api(user_message: str) -> str:
    """
    呼叫 x.ai API，根據使用者訊息及系統提示生成回應。
    設置參數：max_tokens 為 700，temperature 為 0.7。
    """
    api_url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {XAI_API_KEY}"
    }
    payload = {
        "model": "grok-2-latest",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 700,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        if response.status_code == 200:
            result = response.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            logging.error("x.ai API 回應錯誤，狀態碼: %s, 回應內容: %s", response.status_code, response.text)
            return "對不起，生成回應時發生錯誤。"
    except Exception as e:
        logging.error("呼叫 x.ai API 時發生例外：%s", e)
        return "對不起，生成回應時發生例外。"

def split_message(text: str, max_length: int = 700) -> list:
    """
    將長訊息依每 max_length 字元分段，回傳訊息區塊串列。
    若分段中出現不成對的 triple backticks (```)，則自動補齊 markdown 格式，避免斷裂問題。
    """
    segments = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    for i in range(len(segments) - 1):
        # 若本段中的 triple backticks 不成對，則補上 closing 標記
        if segments[i].count("```") % 2 != 0:
            segments[i] += "\n```"
            segments[i+1] = "```\n" + segments[i+1]
    return segments

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    logging.info("收到 LINE Webhook 請求：%s", body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("簽章驗證失敗")
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    logging.info("收到用戶訊息：%s", user_message)
    
    # 取得用戶 ID 與 reply token
    user_id = event.source.user_id if hasattr(event.source, "user_id") else event.source.userId
    reply_token = event.reply_token
    loading_duration = 10  # 設定等待動畫持續 10 秒
    
    # 發送等待動畫
    send_loading_animation(user_id, loading_seconds=loading_duration)
    
    start_time = time.time()
    response_text = call_xai_api(user_message)
    elapsed_time = time.time() - start_time
    
    # 補足剩餘等待時間，確保動畫完整播放後再回覆
    if elapsed_time < loading_duration:
        time.sleep(loading_duration - elapsed_time)
    
    messages = [TextSendMessage(text=segment) for segment in split_message(response_text, max_length=700)]
    
    # 若回應超時（超過 50 秒），避免 reply token 過期則使用 push_message
    if elapsed_time > 50:
        try:
            line_bot_api.push_message(user_id, messages)
            logging.info("使用 push_message 發送回應給用戶：%s", user_id)
        except Exception as e:
            logging.error("使用 push_message 回覆訊息失敗：%s", e)
    else:
        try:
            line_bot_api.reply_message(reply_token, messages)
        except Exception as e:
            logging.error("回覆訊息失敗：%s", e)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
