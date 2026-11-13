"""將照片送到本機印表機（同步阻塞，呼叫端需以 run_in_executor 包裝）。"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import PRINT_PRINTER_NAME_PATTERN, PRINT_TIMEOUT_SECONDS

_PRINTER_RE = re.compile(PRINT_PRINTER_NAME_PATTERN)


def is_valid_printer_name(name: str) -> bool:
    return bool(_PRINTER_RE.fullmatch(name))


def print_image(path: Path, printer: str = "") -> None:
    """Windows：未指定印表機用預設印表機（shell print 動詞），指定則用 mspaint /pt；其他系統用 lp（CUPS）。失敗時拋出 RuntimeError。"""
    if printer and not is_valid_printer_name(printer):
        raise RuntimeError("印表機名稱格式不正確")
    target = str(path.resolve())
    try:
        if sys.platform == "win32":
            if printer:
                subprocess.run(["mspaint", "/pt", target, printer], check=True, timeout=PRINT_TIMEOUT_SECONDS)
            else:
                os.startfile(target, "print")  # type: ignore[attr-defined]
            return
        lp = shutil.which("lp")
        if not lp:
            raise RuntimeError("找不到 lp 指令，請安裝 CUPS")
        cmd = [lp]
        if printer:
            cmd += ["-d", printer]
        cmd += ["-o", "fit-to-page", target]
        subprocess.run(cmd, check=True, timeout=PRINT_TIMEOUT_SECONDS, capture_output=True)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("列印指令逾時") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "ignore").strip() if isinstance(e.stderr, bytes) else ""
        raise RuntimeError(f"列印失敗: {detail or e}") from e
    except OSError as e:
        raise RuntimeError(f"列印失敗: {e}") from e
