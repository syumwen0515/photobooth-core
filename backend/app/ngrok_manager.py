"""
ngrok 外網穿透管理模組
使用 pyngrok 建立/銷毀 HTTP 隧道，讓展場訪客可透過公網掃 QR Code 下載相片。
"""

import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_tunnel = None

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_domain(raw: Optional[str]) -> Optional[str]:
    """正規化自訂網域（去除協定與路徑）；空字串回傳 None，格式不合法拋出 ValueError。"""
    value = (raw or "").strip().lower()
    if not value:
        return None
    value = re.sub(r"^https?://", "", value).split("/")[0]
    if not _DOMAIN_RE.match(value):
        raise ValueError("自訂網域格式不正確，例如 photo.example.com")
    return value


def start_tunnel(port: int = 8000, auth_token: Optional[str] = None, domain: Optional[str] = None) -> str:
    """啟動 ngrok HTTP 隧道，回傳公開 URL。已啟動則直接回傳現有 URL。"""
    global _tunnel

    try:
        from pyngrok import ngrok, conf, exception as ngrok_exc
    except ImportError:
        raise RuntimeError("pyngrok 未安裝，請執行 pip install pyngrok")

    if _tunnel is not None:
        return _tunnel.public_url

    resolved_token = auth_token or os.getenv("NGROK_AUTHTOKEN") or os.getenv("NGROK_AUTH_TOKEN")
    if resolved_token:
        conf.get_default().auth_token = resolved_token

    try:
        if domain:
            _tunnel = ngrok.connect(port, "http", domain=domain)
        else:
            _tunnel = ngrok.connect(port, "http")
        logger.info(f"✓ ngrok 隧道已啟動: {_tunnel.public_url}")
        return _tunnel.public_url
    except ngrok_exc.PyngrokNgrokError as e:
        _tunnel = None
        raise RuntimeError(f"ngrok 啟動失敗: {e}") from e


def stop_tunnel() -> None:
    """關閉現有的 ngrok 隧道。"""
    global _tunnel

    try:
        from pyngrok import ngrok
    except ImportError:
        return

    if _tunnel is not None:
        try:
            ngrok.disconnect(_tunnel.public_url)
        except Exception:
            pass
        _tunnel = None

    try:
        ngrok.kill()
    except Exception:
        pass

    logger.info("🛑 ngrok 隧道已關閉")


def get_tunnel_url() -> Optional[str]:
    """回傳目前公開 HTTPS URL，未啟動則回傳 None。"""
    if _tunnel is None:
        return None
    url = _tunnel.public_url
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def is_active() -> bool:
    return _tunnel is not None
