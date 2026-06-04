"""
拍貼機配置模塊
包含所有系統級配置、常數和環境變數
"""

import os
from pathlib import Path

# 應用程式設定
APP_TITLE = "智能拍貼機邊緣端系統"
APP_VERSION = "0.4.7"
APP_DESCRIPTION = "支援 WebSocket 即時預覽、取件碼系統、LINE BOT 整合的展場級拍貼系統"

# 目錄路徑配置
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
INCOMING_DIR = STORAGE_DIR / "incoming"
TEMPLATE_DIR = BASE_DIR / "app" / "templates"

for directory in [INCOMING_DIR, TEMPLATE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# 檔案類型設定
SUPPORTED_IMAGE_FORMATS = ('.jpg', '.jpeg', '.png')

# WebSocket 設定
WS_PHOTO_ROUTE = "/ws/photos"
WS_MESSAGE_TYPE_NEW_INCOMING = "new_incoming"

# 檔案上傳設定
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# 監聽服務設定
WATCHER_INITIAL_DELAY = 0.5  # 檔案寫入完成後的等待時間（秒）

# CORS 配置
# 若未設定環境變數則不允許任何跨來源，請透過 CORS_ORIGINS 指定允許的來源
_cors_env = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS = ["Content-Type", "Cookie", "X-Requested-With"]

# 日誌設定
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"

# API 設定
API_ADMIN_PREFIX = "/api/admin"

# 靜態檔案掛載路由
STATIC_INCOMING_ROUTE = "/static/incoming"
STATIC_BG_ROUTE = "/static/bg"

# 底圖與帳號設定
BG_DIR = STORAGE_DIR / "bg"
ACCOUNTS_FILE = STORAGE_DIR / "accounts.json"
SESSION_COOKIE_NAME = "pb_session"

# LINE BOT 設定
LINE_CONFIG_FILE = STORAGE_DIR / "line_config.json"
PHOTO_CODES_FILE = STORAGE_DIR / "photo_codes.json"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# ngrok 設定（token 儲存於此，優先序低於環境變數 NGROK_AUTHTOKEN）
NGROK_CONFIG_FILE = STORAGE_DIR / "ngrok_config.json"

THUMB_DIR = STORAGE_DIR / "thumbs"
FONTS_DIR  = STORAGE_DIR / "fonts"
FONTS_META_FILE = STORAGE_DIR / "fonts_meta.json"

# Gallery 設定
GALLERY_CONFIG_FILE = STORAGE_DIR / "gallery_config.json"
GALLERY_CONFIG_DEFAULTS: dict = {
    "enabled": True,
    "watermark_text": "風嶺拍貼機",
}

# 首頁文字設定
INDEX_TEXT_FILE = STORAGE_DIR / "index_text.json"
INDEX_TEXT_DEFAULTS = {
    "main_title": "風嶺",
    "subtitle": "拍貼機",
    "middle_text": "CCIT · PHOTO STUDIO",
    "font": "Noto Sans JP",
}

# 靜態字型路由
STATIC_FONTS_ROUTE = "/static/fonts"

# Google 字型清單（與前端 admin.html 的 optgroup 保持同步）
GOOGLE_FONTS = {
    "Noto Sans JP", "Noto Serif JP", "M PLUS Rounded 1c",
    "Zen Kaku Gothic New", "Shippori Mincho",
}

# 自訂字型支援格式
SUPPORTED_FONT_EXTS: dict[str, str] = {
    ".ttf": "truetype",
    ".otf": "opentype",
    ".woff": "woff",
    ".woff2": "woff2",
}

# 字型檔案上傳大小限制
MAX_FONT_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

# 安全設定
# 設 SECURE_COOKIES=true 可在 HTTPS 環境（如 ngrok）下強制 secure cookie
SECURE_COOKIES: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
# 設 ENABLE_API_DOCS=true 才開放 /api/docs、/api/openapi.json（預設關閉）
ENABLE_API_DOCS: bool = os.getenv("ENABLE_API_DOCS", "false").lower() == "true"

for directory in [BG_DIR, THUMB_DIR, FONTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
