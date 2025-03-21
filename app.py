import os
import logging
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests

# 初始化 Flask 應用
app = Flask(__name__)

# 設置日誌記錄
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 從環境變量獲取配置
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
XAI_API_KEY = os.getenv('XAI_API_KEY')

# 確認環境變量是否正確載入
logger.info(f"LINE_CHANNEL_ACCESS_TOKEN: {LINE_CHANNEL_ACCESS_TOKEN}")
logger.info(f"LINE_CHANNEL_SECRET: {LINE_CHANNEL_SECRET}")
logger.info(f"XAI_API_KEY: {XAI_API_KEY}")

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# x.ai API 配置
XAI_API_URL = 'https://api.x.ai/v1/chat/completions'

# 系統提示詞，定義機器人角色與行為
SYSTEM_PROMPT = """
你是一位 PMP 認證專業教師，專精於專案管理領域。你的任務是根據 PMP 考試的答題邏輯和 PMBOK 指南（最新版）來解釋專案管理概念。請遵循以下準則：

1. **情境式解釋**：優先使用情境式解釋，例如：「如果你是一位專案經理，遇到這種情況，你應該如何處理？」
2. **PMP 答題思維**：
   - 強調遵循 PMBOK 的流程，例如先進行風險評估再決策。
   - 確認選項是否與 PMP 最佳實踐相符。
   - 提醒是否需要與利害關係人協商或遵循變更管理流程。
3. **PMBOK 參考**：提供具體的 PMBOK 章節參考，例如：「根據 PMBOK 第六版第 4 章，專案整合管理……」。
4. **詳細回應**：請提供非常詳細的回應，確保涵蓋所有相關細節。
5. **分段發送**：如果回應超過 700 字，請將內容分段發送。

請始終保持專業、客觀的語氣，並確保你的回應符合 PMI 的最佳實踐。
"""

def split_message(message, max_length=700):
    """
    將長訊息分段，每段不超過 max_length 字，優先在空白字符處分割以保持句子完整性
    """
    parts = []
    while len(message) > max_length:
        # 在 max_length 前尋找最近的空白字符
        split_index = message.rfind(' ', 0, max_length)
        if split_index == -1:
            split_index = max_length  # 若無空白字符，直接按 max_length 分割
        parts.append(message[:split_index].strip())
        message = message[split_index:].strip()
    parts.append(message)
    return parts

@app.route("/callback", methods=['POST'])
def callback():
    """處理 LINE Webhook 請求"""
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    logger.info(f"Request body: {body}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid signature")
        abort(400)  # 返回 400 表示簽名無效
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        return 'Internal Server Error', 500  # 返回 500 表示內部錯誤
    return 'OK', 200  # 明確返回 200 狀態碼表示成功

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理用戶發送的文字訊息"""
    try:
        user_message = event.message.text
        logger.info(f"Received message: {user_message}")

        # 準備 x.ai API 請求
        headers = {
            'Authorization': f'Bearer {XAI_API_KEY}',
            'Content-Type': 'application/json'
        }
        data = {
            'model': 'grok',  # 請確認這是正確的模型名稱
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_message + "\n請提供一個非常詳細的回應。"}
            ],
            'max_tokens': 1000,  # 支持長回應
            'temperature': 0.7   # 平衡創意與準確性
        }

        # 呼叫 x.ai API
        response = requests.post(XAI_API_URL, headers=headers, json=data)
        if response.status_code == 200:
            response_data = response.json()
            ai_response = response_data['choices'][0]['message']['content']
            logger.info(f"AI response: {ai_response}")

            # 檢查回應長度並分段發送
            if len(ai_response) > 700:
                messages = split_message(ai_response)
                for msg in messages:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=msg)
                    )
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=ai_response)
                )
        else:
            logger.error(f"Error calling x.ai API: {response.status_code} - {response.text}")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="抱歉，我無法生成回應。請稍後再試。")
            )
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="抱歉，發生內部錯誤。請稍後再試。")
        )

if __name__ == "__main__":
    # 適配 Render 的端口配置
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
