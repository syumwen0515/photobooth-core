# AGENTS.md — AI 代理開發指引

本文件供 AI 代理（Claude Code 等）在此專案工作時參考。說明如何執行專案、程式碼慣例、架構決策，以及禁止事項。

---

## 技術棧

| 層次 | 技術 |
|------|------|
| Runtime | Python 3.14（Windows 內嵌，位於 `python/`）|
| Web 框架 | FastAPI + Uvicorn |
| 即時通訊 | WebSocket（FastAPI 原生）|
| 檔案監聽 | Watchdog |
| 圖片處理 | Pillow（Pillow 操作必須用 `run_in_executor` 非同步化）|
| 外網穿透 | pyngrok |
| LINE 整合 | line-bot-sdk v3 |
| 前端 | 純 HTML + Tailwind CDN + Axios CDN（無建置工具）|

---

## 執行專案

```powershell
# Windows — 使用內嵌 Python
cd backend
..\python\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 開發模式（自動重載 + 開放 API 文件）
$env:ENABLE_API_DOCS="true"; $env:RELOAD_ADMIN_HTML="true"
..\python\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

語法檢查（不執行應用，只做靜態分析）：
```powershell
..\python\python.exe -c "import ast; ast.parse(open('app/main.py', encoding='utf-8').read()); print('OK')"
```

---

## 目錄結構與關鍵檔案

```
backend/app/
├── config.py        ← 所有常數與環境變數的唯一來源
├── main.py          ← FastAPI app、所有路由、middleware、lifespan
├── auth.py          ← 密碼雜湊（PBKDF2）、Session、帳號 CRUD
├── line_bot.py      ← LINE Webhook handler（stateless，透過 init() 注入依賴）
├── watcher.py       ← Watchdog 監聽 incoming/，廣播 WebSocket 事件
├── ngrok_manager.py ← pyngrok 隧道生命週期
└── templates/       ← 純靜態 HTML，啟動時載入並快取於記憶體
```

`storage/` 目錄由程式自動建立，不應納入版本控制（`accounts.json` 含密碼雜湊，`line_config.json` 含 API Token）。

---

## 程式碼慣例

### 新增路由
1. Pydantic 模型定義在 `main.py` 的 `# ==================== Pydantic 模型 ====================` 區塊
2. 需要認證的路由呼叫 `_require_auth(pb_session)`，回傳 `username`
3. 管理員路由路徑前綴為 `API_ADMIN_PREFIX`（`/api/admin`），從 config.py import
4. 回傳型別標註 `Dict[str, Any]` 或具體型別

### 設定值
**所有常數必須定義在 `config.py`**，`main.py` 只做 import。不允許在路由函數或業務邏輯中寫死數值。

### 圖片處理（Pillow）
必須用 `run_in_executor` 包裝，避免阻塞 asyncio 事件迴圈：
```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, sync_function, arg1, arg2)
```

### 檔案安全
所有接受 filename 參數的路由，必須：
1. `validate_filename_safety(filename)` — 拒絕路徑遍歷字元
2. `path.resolve().relative_to(base_dir.resolve())` — 確認最終路徑在允許目錄內

### Session / Cookie
- Session 存在記憶體 dict `_sessions`，服務重啟後失效（設計如此）
- Cookie 名稱從 config 的 `SESSION_COOKIE_NAME` 取得
- `SECURE_COOKIES` 環境變數控制 Secure flag（ngrok HTTPS 環境需設 `true`）

---

## 架構決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-06-02 | 移除 compositor.py / printer.py / borders/ | 不需要合成 / 列印功能，直接使用 incoming 原圖 |
| 2026-06-02 | 移除 2×3/2×4 版型功能 | 簡化流程，不需多版型選片 |
| 2026-06-02 | PIL 圖片處理改用 run_in_executor | PIL 是 CPU 密集操作，直接在 async 函數呼叫會阻塞整個事件迴圈 |
| 2026-06-02 | WebSocket ConnectionManager 改用 set | list.remove 是 O(n)；set.discard 是 O(1) |
| 2026-06-02 | 設定常數集中至 config.py | main.py 中與邏輯無關的純設定值應統一由 config.py 管理 |
| 2026-06-02 | 密碼雜湊升級 SHA-256 → PBKDF2-HMAC-SHA256 | SHA-256 速度太快，容易被 GPU 暴力破解；PBKDF2 以計算成本防禦彩虹表 |
| 2026-06-02 | WebSocket 加入 Session 認證 | 未認證的 WS 端點讓任何人都能監聽展場照片的即時拍攝通知 |
| 2026-06-02 | 取件碼端點加速率限制 | 防止自動化腳本枚舉取件碼竊取照片 |
| 2026-06-02 | API Docs 預設關閉 | `/api/docs` 向任何知道 URL 的人暴露完整 API 結構 |

---

## 安全性規則（禁止違反）

- **不得**使用 SHA-256 / MD5 / SHA-1 做密碼雜湊；必須用 `_hash_password_pbkdf2()`
- **不得**在取件碼或照片端點跳過速率限制（`_check_code_rate_limit`）
- **不得**在不驗證路徑的情況下讀取或刪除用戶端提供的 filename
- **不得**在 WebSocket endpoint 跳過 Session 驗證
- **不得**在 HTML 模板中直接插入未驗證的用戶輸入（使用 `.strip().upper()` 過濾後的取件碼除外，且只有在查表成功後才插入）
- **不得**在 `main.py` 中定義新的魔法數字或字串常數 — 必須加到 `config.py`

---

## 常見工作模式

### 新增管理員功能
```python
# 1. 若需要新的 request body，在 Pydantic 模型區塊加 BaseModel
class MyRequest(BaseModel):
    field: str

# 2. 路由加 auth 驗證
@app.post(f"{API_ADMIN_PREFIX}/my-endpoint", tags=["MyTag"])
async def my_endpoint(request: MyRequest, pb_session: Optional[str] = Cookie(default=None)) -> Dict[str, str]:
    _require_auth(pb_session)
    # ... 業務邏輯
    return {"message": "成功"}
```

### 新增公開端點（含速率限制）
```python
@app.get("/api/public-thing/{code}", tags=["Public"])
async def public_thing(code: str, request: Request) -> ...:
    if not _check_code_rate_limit(_get_client_ip(request)):
        raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試")
    # ...
```

### 修改密碼雜湊
`auth.py` 的 `_hash_password_pbkdf2()` 是唯一的雜湊實作。`_verify_password()` 處理新舊格式的向下相容。新增帳號或修改密碼時，只能呼叫 `_hash_password_pbkdf2()`，並確保帳號 dict 有 `"algo": "pbkdf2"` 欄位。

---

## 前端修改

`templates/` 下的 HTML 是純靜態檔案，Tailwind 和 Axios 從 CDN 載入。沒有建置流程，直接編輯 HTML 即可。

修改前端後，若伺服器已啟動，需設 `RELOAD_ADMIN_HTML=true` 或重啟伺服器（預設會快取 HTML）。

---

## 不需要做的事

- **不需要** migrations — 沒有資料庫，所有資料存在 JSON 文件
- **不需要** 安裝 bcrypt / argon2 — 已用 Python 內建 `hashlib.pbkdf2_hmac`
- **不需要** 前端建置工具 — Tailwind 透過 CDN 載入
- **不需要** Docker — 設計為 Windows 單機直接執行
