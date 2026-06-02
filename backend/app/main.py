import asyncio
import functools
import json
import os
import subprocess
import sys
import random
import logging
from urllib.parse import quote
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Cookie, Request
from websockets.exceptions import ConnectionClosedError
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime

from app.watcher import start_watcher
from app.ngrok_manager import start_tunnel, stop_tunnel, get_tunnel_url, is_active as ngrok_is_active
from app import auth, line_bot
from app.config import (
    APP_TITLE, APP_VERSION, APP_DESCRIPTION,
    TEMPLATE_DIR, INCOMING_DIR,
    BG_DIR, ACCOUNTS_FILE,
    CORS_ORIGINS, CORS_ALLOW_CREDENTIALS, CORS_ALLOW_METHODS, CORS_ALLOW_HEADERS,
    MAX_FILE_SIZE_BYTES, SUPPORTED_IMAGE_FORMATS,
    STATIC_INCOMING_ROUTE, STATIC_BG_ROUTE,
    API_ADMIN_PREFIX, WS_PHOTO_ROUTE,
    LOG_LEVEL, LOG_FORMAT,
    SESSION_COOKIE_NAME,
    LINE_CONFIG_FILE, PHOTO_CODES_FILE, PUBLIC_BASE_URL,
    NGROK_CONFIG_FILE,
    THUMB_DIR,
    INDEX_TEXT_FILE, INDEX_TEXT_DEFAULTS,
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ── 取件碼字元表（移除易混淆字元 0/O/1/I）───────────────────
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(_CODE_CHARS, k=length))


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


def _load_index_text() -> Dict[str, str]:
    if INDEX_TEXT_FILE.exists():
        try:
            data = json.loads(INDEX_TEXT_FILE.read_text(encoding="utf-8"))
            return {**INDEX_TEXT_DEFAULTS, **data}
        except Exception:
            pass
    return dict(INDEX_TEXT_DEFAULTS)


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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔗 新 WebSocket 連接 (總連接數: {len(self.active_connections)})")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"🔌 WebSocket 斷線 (剩餘: {len(self.active_connections)})")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"⚠️ 廣播失敗: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)


manager = ConnectionManager()


# ==================== 應用程式生命週期 ====================

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
    logger.info("✓ 拍貼機服務啟動完成")
    yield
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
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
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
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

app.mount(STATIC_INCOMING_ROUTE, StaticFiles(directory=str(INCOMING_DIR)), name="incoming_photos")
app.mount(STATIC_BG_ROUTE, StaticFiles(directory=str(BG_DIR)), name="bg")


# ==================== Pydantic 模型 ====================

class NgrokStartRequest(BaseModel):
    port: int = 8000

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
async def get_index() -> str:
    try:
        return _get_html("index.html")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")



@app.get("/login", response_class=HTMLResponse, tags=["Pages"])
async def get_login_page() -> str:
    try:
        return _get_html("login.html")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")


@app.get("/admin", response_class=HTMLResponse, tags=["Pages"])
async def get_admin_page(pb_session: Optional[str] = Cookie(default=None)) -> Response:
    if not auth.validate_session(pb_session):
        return RedirectResponse(url="/login", status_code=302)
    try:
        return HTMLResponse(_get_html("admin.html"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="頁面不存在")


# ==================== WebSocket 端點 ====================

@app.websocket(WS_PHOTO_ROUTE)
async def websocket_endpoint(websocket: WebSocket) -> None:
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
async def login(request: LoginRequest, response: Response) -> Dict[str, str]:
    if auth.is_account_locked(request.username):
        raise HTTPException(status_code=429, detail="登入嘗試次數過多，請稍後再試")
    if not auth.verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    token = auth.create_session(request.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return {"message": "登入成功", "username": request.username}


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
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(content)).convert("RGB")
        if img.width > 1920:
            ratio = 1920 / img.width
            img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)
        img.save(str(BG_DIR / "bg.jpg"), "JPEG", quality=82, optimize=True, progressive=True)
        img.save(str(BG_DIR / "bg.webp"), "WEBP", quality=78, method=6)
        logger.info(f"✓ 首頁底圖已更新 ({img.width}×{img.height})")
        return {"message": "底圖上傳成功", "url": f"{STATIC_BG_ROUTE}/bg.jpg"}
    except Exception as e:
        logger.error(f"底圖處理失敗: {e}")
        raise HTTPException(status_code=500, detail="圖片處理失敗")


