import asyncio
import functools
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import secrets
import logging
import math
import time
from collections import defaultdict
from urllib.parse import quote
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Cookie, Request
from websockets.exceptions import ConnectionClosedError
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, ImageDraw, ImageFont
from pydantic import BaseModel
from datetime import datetime

from app.watcher import start_watcher
from app.ngrok_manager import start_tunnel, stop_tunnel, get_tunnel_url, is_active as ngrok_is_active
from app import auth, line_bot
from app.config import (
    NGROK_DEFAULT_PORT,
    APP_TITLE, APP_VERSION, APP_DESCRIPTION,
    TEMPLATE_DIR, INCOMING_DIR,
    BG_DIR, ACCOUNTS_FILE,
    CORS_ORIGINS, CORS_ALLOW_CREDENTIALS, CORS_ALLOW_METHODS, CORS_ALLOW_HEADERS,
    MAX_FILE_SIZE_BYTES, SUPPORTED_IMAGE_FORMATS,
    STATIC_INCOMING_ROUTE, STATIC_BG_ROUTE, STATIC_FONTS_ROUTE,
    API_ADMIN_PREFIX, WS_PHOTO_ROUTE, WS_MESSAGE_TYPE_NEW_INCOMING,
    LOG_LEVEL, LOG_FORMAT,
    SESSION_COOKIE_NAME,
    LINE_CONFIG_FILE, PHOTO_CODES_FILE, PUBLIC_BASE_URL,
    NGROK_CONFIG_FILE,
    THUMB_DIR,
    INDEX_TEXT_FILE, INDEX_TEXT_DEFAULTS,
    FONTS_DIR, FONTS_META_FILE,
    GOOGLE_FONTS, SUPPORTED_FONT_EXTS, MAX_FONT_SIZE_BYTES,
    SECURE_COOKIES, ENABLE_API_DOCS,
    GALLERY_CONFIG_FILE, GALLERY_CONFIG_DEFAULTS, WM_FONT_CANDIDATES,
    LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW, TRUSTED_PROXY_IPS,
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# ── IP 速率限制（防止暴力枚舉取件碼）───────────────────────────
_code_request_log: Dict[str, List[float]] = defaultdict(list)
_CODE_RATE_LIMIT = 30   # 每個 IP 每分鐘最多 30 次
_CODE_RATE_WINDOW = 60  # 秒

# ── IP 速率限制（防止分散式暴力破解登入）────────────────────────
_login_request_log: Dict[str, List[float]] = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    # 只有當 TCP 連線來自已設定的可信代理 IP 時，才信任 X-Forwarded-For
    # 未設定 TRUSTED_PROXY_IPS 時（預設），直接使用 TCP 遠端位址，防止 header 偽造
    client_host = request.client.host if request.client else ""
    if TRUSTED_PROXY_IPS and client_host in TRUSTED_PROXY_IPS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return client_host or "unknown"


def _check_login_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - LOGIN_RATE_WINDOW
    _login_request_log[ip] = [t for t in _login_request_log[ip] if t > cutoff]
    if len(_login_request_log[ip]) >= LOGIN_RATE_LIMIT:
        return False
    _login_request_log[ip].append(now)
    return True


def _check_code_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - _CODE_RATE_WINDOW
    log = _code_request_log[ip]
    # 清理舊紀錄
    _code_request_log[ip] = [t for t in log if t > cutoff]
    if len(_code_request_log[ip]) >= _CODE_RATE_LIMIT:
        return False
    _code_request_log[ip].append(now)
    return True


# ── 取件碼字元表（移除易混淆字元 0/O/1/I）───────────────────
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(length))


# ── 取件碼儲存（filename → code）────────────────────────────
_photo_codes: Dict[str, str] = {}   # filename → code
_code_to_file: Dict[str, str] = {}  # code → filename（反向查表）


def _load_photo_codes() -> None:
    global _photo_codes, _code_to_file
    if PHOTO_CODES_FILE.exists():
        try:
            _photo_codes = json.loads(PHOTO_CODES_FILE.read_text(encoding="utf-8"))
            _code_to_file = {v: k for k, v in _photo_codes.items()}
        except Exception as e:
            logger.warning(f"⚠️ 取件碼檔案讀取失敗: {e}")


