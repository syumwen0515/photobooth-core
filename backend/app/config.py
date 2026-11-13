"""
拍貼機配置模塊
包含所有系統級配置、常數和環境變數
"""

import os
from pathlib import Path

# 應用程式設定
APP_TITLE = "智能拍貼機邊緣端系統"
APP_VERSION = "0.6.0"
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
WATCHER_STABILITY_INTERVAL = 0.5  # 檢查照片檔案大小的間隔（秒）
WATCHER_STABILITY_CHECKS = 3  # 大小連續不變的檢查次數
WATCHER_STABILITY_TIMEOUT = 120.0  # 等待檔案寫入完成的最長時間（秒）

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

# 最高管理者帳號：可改任何人密碼，且不可被刪除
SUPER_ADMIN_USERNAME = "admin"

# 靜態檔案掛載路由
STATIC_INCOMING_ROUTE = "/static/incoming"
STATIC_BG_ROUTE = "/static/bg"

# 底圖與帳號設定
BG_DIR = STORAGE_DIR / "bg"
ACCOUNTS_FILE = STORAGE_DIR / "accounts.json"
SESSION_COOKIE_NAME = "pb_session"
INITIAL_ADMIN_PASSWORD = os.getenv("PB_INITIAL_ADMIN_PASSWORD", "").strip()
INITIAL_ADMIN_PASSWORD_MIN_LENGTH = 12

# ngrok 設定（無法取得實際監聽 port 時的備援值）
NGROK_DEFAULT_PORT = int(os.getenv("PORT", "8000"))

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

# 記錄公開縮圖所用浮水印字型；字型改變時啟動會清除舊縮圖快取
WM_FONT_MARKER_NAME = "wm_font.marker"

# 浮水印字型候選（依序嘗試；需含 CJK 字形才能顯示繁體中文）
WM_FONT_CANDIDATES: tuple = (
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\mingliu.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

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

# 登入速率限制（IP 維度，防止分散式暴力破解）
LOGIN_RATE_LIMIT: int = int(os.getenv("LOGIN_RATE_LIMIT", "10"))   # 每個 IP 每分鐘最多 N 次
LOGIN_RATE_WINDOW: int = 60  # 秒

# 可信任的反向代理 IP（逗號分隔；設定後才信任 X-Forwarded-For；空白＝不信任任何代理）
# 範例：TRUSTED_PROXY_IPS=127.0.0.1,::1
_trusted_proxy_env = os.getenv("TRUSTED_PROXY_IPS", "")
TRUSTED_PROXY_IPS: set = {ip.strip() for ip in _trusted_proxy_env.split(",") if ip.strip()}

# 模板合成 / 客戶自拍設定
TEMPLATES_DIR = STORAGE_DIR / "templates"
TEMPLATES_META_FILE = STORAGE_DIR / "templates.json"
SELFIE_CONFIG_FILE = STORAGE_DIR / "selfie_config.json"
SELFIE_CONFIG_DEFAULTS: dict = {"enabled": False}
API_CUSTOMER_PREFIX = "/api/v1/customer"
SELFIE_PAGE_ROUTE = "/app"
TEMPLATE_ID_PREFIX = "tpl_"
TEMPLATE_MAX_BYTES = 20 * 1024 * 1024     # 模板 PNG 大小上限
TEMPLATE_MAX_PIXELS = 36_000_000          # 模板像素上限（防 decompression bomb）
TEMPLATE_MAX_SLOTS = 12                   # 單一模板槽位數上限
TEMPLATE_ALPHA_THRESHOLD = 10             # alpha <= 此值視為透明
TEMPLATE_MAX_RUNS = 200_000               # 透明連續區段上限（防止紋理型 alpha 拖垮偵測）
TEMPLATE_MIN_SLOT_AREA = 400              # 小於此面積（px）的透明區域視為雜訊
COMPOSITE_MAX_UPLOAD_BYTES = 12 * 1024 * 1024   # 客戶單張自拍大小上限
COMPOSITE_MAX_PHOTO_PIXELS = 50_000_000         # 單張照片像素上限
COMPOSITE_MAX_CONCURRENCY = 2                   # 同時合成的工作數
COMPOSITE_JPEG_QUALITY = 92
SELFIE_RATE_LIMIT = int(os.getenv("SELFIE_RATE_LIMIT", "6"))  # 每個 IP 每分鐘最多合成 N 次
SELFIE_RATE_WINDOW = 60  # 秒

THUMB_MAX_CONCURRENCY = 2       # 同時生成縮圖的工作數（避免 CPU / 記憶體暴衝）
THUMB_SIZE = 480                # 縮圖最長邊（px）
WS_SEND_TIMEOUT = 5.0           # WebSocket 單一連線送出逾時（秒），逾時視為死連線
GALLERY_LIST_TTL = 5.0          # /api/gallery 檔案列表記憶體快取秒數
PERF_SAMPLE_INTERVAL = 5.0      # 效能取樣間隔（秒）
PERF_HISTORY_SIZE = 120         # 保留取樣數（約 10 分鐘）
STATIC_CACHE_CONTROL = "public, max-age=3600"  # 背景圖 / 字型靜態檔快取

for directory in [BG_DIR, THUMB_DIR, FONTS_DIR, TEMPLATES_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