@app.delete(f"{API_ADMIN_PREFIX}/bg", tags=["Background"])
async def delete_bg(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    bg_path = BG_DIR / "bg.jpg"
    if not bg_path.exists():
        raise HTTPException(status_code=404, detail="尚未上傳底圖")
    bg_path.unlink()
    webp_path = BG_DIR / "bg.webp"
    if webp_path.exists():
        webp_path.unlink()
    return {"message": "底圖已刪除"}


@app.get(f"{API_ADMIN_PREFIX}/bg-status", tags=["Background"])
async def get_bg_status() -> Dict[str, Any]:
    bg_path = BG_DIR / "bg.jpg"
    return {"exists": bg_path.exists(), "url": f"{STATIC_BG_ROUTE}/bg.jpg" if bg_path.exists() else None}


# ==================== 首頁文字 API ====================

@app.get("/api/index-text", tags=["IndexText"])
async def get_index_text() -> Dict[str, str]:
    return _load_index_text()


@app.post(f"{API_ADMIN_PREFIX}/index-text", tags=["IndexText"])
async def save_index_text(request: IndexTextRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    allowed_fonts = {"Noto Sans JP", "Noto Serif JP", "M PLUS Rounded 1c", "Zen Kaku Gothic New", "Shippori Mincho"}
    if request.font not in allowed_fonts:
        raise HTTPException(status_code=400, detail="不支援的字體")
    data = {
        "main_title": request.main_title[:30],
        "subtitle": request.subtitle[:30],
        "middle_text": request.middle_text[:60],
        "font": request.font,
    }
    _save_index_text(data)
    return {"message": "首頁文字設定已儲存"}


# ==================== 拍攝照片管理 API ====================

@app.get(f"{API_ADMIN_PREFIX}/incoming", tags=["Incoming"])
async def list_incoming(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    try:
        paths = [p for p in INCOMING_DIR.iterdir() if p.suffix.lower() in SUPPORTED_IMAGE_FORMATS]
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        photos = [{"filename": p.name, "code": _photo_codes.get(p.name)} for p in paths]
        return {"photos": photos, "count": len(photos)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"無法取得照片列表: {e}")


@app.get(f"{API_ADMIN_PREFIX}/incoming/thumb/{{filename}}", tags=["Incoming"])
async def get_incoming_thumb(filename: str, pb_session: Optional[str] = Cookie(default=None)) -> Response:
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
            from PIL import Image, ImageOps
            import io
            img = ImageOps.exif_transpose(Image.open(src_path)).convert("RGB")
            img.thumbnail((480, 480), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=72, method=4)
            thumb_path.write_bytes(buf.getvalue())
        except Exception as e:
            logger.error(f"縮圖生成失敗 {filename}: {e}")
            raise HTTPException(status_code=500, detail="縮圖生成失敗")

    return Response(
        content=thumb_path.read_bytes(),
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
    thumb_path = THUMB_DIR / f"{filename}.thumb.webp"
    if thumb_path.exists():
        thumb_path.unlink()
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
                thumb_path = THUMB_DIR / f"{p.name}.thumb.webp"
                if thumb_path.exists():
                    thumb_path.unlink()
                if p.name in _photo_codes:
                    code = _photo_codes.pop(p.name)
                    _code_to_file.pop(code, None)
            except Exception as e:
                errors.append(f"{p.name}: {e}")
    if deleted:
        _save_photo_codes()
    return {"deleted": deleted, "errors": errors, "count": len(deleted)}


@app.post(f"{API_ADMIN_PREFIX}/open-incoming-folder", tags=["Incoming"])
async def open_incoming_folder(request: Request, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    host = request.headers.get("host", "").split(":")[0]
    if host not in ("localhost", "127.0.0.1", "::1"):
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
    return {"active": ngrok_is_active(), "public_url": get_tunnel_url()}


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
async def start_ngrok(request: NgrokStartRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    token = _load_ngrok_token()
    try:
        loop = asyncio.get_running_loop()
        public_url = await loop.run_in_executor(
            None, functools.partial(start_tunnel, request.port, token)
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
async def photo_download_page(code: str) -> HTMLResponse:
    code = code.strip().upper()
    filename = _lookup_code(code)
    if not filename or not (INCOMING_DIR / filename).exists():
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:4rem'>找不到照片，取件碼可能已過期或不存在。</h3>", status_code=404)
    template_path = TEMPLATE_DIR / "download.html"
    html = template_path.read_text(encoding="utf-8").replace("{code}", code)
    return HTMLResponse(html)


@app.get("/api/photo/{code}", tags=["Photo Pickup"])
async def serve_photo(code: str, dl: int = 0) -> FileResponse:
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


# ==================== 系統重置 API ====================

@app.post(f"{API_ADMIN_PREFIX}/reset", tags=["System"])
async def reset_system(pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, Any]:
    _require_auth(pb_session)
    global _photo_codes, _code_to_file

    results = {}

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
        deleted = sum(1 for p in INCOMING_DIR.iterdir() if p.is_file() and not p.unlink())
        for t in THUMB_DIR.iterdir():
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