def _save_photo_codes() -> None:
    try:
        PHOTO_CODES_FILE.write_text(json.dumps(_photo_codes, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"❌ 取件碼儲存失敗: {e}")


def _assign_code(filename: str) -> str:
    if filename in _photo_codes:
        return _photo_codes[filename]
    for _ in range(20):
        code = _generate_code()
        if code not in _code_to_file:
            _photo_codes[filename] = code
            _code_to_file[code] = filename
            _save_photo_codes()
            return code
    code = _generate_code(8)
    _photo_codes[filename] = code
    _code_to_file[code] = filename
    _save_photo_codes()
    return code


def _lookup_code(code: str) -> Optional[str]:
    return _code_to_file.get(code.strip().upper())


def _assign_codes_for_existing_incoming() -> None:
    """啟動時為 incoming 目錄中尚未有取件碼的照片補碼。"""
    try:
        assigned = 0
        for p in INCOMING_DIR.iterdir():
            if p.suffix.lower() in SUPPORTED_IMAGE_FORMATS and p.name not in _photo_codes:
                _assign_code(p.name)
                assigned += 1
        if assigned:
            logger.info(f"✓ 已為 {assigned} 張現有照片補發取件碼")
    except Exception as e:
        logger.warning(f"⚠️ 補發取件碼失敗: {e}")


# ── ngrok Token 儲存（優先序低於環境變數 NGROK_AUTHTOKEN）────
def _load_ngrok_token() -> Optional[str]:
    env_token = os.getenv("NGROK_AUTHTOKEN") or os.getenv("NGROK_AUTH_TOKEN")
    if env_token:
        return env_token
    if NGROK_CONFIG_FILE.exists():
        try:
            cfg = json.loads(NGROK_CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("auth_token") or None
        except Exception:
            pass
    return None


def _save_ngrok_token(auth_token: str) -> None:
    NGROK_CONFIG_FILE.write_text(
        json.dumps({"auth_token": auth_token}, ensure_ascii=False),
        encoding="utf-8",
    )


# ── LINE BOT 設定儲存 ────────────────────────────────────────
def _load_line_config() -> Optional[Dict[str, str]]:
    # 環境變數優先序高於 JSON 檔案（適合生產部署，避免 token 明文落盤）
    env_secret = os.getenv("LINE_CHANNEL_SECRET", "").strip()
    env_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    if env_secret and env_token:
        return {"channel_secret": env_secret, "channel_access_token": env_token}
    if LINE_CONFIG_FILE.exists():
        try:
            cfg = json.loads(LINE_CONFIG_FILE.read_text(encoding="utf-8"))
            if cfg.get("channel_secret") and cfg.get("channel_access_token"):
                return cfg
        except Exception:
            pass
    return None


def _save_line_config(channel_secret: str, channel_access_token: str) -> None:
    LINE_CONFIG_FILE.write_text(
        json.dumps({"channel_secret": channel_secret, "channel_access_token": channel_access_token},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def _load_fonts_meta() -> List[Dict]:
    if FONTS_META_FILE.exists():
        try:
            return json.loads(FONTS_META_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_fonts_meta(fonts: List[Dict]) -> None:
    FONTS_META_FILE.write_text(json.dumps(fonts, ensure_ascii=False, indent=2), encoding="utf-8")


_gallery_config_cache: Optional[Dict[str, Any]] = None


def _load_gallery_config() -> Dict[str, Any]:
    global _gallery_config_cache
    if _gallery_config_cache is not None:
        return dict(_gallery_config_cache)
    if GALLERY_CONFIG_FILE.exists():
        try:
            saved = json.loads(GALLERY_CONFIG_FILE.read_text(encoding="utf-8"))
            _gallery_config_cache = {**GALLERY_CONFIG_DEFAULTS, **{k: v for k, v in saved.items() if k in GALLERY_CONFIG_DEFAULTS}}
            return dict(_gallery_config_cache)
        except Exception:
            pass
    _gallery_config_cache = dict(GALLERY_CONFIG_DEFAULTS)
    return dict(_gallery_config_cache)


def _save_gallery_config(data: Dict[str, Any]) -> None:
    global _gallery_config_cache
    GALLERY_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _gallery_config_cache = dict(data)


def _invalidate_public_thumbs() -> None:
    """刪除所有公開縮圖快取（浮水印文字變更後呼叫）。"""
    try:
        for p in THUMB_DIR.glob("pub_*.webp"):
            try:
                p.unlink()
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"⚠️ 清除公開縮圖快取失敗: {e}")


def _load_index_text() -> Dict[str, Any]:
    if INDEX_TEXT_FILE.exists():
        try:
            saved = json.loads(INDEX_TEXT_FILE.read_text(encoding="utf-8"))
            result: Dict[str, Any] = {**INDEX_TEXT_DEFAULTS, **{k: v for k, v in saved.items() if k in INDEX_TEXT_DEFAULTS}}
        except Exception:
            result = dict(INDEX_TEXT_DEFAULTS)
    else:
        result = dict(INDEX_TEXT_DEFAULTS)

    font = result.get("font", INDEX_TEXT_DEFAULTS["font"])
    if font in GOOGLE_FONTS:
        result["font_source"] = "google"
    else:
        font_info = next((f for f in _load_fonts_meta() if f["family"] == font), None)
        if font_info:
            result["font_source"] = "custom"
            result["font_file"]   = f"{STATIC_FONTS_ROUTE}/{font_info['filename']}"
            result["font_format"] = font_info["format"]
        else:
            result["font"] = INDEX_TEXT_DEFAULTS["font"]
            result["font_source"] = "google"

    return result


def _save_index_text(data: Dict[str, str]) -> None:
    INDEX_TEXT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_public_base_url() -> str:
    if ngrok_is_active():
        url = get_tunnel_url()
        if url:
            return url.rstrip("/")
    url = PUBLIC_BASE_URL.rstrip("/") if PUBLIC_BASE_URL else ""
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def _init_line_bot(cfg: Dict[str, str]) -> None:
    try:
        line_bot.init(
            channel_secret=cfg["channel_secret"],
            channel_access_token=cfg["channel_access_token"],
            code_lookup=_lookup_code,
            get_base_url=_get_public_base_url,
        )
    except Exception as e:
        logger.warning(f"⚠️ LINE BOT 初始化失敗: {e}")


# ==================== WebSocket 連接管理 ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"🔗 新 WebSocket 連接 (總連接數: {len(self.active_connections)})")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info(f"🔌 WebSocket 斷線 (剩餘: {len(self.active_connections)})")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        disconnected: set[WebSocket] = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"⚠️ 廣播失敗: {e}")
                disconnected.add(connection)
        self.active_connections -= disconnected


manager = ConnectionManager()


# ==================== 應用程式生命週期 ====================

async def _session_cleanup_task() -> None:
    """每小時清理一次過期 session 與速率限制紀錄，防止記憶體無限成長。"""
    while True:
        await asyncio.sleep(3600)
        removed = auth.cleanup_expired_sessions()
        if removed:
            logger.info(f"✓ 已清理 {removed} 個過期 session")
        now = time.monotonic()
        cutoff = now - _CODE_RATE_WINDOW
        stale_ips = [ip for ip, log in _code_request_log.items() if not any(t > cutoff for t in log)]
        for ip in stale_ips:
            del _code_request_log[ip]
        if stale_ips:
            logger.debug(f"✓ 已清理 {len(stale_ips)} 個過期 IP 速率限制記錄（取件碼）")
        login_cutoff = now - LOGIN_RATE_WINDOW
        stale_login_ips = [ip for ip, log in _login_request_log.items() if not any(t > login_cutoff for t in log)]
        for ip in stale_login_ips:
            del _login_request_log[ip]
        if stale_login_ips:
            logger.debug(f"✓ 已清理 {len(stale_login_ips)} 個過期 IP 速率限制記錄（登入）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.init(ACCOUNTS_FILE)
    _load_photo_codes()
    _assign_codes_for_existing_incoming()
    line_cfg = _load_line_config()
    if line_cfg:
        _init_line_bot(line_cfg)
    loop = asyncio.get_running_loop()
    app.state.observer = start_watcher(INCOMING_DIR, manager, loop, code_assigner=_assign_code)
    app.state.cleanup_task = loop.create_task(_session_cleanup_task())
    logger.info("✓ 拍貼機服務啟動完成")
    yield
    app.state.cleanup_task.cancel()
    if hasattr(app.state, "observer") and app.state.observer:
        app.state.observer.stop()
        app.state.observer.join()
        logger.info("🛑 資料夾監聽服務已安全關閉")
    if ngrok_is_active():
        stop_tunnel()


# ==================== FastAPI 初始化 ====================

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    docs_url="/api/docs" if ENABLE_API_DOCS else None,
    redoc_url="/api/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/api/openapi.json" if ENABLE_API_DOCS else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
)


@app.middleware("http")
async def protect_static_incoming(request: Request, call_next):
    """封鎖未授權的原始照片直接存取（繞過取件碼機制的後門）。
    公開縮圖（含浮水印）走 /api/gallery/thumb/；原始檔必須通過 /api/photo/{code} 或管理員 session。
    此 middleware 後定義，執行順序優先於 add_security_headers。
    """
    if request.url.path.startswith(STATIC_INCOMING_ROUTE + "/"):
        pb_session = request.cookies.get(SESSION_COOKIE_NAME)
        if not auth.validate_session(pb_session):
            return Response(
                status_code=401,
                content="需要管理員登入才能直接存取原始照片。請透過取件碼頁面 /download/{code} 取件。",
                media_type="text/plain; charset=utf-8",
                headers={"X-Content-Type-Options": "nosniff"},
            )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # admin.html uses Tailwind Play CDN which injects <style> at runtime without nonces;
    # restrict unsafe-inline to the authenticated /admin path only.
    if request.url.path == "/admin":
        style_src = "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    else:
        style_src = f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
        f"{style_src}"
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "base-uri 'self'"
    )
    if SECURE_COOKIES:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.mount(STATIC_INCOMING_ROUTE, StaticFiles(directory=str(INCOMING_DIR)), name="incoming_photos")
app.mount(STATIC_BG_ROUTE, StaticFiles(directory=str(BG_DIR)), name="bg")
app.mount(STATIC_FONTS_ROUTE, StaticFiles(directory=str(FONTS_DIR)), name="fonts")


# ==================== Pydantic 模型 ====================

class NgrokStartRequest(BaseModel):
    port: Optional[int] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class AddAccountRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    new_password: str

class LineConfigRequest(BaseModel):
    channel_secret: str
    channel_access_token: str

class IndexTextRequest(BaseModel):
    main_title: str
    subtitle: str
    middle_text: str
    font: str


class GallerySettingsRequest(BaseModel):
    enabled: bool
    watermark_text: str


# ==================== 輔助函數 ====================

def validate_filename_safety(filename: str) -> bool:
    if not filename or filename in ('.', '..'):
        return False
    return not any(p in filename for p in ('/', '\\', '..', '~', '\x00'))


def _require_auth(pb_session: Optional[str]) -> str:
    username = auth.validate_session(pb_session)
    if not username:
        raise HTTPException(status_code=401, detail="請先登入")
    return username


_html_cache: Dict[str, Optional[str]] = {}


def _apply_nonce(html: str, nonce: str) -> str:
    return html.replace("__CSP_NONCE__", nonce)


def _get_html(name: str) -> str:
    reload_mode = os.getenv("RELOAD_ADMIN_HTML", "false").lower() == "true"
    if _html_cache.get(name) is None or reload_mode:
        path = Path(TEMPLATE_DIR) / name
        if not path.exists():
            raise FileNotFoundError(f"找不到網頁檔案: {path}")
        _html_cache[name] = path.read_text(encoding="utf-8")
    return _html_cache[name]


# ==================== 頁面路由 ====================

@app.get("/", response_class=HTMLResponse, tags=["Pages"])
async def get_index(request: Request) -> str:
    try:
        return _apply_nonce(_get_html("index.html"), request.state.csp_nonce)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")



@app.get("/login", response_class=HTMLResponse, tags=["Pages"])
async def get_login_page(request: Request) -> str:
    try:
        return _apply_nonce(_get_html("login.html"), request.state.csp_nonce)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")


@app.get("/admin", response_class=HTMLResponse, tags=["Pages"])
async def get_admin_page(request: Request, pb_session: Optional[str] = Cookie(default=None)) -> Response:
    if not auth.validate_session(pb_session):
        return RedirectResponse(url="/login", status_code=302)
    try:
        return HTMLResponse(_apply_nonce(_get_html("admin.html"), request.state.csp_nonce))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")


# ==================== WebSocket 端點 ====================

@app.websocket(WS_PHOTO_ROUTE)
async def websocket_endpoint(websocket: WebSocket) -> None:
    pb_session = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not auth.validate_session(pb_session):
        await websocket.close(code=1008)  # Policy Violation
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ConnectionClosedError):
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ WebSocket 處理失敗: {e}")
        manager.disconnect(websocket)


# ==================== 系統端點 ====================

@app.get("/api", tags=["System"])
async def read_root() -> Dict[str, Any]:
    return {
        "status": "online",
        "message": "拍貼機後端核心正在運作中",
        "version": APP_VERSION,
        "timestamp": datetime.now().isoformat(),
    }


# ==================== 公開 API ====================


@app.get("/api/ngrok-url", tags=["Public"], summary="取得 ngrok 公開網址（公開）")
async def get_ngrok_url_public() -> Dict[str, Any]:
    return {"public_url": get_tunnel_url() if ngrok_is_active() else None}


# ==================== Auth API ====================

@app.post("/api/auth/login", tags=["Auth"], summary="管理員登入")
async def login(body: LoginRequest, http_request: Request, response: Response) -> Dict[str, str]:
    client_ip = _get_client_ip(http_request)
    if not _check_login_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="登入嘗試次數過多，請稍後再試")
    if auth.is_account_locked(body.username):
        raise HTTPException(status_code=429, detail="登入嘗試次數過多，請稍後再試")
    if not auth.verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    token = auth.create_session(body.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return {"message": "登入成功", "username": body.username}


@app.post("/api/auth/logout", tags=["Auth"], summary="管理員登出")
async def logout(response: Response, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    if pb_session:
        auth.destroy_session(pb_session)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"message": "已登出"}


@app.get("/api/auth/me", tags=["Auth"], summary="取得目前登入帳號")
async def get_me(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    username = auth.validate_session(pb_session)
    if not username:
        raise HTTPException(status_code=401, detail="尚未登入")
    return {"username": username}


# ==================== 帳號管理 API ====================

@app.get(f"{API_ADMIN_PREFIX}/accounts", tags=["Accounts"])
async def list_accounts(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    return {"accounts": auth.get_accounts()}


@app.post(f"{API_ADMIN_PREFIX}/accounts", tags=["Accounts"])
async def add_account(request: AddAccountRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    ok, msg = auth.add_account(request.username, request.password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.put(f"{API_ADMIN_PREFIX}/accounts/{{username}}/password", tags=["Accounts"])
async def change_password(username: str, request: ChangePasswordRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    ok, msg = auth.change_password(username, request.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.delete(f"{API_ADMIN_PREFIX}/accounts/{{username}}", tags=["Accounts"])
async def delete_account(username: str, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    ok, msg = auth.delete_account(username)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


# ==================== 底圖管理 API ====================

def _process_bg_image(content: bytes) -> tuple[int, int]:
    img = Image.open(io.BytesIO(content)).convert("RGB")
    if img.width > 1920:
        ratio = 1920 / img.width
        img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)
    img.save(str(BG_DIR / "bg.jpg"), "JPEG", quality=82, optimize=True, progressive=True)
    img.save(str(BG_DIR / "bg.webp"), "WEBP", quality=78, method=6)
    return img.width, img.height


@app.post(f"{API_ADMIN_PREFIX}/upload-bg", tags=["Background"])
async def upload_bg(file: UploadFile = File(...), pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if not file.filename:
        raise HTTPException(status_code=400, detail="請選擇檔案")
    ext = Path(file.filename).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise HTTPException(status_code=400, detail="僅支援 JPG / PNG / WebP 格式")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="檔案超過 50MB 限制")
    try:
        loop = asyncio.get_running_loop()
        w, h = await loop.run_in_executor(None, _process_bg_image, content)
        logger.info(f"✓ 首頁底圖已更新 ({w}×{h})")
        return {"message": "底圖上傳成功", "url": f"{STATIC_BG_ROUTE}/bg.jpg"}
    except Exception as e:
        logger.error(f"底圖處理失敗: {e}")
        raise HTTPException(status_code=500, detail="圖片處理失敗")


@app.delete(f"{API_ADMIN_PREFIX}/bg", tags=["Background"])
async def delete_bg(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    bg_path = BG_DIR / "bg.jpg"
    try:
        bg_path.unlink()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="尚未上傳底圖")
    (BG_DIR / "bg.webp").unlink(missing_ok=True)
    return {"message": "底圖已刪除"}


@app.get(f"{API_ADMIN_PREFIX}/bg-status", tags=["Background"])
async def get_bg_status(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    bg_path = BG_DIR / "bg.jpg"
    return {"exists": bg_path.exists(), "url": f"{STATIC_BG_ROUTE}/bg.jpg" if bg_path.exists() else None}


# ==================== 首頁文字 API ====================

@app.get("/api/index-text", tags=["IndexText"])
async def get_index_text() -> Dict[str, str]:
    return _load_index_text()


@app.post(f"{API_ADMIN_PREFIX}/index-text", tags=["IndexText"])
async def save_index_text(request: IndexTextRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if request.font not in GOOGLE_FONTS:
        custom_families = {f["family"] for f in _load_fonts_meta()}
        if request.font not in custom_families:
            raise HTTPException(status_code=400, detail="字體不存在")
    data = {
        "main_title": request.main_title[:30],
        "subtitle": request.subtitle[:30],
        "middle_text": request.middle_text[:60],
        "font": request.font,
    }
    _save_index_text(data)
    return {"message": "首頁文字設定已儲存"}


# ==================== 公開照片集 API ====================

@app.get("/api/gallery", tags=["Public"], summary="公開照片集列表")
async def get_gallery_list() -> Dict[str, Any]:
    gallery_cfg = _load_gallery_config()
    enabled = gallery_cfg.get("enabled", True)
    wm_text = gallery_cfg.get("watermark_text") or GALLERY_CONFIG_DEFAULTS["watermark_text"]
    wm_version = hashlib.md5(wm_text.encode()).hexdigest()[:8]
    if not enabled:
        return {"enabled": False, "photos": [], "count": 0, "wm_version": wm_version}
    try:
        paths = []
        for p in INCOMING_DIR.iterdir():
            if p.suffix.lower() in SUPPORTED_IMAGE_FORMATS:
                try:
                    paths.append((p, p.stat().st_mtime))
                except (FileNotFoundError, OSError):
                    pass
        paths.sort(key=lambda x: x[1], reverse=True)
        return {"enabled": True, "photos": [p.name for p, _ in paths], "count": len(paths), "wm_version": wm_version}
    except Exception:
        return {"enabled": True, "photos": [], "count": 0, "wm_version": wm_version}


@app.get("/api/gallery/thumb/{filename}", tags=["Public"], summary="公開照片縮圖（含浮水印）")
async def get_gallery_thumb_public(filename: str) -> FileResponse:
    if not _load_gallery_config().get("enabled", True):
        raise HTTPException(status_code=404, detail="公開照片集未啟用")
    if not validate_filename_safety(filename):
        raise HTTPException(status_code=400, detail="無效的檔案名稱")
    src_path = INCOMING_DIR / filename
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="找不到照片")
    try:
        src_path.resolve().relative_to(INCOMING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="路徑驗證失敗")
    # 以 hash 命名快取，避免中文/特殊字元檔名在不同 OS 的相容問題
    thumb_path = _pub_thumb_path(filename)
    if not thumb_path.exists():
        try:
            gallery_cfg = _load_gallery_config()
            wm_text = gallery_cfg.get("watermark_text") or GALLERY_CONFIG_DEFAULTS["watermark_text"]
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _generate_public_thumbnail, src_path, thumb_path, wm_text)
        except Exception as e:
            logger.error(f"公開縮圖生成失敗 {filename}: {e}")
            raise HTTPException(status_code=500, detail="縮圖生成失敗")
    return FileResponse(
        str(thumb_path),
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ==================== Gallery 設定 API ====================

@app.get(f"{API_ADMIN_PREFIX}/gallery-settings", tags=["Gallery"])
async def get_gallery_settings(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    return _load_gallery_config()


@app.post(f"{API_ADMIN_PREFIX}/gallery-settings", tags=["Gallery"])
async def update_gallery_settings(
    request: GallerySettingsRequest,
    pb_session: Optional[str] = Cookie(default=None),
) -> Dict[str, str]:
    _require_auth(pb_session)
    wm_text = request.watermark_text.strip()[:40] or GALLERY_CONFIG_DEFAULTS["watermark_text"]
    current = _load_gallery_config()
    watermark_changed = current.get("watermark_text") != wm_text
    data = {"enabled": request.enabled, "watermark_text": wm_text}
    _save_gallery_config(data)
    if watermark_changed:
        _invalidate_public_thumbs()
    return {"message": "Gallery 設定已儲存"}


# ==================== 自訂字型 API ====================

@app.get("/api/fonts", tags=["Fonts"])
async def list_fonts_public() -> Dict[str, Any]:
    return {"fonts": _load_fonts_meta()}


@app.post(f"{API_ADMIN_PREFIX}/fonts", tags=["Fonts"])
async def upload_font(files: List[UploadFile] = File(...), pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    if not files:
        raise HTTPException(status_code=400, detail="請選擇字型檔案")

    uploaded: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    fonts = _load_fonts_meta()

    for file in files:
        if not file.filename:
            errors.append({"filename": "", "error": "空白檔名"})
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_FONT_EXTS:
            errors.append({"filename": file.filename, "error": "僅支援 TTF / OTF / WOFF / WOFF2 格式"})
            continue
        content = await file.read()
        if len(content) > MAX_FONT_SIZE_BYTES:
            errors.append({"filename": file.filename, "error": "字型檔案超過 20MB 限制"})
            continue
        raw_stem = Path(file.filename).stem
        safe_family = re.sub(r"[^\w\s\-]", "", raw_stem).strip() or "CustomFont"
        safe_filename = safe_family + ext
        (FONTS_DIR / safe_filename).write_bytes(content)
        fonts = [f for f in fonts if f["filename"] != safe_filename]
        fonts.append({"family": safe_family, "filename": safe_filename, "format": SUPPORTED_FONT_EXTS[ext]})
        uploaded.append({"family": safe_family, "filename": safe_filename})
        logger.info(f"✓ 自訂字型已上傳: {safe_filename}")

    if uploaded:
        _save_fonts_meta(fonts)

    return {"message": f"上傳完成 ({len(uploaded)}/{len(files)})", "uploaded": uploaded, "errors": errors}


@app.delete(f"{API_ADMIN_PREFIX}/fonts/{{filename}}", tags=["Fonts"])
async def delete_font(filename: str, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if not validate_filename_safety(filename):
        raise HTTPException(status_code=400, detail="無效的檔案名稱")
    font_path = FONTS_DIR / filename
    try:
        font_path.resolve().relative_to(FONTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="路徑驗證失敗")
    try:
        font_path.unlink()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="找不到字型")
    fonts = [f for f in _load_fonts_meta() if f["filename"] != filename]
    _save_fonts_meta(fonts)
    return {"message": f"已刪除字型 {filename}"}


# ==================== 拍攝照片管理 API ====================

@app.get(f"{API_ADMIN_PREFIX}/incoming", tags=["Incoming"])
async def list_incoming(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    try:
        paths = []
        for p in INCOMING_DIR.iterdir():
            if p.suffix.lower() in SUPPORTED_IMAGE_FORMATS:
                try:
                    paths.append((p, p.stat().st_mtime))
                except (FileNotFoundError, OSError):
                    pass
        paths.sort(key=lambda x: x[1], reverse=True)
        photos = [{"filename": p.name, "code": _photo_codes.get(p.name)} for p, _ in paths]
        return {"photos": photos, "count": len(photos)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法取得照片列表: {e}")


def _generate_thumbnail(src_path: Path, thumb_path: Path, fmt: str = "WEBP") -> None:
    img = ImageOps.exif_transpose(
        Image.open(io.BytesIO(src_path.read_bytes()))
    ).convert("RGB")
    img.thumbnail((480, 480), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=82, optimize=True)
    else:
        img.save(buf, "WEBP", quality=72, method=4)
    thumb_path.write_bytes(buf.getvalue())


@functools.lru_cache(maxsize=1)
def _wm_font_paths() -> tuple:
    paths = [p for p in WM_FONT_CANDIDATES[:-3] if os.path.exists(p)]
    if sys.platform != "win32":
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=zh-tw"],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            if out and os.path.exists(out) and out not in paths:
                paths.append(out)
        except Exception:
            pass
    paths += [p for p in WM_FONT_CANDIDATES[-3:] if os.path.exists(p)]
    return tuple(paths)


@functools.lru_cache(maxsize=32)
def _wm_font(size: int) -> ImageFont.ImageFont:
    for path in _wm_font_paths():
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    logging.getLogger(__name__).warning("找不到可用的 CJK 字型，浮水印中文可能顯示為方塊；請安裝 fonts-noto-cjk")
    return ImageFont.load_default(size=size)


def _pub_thumb_path(filename: str) -> Path:
    """以 MD5 hash 產生公開縮圖快取路徑，避免中文/特殊字元問題。"""
    key = hashlib.md5(filename.encode("utf-8")).hexdigest()
    return THUMB_DIR / f"pub_{key}.webp"


def _generate_public_thumbnail(src_path: Path, thumb_path: Path, watermark_text: str = "") -> None:
    """縮圖 + 浮水印，供公開照片集使用（與管理端縮圖分開快取）。"""
    img = ImageOps.exif_transpose(
        Image.open(io.BytesIO(src_path.read_bytes()))
    ).convert("RGBA")
    img.thumbnail((480, 480), Image.LANCZOS)
    w, h = img.size

    font_size = max(13, w // 16)
    font = _wm_font(font_size)
    text = watermark_text or GALLERY_CONFIG_DEFAULTS["watermark_text"]

    # Measure text on a dummy surface first
    _tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = _tmp_draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Create overlay larger than (w, h) so that after 20° rotation the corners still have coverage
    angle = 20
    pad = int(max(w, h) * math.sin(math.radians(angle))) + font_size
    ow, oh = w + pad * 2, h + pad * 2

    overlay = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    step_x = tw + max(30, w // 6)
    step_y = th + max(24, h // 8)
    for row, base_y in enumerate(range(-step_y, oh + step_y, step_y)):
        offset_x = (tw // 2) if row % 2 else 0
        for base_x in range(-step_x + offset_x, ow + step_x, step_x):
            draw.text((base_x, base_y), text, font=font, fill=(255, 255, 255, 48))

    rotated = overlay.rotate(angle, expand=False)
    # Crop the center (w, h) region from the rotated overlay
    left = (ow - w) // 2
    top = (oh - h) // 2
    cropped = rotated.crop((left, top, left + w, top + h))

    result = Image.alpha_composite(img, cropped).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, "WEBP", quality=72, method=4)
    thumb_path.write_bytes(buf.getvalue())


@app.get(f"{API_ADMIN_PREFIX}/incoming/thumb/{{filename}}", tags=["Incoming"])
async def get_incoming_thumb(filename: str, pb_session: Optional[str] = Cookie(default=None)) -> FileResponse:
    _require_auth(pb_session)
    if not validate_filename_safety(filename):
        raise HTTPException(status_code=400, detail="無效的檔案名稱")
    src_path = INCOMING_DIR / filename
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"找不到照片: {filename}")
    try:
        src_path.resolve().relative_to(INCOMING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="路徑驗證失敗")

    thumb_path = THUMB_DIR / f"{filename}.thumb.webp"
    if not thumb_path.exists():
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _generate_thumbnail, src_path, thumb_path)
        except Exception as e:
            logger.error(f"縮圖生成失敗 {filename}: {e}")
            raise HTTPException(status_code=500, detail="縮圖生成失敗")

    return FileResponse(
        str(thumb_path),
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.delete(f"{API_ADMIN_PREFIX}/incoming/{{filename}}", tags=["Incoming"])
async def delete_incoming(filename: str, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if not validate_filename_safety(filename):
        raise HTTPException(status_code=400, detail="無效的檔案名稱")
    file_path = INCOMING_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"找不到照片: {filename}")
    try:
        file_path.resolve().relative_to(INCOMING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="檔案路徑驗證失敗")
    file_path.unlink()
    for thumb_path in [
        THUMB_DIR / f"{filename}.thumb.webp",
        THUMB_DIR / f"{filename}.thumb.jpg",
    ]:
        if thumb_path.exists():
            thumb_path.unlink()
    pub_thumb = _pub_thumb_path(filename)
    if pub_thumb.exists():
        pub_thumb.unlink()
    if filename in _photo_codes:
        code = _photo_codes.pop(filename)
        _code_to_file.pop(code, None)
        _save_photo_codes()
    return {"message": f"已刪除 {filename}", "filename": filename}


@app.delete(f"{API_ADMIN_PREFIX}/incoming", tags=["Incoming"])
async def clear_incoming(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    deleted, errors = [], []
    for p in INCOMING_DIR.iterdir():
        if p.suffix.lower() in SUPPORTED_IMAGE_FORMATS:
            try:
                p.unlink()
                deleted.append(p.name)
                for thumb_path in [
                    THUMB_DIR / f"{p.name}.thumb.webp",
                    THUMB_DIR / f"{p.name}.thumb.jpg",
                ]:
                    if thumb_path.exists():
                        thumb_path.unlink()
                pub_thumb = _pub_thumb_path(p.name)
                if pub_thumb.exists():
                    pub_thumb.unlink()
                if p.name in _photo_codes:
                    code = _photo_codes.pop(p.name)
                    _code_to_file.pop(code, None)
            except Exception as e:
                errors.append(f"{p.name}: {e}")
    if deleted:
        _save_photo_codes()
    return {"deleted": deleted, "errors": errors, "count": len(deleted)}


@app.post(f"{API_ADMIN_PREFIX}/upload-incoming", tags=["Incoming"])
async def upload_incoming(
    file: UploadFile = File(...),
    pb_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_auth(pb_session)
    if not file.filename:
        raise HTTPException(status_code=400, detail="檔案名稱為空")
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail=f"不支援的格式（{ext}）")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="檔案超過 50MB 限制")
    raw_stem = re.sub(r'[^\w\-]', '', Path(file.filename).stem)[:32] or 'photo'
    ts = int(time.time() * 1000)
    safe_name = f"{ts}_{raw_stem}{ext}"
    dest = INCOMING_DIR / safe_name
    suffix = 0
    while dest.exists():
        suffix += 1
        safe_name = f"{ts}_{raw_stem}_{suffix}{ext}"
        dest = INCOMING_DIR / safe_name
    try:
        dest.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"儲存失敗: {e}")
    code = _assign_code(safe_name)
    await manager.broadcast({
        "type": WS_MESSAGE_TYPE_NEW_INCOMING,
        "filename": safe_name,
        "url": f"{STATIC_INCOMING_ROUTE}/{safe_name}",
        "code": code,
        "timestamp": time.time(),
    })
    logger.info(f"✓ 管理員上傳照片: {safe_name} → {code}")
    return {"filename": safe_name, "code": code}


@app.post(f"{API_ADMIN_PREFIX}/open-incoming-folder", tags=["Incoming"])
async def open_incoming_folder(request: Request, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    # 使用 TCP 連線來源 IP（不信任可被偽造的 Host header），防止 ngrok 環境下的 Host 偽造
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="此功能僅限本機存取")
    folder = INCOMING_DIR.resolve()
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return {"message": "已開啟資料夾", "path": str(folder)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法開啟資料夾: {e}")



# ==================== ngrok 外網穿透 API ====================

@app.get(f"{API_ADMIN_PREFIX}/ngrok/status", tags=["Ngrok"])
async def get_ngrok_status(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    return {"active": ngrok_is_active(), "public_url": get_tunnel_url(), "has_token": _load_ngrok_token() is not None}


class NgrokTokenRequest(BaseModel):
    auth_token: str


@app.post(f"{API_ADMIN_PREFIX}/ngrok/token", tags=["Ngrok"])
async def save_ngrok_token(request: NgrokTokenRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if not request.auth_token.strip():
        raise HTTPException(status_code=400, detail="Auth Token 不得為空")
    try:
        _save_ngrok_token(request.auth_token.strip())
        return {"message": "ngrok Auth Token 已儲存"}
    except Exception as e:
        logger.error(f"ngrok token 儲存失敗: {e}")
        raise HTTPException(status_code=500, detail="Token 儲存失敗")


@app.post(f"{API_ADMIN_PREFIX}/ngrok/start", tags=["Ngrok"])
async def start_ngrok(request: NgrokStartRequest, http_request: Request, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    # 優先使用 uvicorn 實際監聽的 port，避免與 PORT 設定不一致
    server = http_request.scope.get("server")
    port = server[1] if server and server[1] else (request.port or NGROK_DEFAULT_PORT)
    token = _load_ngrok_token()
    if token is None:
        raise HTTPException(status_code=400, detail="請先設定 ngrok Auth Token，或透過環境變數 NGROK_AUTHTOKEN 注入")
    try:
        loop = asyncio.get_running_loop()
        public_url = await loop.run_in_executor(
            None, functools.partial(start_tunnel, port, token)
        )
        return {"active": True, "public_url": public_url, "message": "ngrok 隧道啟動成功"}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{API_ADMIN_PREFIX}/ngrok/stop", tags=["Ngrok"])
async def stop_ngrok(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, stop_tunnel)
    return {"active": False, "public_url": None, "message": "ngrok 隧道已關閉"}


# ==================== LINE BOT API ====================

@app.get(f"{API_ADMIN_PREFIX}/line/config", tags=["LINE"])
async def get_line_config(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    configured = line_bot.is_configured()
    base = _get_public_base_url()
    webhook_url = f"{base}/api/line/webhook" if base else ""
    return {"configured": configured, "webhook_url": webhook_url}


@app.post(f"{API_ADMIN_PREFIX}/line/config", tags=["LINE"])
async def save_line_config(request: LineConfigRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    if not request.channel_secret or not request.channel_access_token:
        raise HTTPException(status_code=400, detail="Channel Secret 與 Access Token 不得為空")
    try:
        _save_line_config(request.channel_secret, request.channel_access_token)
        _init_line_bot({"channel_secret": request.channel_secret, "channel_access_token": request.channel_access_token})
        return {"message": "LINE BOT 設定已儲存並套用"}
    except Exception as e:
        logger.error(f"LINE BOT 設定儲存失敗: {e}")
        raise HTTPException(status_code=500, detail="LINE BOT 設定失敗，請檢查憑證是否正確")


# ==================== 照片取件頁面 ====================

@app.get("/download/{code}", tags=["Photo Pickup"])
async def photo_download_page(code: str, request: Request) -> HTMLResponse:
    if not _check_code_rate_limit(_get_client_ip(request)):
        raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試")
    code = code.strip().upper()
    filename = _lookup_code(code)
    if not filename or not (INCOMING_DIR / filename).exists():
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:4rem'>找不到照片，取件碼可能已過期或不存在。</h3>", status_code=404)
    try:
        html = _apply_nonce(_get_html("download.html"), request.state.csp_nonce).replace("{code}", code)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")
    return HTMLResponse(html)


@app.get("/api/photo/{code}", tags=["Photo Pickup"])
async def serve_photo(code: str, request: Request, dl: int = 0) -> FileResponse:
    if not _check_code_rate_limit(_get_client_ip(request)):
        raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試")
    code = code.strip().upper()
    filename = _lookup_code(code)
    if not filename:
        raise HTTPException(status_code=404, detail="找不到對應照片")
    file_path = INCOMING_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="照片檔案不存在")
    try:
        file_path.resolve().relative_to(INCOMING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="路徑驗證失敗")
    ext = file_path.suffix.lower()
    media_type = {"png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}" if dl else "inline"
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@app.get("/api/photo/{code}/thumb", tags=["Photo Pickup"])
async def serve_photo_thumb(code: str, request: Request) -> FileResponse:
    """取件預覽縮圖（480px，無浮水印）：依 Accept header 回傳 WebP 或 JPEG，相容 iOS 13 等不支援 WebP 的瀏覽器。"""
    if not _check_code_rate_limit(_get_client_ip(request)):
        raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試")
    code = code.strip().upper()
    filename = _lookup_code(code)
    if not filename:
        raise HTTPException(status_code=404, detail="找不到對應照片")
    src_path = INCOMING_DIR / filename
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="照片檔案不存在")
    try:
        src_path.resolve().relative_to(INCOMING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="路徑驗證失敗")

    accept = request.headers.get("accept", "")
    if "image/webp" in accept:
        thumb_path = THUMB_DIR / f"{filename}.thumb.webp"
        media_type = "image/webp"
        fmt = "WEBP"
    else:
        thumb_path = THUMB_DIR / f"{filename}.thumb.jpg"
        media_type = "image/jpeg"
        fmt = "JPEG"

    if not thumb_path.exists():
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _generate_thumbnail, src_path, thumb_path, fmt)
        except Exception as e:
            logger.error(f"取件縮圖生成失敗 {filename}: {e}")
            raise HTTPException(status_code=500, detail="縮圖生成失敗")
    return FileResponse(
        str(thumb_path),
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ==================== 系統重置 API ====================

@app.post(f"{API_ADMIN_PREFIX}/reset", tags=["System"])
async def reset_system(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    global _photo_codes, _code_to_file

    results = {}

    # 停止並清除 ngrok 設定
    try:
        if ngrok_is_active():
            stop_tunnel()
        if NGROK_CONFIG_FILE.exists():
            NGROK_CONFIG_FILE.unlink()
        try:
            from pyngrok import conf as _ngrok_conf
            _ngrok_conf.get_default().auth_token = None
        except Exception:
            pass
        results["ngrok_config"] = "已清除"
    except Exception as e:
        results["ngrok_config"] = f"失敗: {e}"

    # 清除 LINE BOT 設定
    try:
        if LINE_CONFIG_FILE.exists():
            LINE_CONFIG_FILE.unlink()
        line_bot.reset()
        results["line_config"] = "已清除"
    except Exception as e:
        results["line_config"] = f"失敗: {e}"

    # 清除取件碼
    try:
        _photo_codes.clear()
        _code_to_file.clear()
        PHOTO_CODES_FILE.write_text("{}", encoding="utf-8")
        results["photo_codes"] = "已清除"
    except Exception as e:
        results["photo_codes"] = f"失敗: {e}"

    # 刪除拍攝照片與縮圖快取
    try:
        deleted = 0
        for p in list(INCOMING_DIR.iterdir()):
            if p.is_file():
                p.unlink()
                deleted += 1
        for t in list(THUMB_DIR.iterdir()):
            if t.is_file():
                t.unlink()
        results["incoming_photos"] = f"已刪除 {deleted} 張"
    except Exception as e:
        results["incoming_photos"] = f"失敗: {e}"

    # 移除底圖
    try:
        cleared = False
        for name in ("bg.jpg", "bg.webp"):
            p = BG_DIR / name
            if p.exists():
                p.unlink()
                cleared = True
        results["background"] = "已清除" if cleared else "無底圖，略過"
    except Exception as e:
        results["background"] = f"失敗: {e}"

    # 重置首頁文字
    try:
        if INDEX_TEXT_FILE.exists():
            INDEX_TEXT_FILE.unlink()
        results["index_text"] = "已重置為預設值"
    except Exception as e:
        results["index_text"] = f"失敗: {e}"

    # 重置 Gallery 設定（含清除 in-memory 快取）
    try:
        global _gallery_config_cache
        if GALLERY_CONFIG_FILE.exists():
            GALLERY_CONFIG_FILE.unlink()
        _gallery_config_cache = None
        _invalidate_public_thumbs()
        results["gallery_config"] = "已重置為預設值"
    except Exception as e:
        results["gallery_config"] = f"失敗: {e}"

    # 清除自訂字型
    try:
        cleared = 0
        for f in FONTS_DIR.iterdir():
            if f.is_file():
                f.unlink()
                cleared += 1
        if FONTS_META_FILE.exists():
            FONTS_META_FILE.unlink()
        results["custom_fonts"] = f"已刪除 {cleared} 個字型" if cleared else "無自訂字型，略過"
    except Exception as e:
        results["custom_fonts"] = f"失敗: {e}"

    logger.info("✓ 系統已執行重置")
    return {"message": "系統已重置完成", "details": results}


@app.post("/api/line/webhook", tags=["LINE"])
async def line_webhook(request: Request) -> Response:
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None, functools.partial(line_bot.handle_webhook, body, signature)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return Response(content="OK", status_code=200)
