import hashlib
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_ACCOUNTS_FILE: Optional[Path] = None
_SESSION_TTL_HOURS = 24 * 7  # 7 天
_sessions: dict = {}

# 登入失敗次數限制：同一帳號 10 分鐘內超過 5 次失敗則鎖定
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_MINUTES = 10
_failed_logins: dict = {}  # username → {"count": int, "first_at": datetime}


def init(accounts_file: Path) -> None:
    global _ACCOUNTS_FILE
    _ACCOUNTS_FILE = accounts_file
    _ensure_default_account()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()


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
            "password_hash": _hash_password("admin", salt),
            "salt": salt,
        }])


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
            if acc["password_hash"] == _hash_password(password, acc["salt"]):
                _clear_failed_logins(username)
                return True
            _record_failed_login(username)
            return False
    _record_failed_login(username)
    return False


def is_account_locked(username: str) -> bool:
    return _is_locked_out(username)


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
        "password_hash": _hash_password(password, salt),
        "salt": salt,
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
            acc["password_hash"] = _hash_password(new_password, acc["salt"])
            _save_accounts(accounts)
            return True, "密碼已更新"
    return False, "帳號不存在"
