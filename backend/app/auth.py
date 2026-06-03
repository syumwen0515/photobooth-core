import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ACCOUNTS_FILE: Optional[Path] = None
_SESSION_TTL_HOURS = 24 * 7  # 7 天
_sessions: dict = {}

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_MINUTES = 10
_failed_logins: dict = {}  # username → {"count": int, "first_at": datetime}

_PBKDF2_ITERATIONS = 260_000


def init(accounts_file: Path) -> None:
    global _ACCOUNTS_FILE
    _ACCOUNTS_FILE = accounts_file
    _ensure_default_account()


# ── 密碼雜湊（PBKDF2-HMAC-SHA256，向下相容舊 SHA-256）──────────

def _hash_password_pbkdf2(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return base64.b64encode(dk).decode("ascii")


def _hash_password_sha256(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: str) -> str:
    return _hash_password_pbkdf2(password, salt)


def _verify_password(password: str, account: dict) -> bool:
    algo = account.get("algo", "sha256")
    if algo == "pbkdf2":
        return hmac.compare_digest(account["password_hash"], _hash_password_pbkdf2(password, account["salt"]))
    # 舊 SHA-256 帳號：驗證成功後自動升級
    if hmac.compare_digest(account["password_hash"], _hash_password_sha256(password, account["salt"])):
        return True
    return False


def _upgrade_to_pbkdf2(username: str, password: str) -> None:
    """舊 SHA-256 帳號登入成功後，靜默升級為 PBKDF2。"""
    accounts = _load_accounts()
    for acc in accounts:
        if acc["username"] == username and acc.get("algo", "sha256") == "sha256":
            acc["salt"] = secrets.token_hex(16)
            acc["password_hash"] = _hash_password_pbkdf2(password, acc["salt"])
            acc["algo"] = "pbkdf2"
            _save_accounts(accounts)
            return


# ── 帳號持久化 ───────────────────────────────────────────────

def _load_accounts() -> list:
    if not _ACCOUNTS_FILE or not _ACCOUNTS_FILE.exists():
        return []
    try:
        return json.loads(_ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_accounts(accounts: list) -> None:
    _ACCOUNTS_FILE.write_text(
        json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _ensure_default_account() -> None:
    if not _load_accounts():
        salt = secrets.token_hex(16)
        _save_accounts([{
            "username": "admin",
            "password_hash": _hash_password_pbkdf2("admin", salt),
            "salt": salt,
            "algo": "pbkdf2",
        }])


# ── 登入失敗鎖定 ─────────────────────────────────────────────

def _is_locked_out(username: str) -> bool:
    record = _failed_logins.get(username)
    if not record:
        return False
    if datetime.now() - record["first_at"] > timedelta(minutes=_LOGIN_LOCKOUT_MINUTES):
        _failed_logins.pop(username, None)
        return False
    return record["count"] >= _LOGIN_MAX_ATTEMPTS


def _record_failed_login(username: str) -> None:
    record = _failed_logins.get(username)
    if not record or datetime.now() - record["first_at"] > timedelta(minutes=_LOGIN_LOCKOUT_MINUTES):
        _failed_logins[username] = {"count": 1, "first_at": datetime.now()}
    else:
        record["count"] += 1


def _clear_failed_logins(username: str) -> None:
    _failed_logins.pop(username, None)


def verify_credentials(username: str, password: str) -> bool:
    if _is_locked_out(username):
        return False
    for acc in _load_accounts():
        if acc["username"] == username:
            if _verify_password(password, acc):
                _clear_failed_logins(username)
                # 舊帳號靜默升級
                if acc.get("algo", "sha256") == "sha256":
                    _upgrade_to_pbkdf2(username, password)
                return True
            _record_failed_login(username)
            return False
    _record_failed_login(username)
    return False


def is_account_locked(username: str) -> bool:
    return _is_locked_out(username)


# ── Session 管理 ─────────────────────────────────────────────

def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"username": username, "created_at": datetime.now()}
    return token


def validate_session(token: Optional[str]) -> Optional[str]:
    if not token or token not in _sessions:
        return None
    sess = _sessions[token]
    if datetime.now() - sess["created_at"] > timedelta(hours=_SESSION_TTL_HOURS):
        del _sessions[token]
        return None
    return sess["username"]


def destroy_session(token: str) -> None:
    _sessions.pop(token, None)


def cleanup_expired_sessions() -> int:
    """清理過期 session，回傳清除數量。"""
    cutoff = datetime.now() - timedelta(hours=_SESSION_TTL_HOURS)
    expired = [t for t, s in _sessions.items() if s["created_at"] < cutoff]
    for t in expired:
        del _sessions[t]
    return len(expired)


# ── 帳號 CRUD ────────────────────────────────────────────────

def get_accounts() -> list[str]:
    return [a["username"] for a in _load_accounts()]


def add_account(username: str, password: str) -> tuple[bool, str]:
    if len(username) < 2:
        return False, "帳號至少需要 2 個字元"
    if len(password) < 8:
        return False, "密碼至少需要 8 個字元"
    accounts = _load_accounts()
    if any(a["username"] == username for a in accounts):
        return False, "帳號已存在"
    salt = secrets.token_hex(16)
    accounts.append({
        "username": username,
        "password_hash": _hash_password_pbkdf2(password, salt),
        "salt": salt,
        "algo": "pbkdf2",
    })
    _save_accounts(accounts)
    return True, "帳號新增成功"


def delete_account(username: str) -> tuple[bool, str]:
    accounts = _load_accounts()
    if len(accounts) <= 1:
        return False, "至少需保留一組帳號"
    new_accounts = [a for a in accounts if a["username"] != username]
    if len(new_accounts) == len(accounts):
        return False, "帳號不存在"
    _save_accounts(new_accounts)
    return True, "帳號已刪除"


def change_password(username: str, new_password: str) -> tuple[bool, str]:
    if len(new_password) < 8:
        return False, "密碼至少需要 8 個字元"
    accounts = _load_accounts()
    for acc in accounts:
        if acc["username"] == username:
            acc["salt"] = secrets.token_hex(16)
            acc["password_hash"] = _hash_password_pbkdf2(new_password, acc["salt"])
            acc["algo"] = "pbkdf2"
            _save_accounts(accounts)
            return True, "密碼已更新"
    return False, "帳號不存在"
