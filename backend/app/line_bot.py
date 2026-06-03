import logging
from typing import Callable, Optional

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

logger = logging.getLogger(__name__)

_handler: Optional[WebhookHandler] = None
_messaging_config: Optional[Configuration] = None
_code_lookup: Optional[Callable[[str], Optional[str]]] = None
_get_base_url: Optional[Callable[[], str]] = None


def init(
    channel_secret: str,
    channel_access_token: str,
    code_lookup: Callable[[str], Optional[str]],
    get_base_url: Callable[[], str],
) -> None:
    global _handler, _messaging_config, _code_lookup, _get_base_url

    _code_lookup = code_lookup
    _get_base_url = get_base_url
    _messaging_config = Configuration(access_token=channel_access_token)
    _messaging_config.timeout = 10.0  # LINE API 呼叫最多等 10 秒

    handler = WebhookHandler(channel_secret)

    @handler.add(MessageEvent, message=TextMessageContent)
    def _on_text(event: MessageEvent) -> None:
        _handle_text(event)

    _handler = handler
    logger.info("✓ LINE BOT 初始化完成")


def _handle_text(event: MessageEvent) -> None:
    code = event.message.text.strip().upper()
    filename = _code_lookup(code) if _code_lookup else None

    with ApiClient(_messaging_config) as api_client:
        api = MessagingApi(api_client)
        if filename:
            base = _get_base_url()
            if base.startswith("http://"):
                base = "https://" + base[7:]
            download_url = f"{base}/download/{code}"
            logger.info(f"✓ LINE 傳送取件連結: {filename} → {event.source.user_id} [{download_url}]")
            messages = [
                TextMessage(
                    text=f"您的照片已準備好，請點擊以下連結查看並下載：\n{download_url}"
                )
            ]
        else:
            messages = [
                TextMessage(
                    text="找不到對應的照片，請確認取件碼是否正確。\n（取件碼共 6 碼，不區分大小寫）"
                )
            ]

        api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=messages,
            )
        )


def handle_webhook(body: bytes, signature: str) -> None:
    if _handler is None:
        raise RuntimeError("LINE BOT 尚未設定，請先在管理後台填入 Channel Secret 與 Access Token。")
    try:
        _handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise ValueError("LINE Webhook 簽名驗證失敗，請確認 Channel Secret 是否正確。")


def is_configured() -> bool:
    return _handler is not None


def reset() -> None:
    global _handler, _messaging_config, _code_lookup, _get_base_url
    _handler = None
    _messaging_config = None
    _code_lookup = None
    _get_base_url = None
    logger.info("✓ LINE BOT 設定已清除")
