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
    ├── index.html   ← 公開首頁（Hero + Gallery 雙區塊 scroll-snap）
    ├── admin.html   ← 管理後台
    ├── login.html
    └── download.html
```

`storage/` 目錄由程式自動建立，不應納入版本控制（`accounts.json` 含密碼雜湊，`line_config.json` 含 API Token）。

**縮圖快取命名規則：**
- 管理端縮圖：`storage/thumbs/{filename}.thumb.webp`（含原始檔名）
- 公開縮圖（含浮水印）：`storage/thumbs/pub_{md5(filename)}.webp`（hash 命名，避免中文/特殊字元相容問題）

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

**讀取圖片時必須用 BytesIO**，不得直接傳路徑給 `Image.open()`，避免中文/Unicode 路徑在部分 Windows 環境下的相容問題：
```python
img = Image.open(io.BytesIO(src_path.read_bytes()))
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
| 2026-06-02 | 改密碼改用 Modal + `type="password"` | 原 `prompt()` 以明碼顯示密碼輸入；改為頁內 Modal，提供密碼遮罩、確認欄位與前端驗證 |
| 2026-06-03 | 深/淺色模式用 CSS variables + `data-theme` | 無建置工具環境下最輕量；不依賴 Tailwind dark class purge；全域狀態一個 attribute 搞定 |
| 2026-06-03 | i18n 用純 JS TRANSLATIONS 物件 | 不引入外部函式庫，維持零建置工具原則；管理頁面文字量不大，物件方案已足夠 |
| 2026-06-03 | login.html / download.html 移除 Tailwind CDN | 這兩頁邏輯極簡，Tailwind CDN 的額外 JS runtime 不值得；改用純 CSS 同時統一到 frame-corner / vert-label / wa-input 視覺語言 |
| 2026-06-03 | Gallery 公開照片用 Canvas 渲染而非 `<img>` | `<img src="...">` 在 DOM 暴露圖片 URL，右鍵另存或開發者工具 Elements tab 即可取得；Canvas 不暴露來源 URL，配合 blob URL 立即撤銷（`revokeObjectURL`）讓圖片無法被追蹤 |
| 2026-06-03 | 公開縮圖加 Server-side 浮水印 | DevTools Network tab 無法被前端 JS 阻擋；加浮水印讓即使技術用戶從 Network tab 下載的也只是低解析度的浮水印版本，降低直接可用性 |
| 2026-06-03 | 公開縮圖快取改用 MD5 hash 命名 | `THUMB_DIR / f"{filename}.pub.webp"` 當 filename 為中文時，Windows 的 `Path.exists()` 可能回傳不一致結果；改以 `pub_{md5(filename)}.webp` 確保快取路徑永遠是 ASCII，消除 Unicode 路徑相容問題 |
| 2026-06-03 | Pillow 讀圖改用 BytesIO | `Image.open(unicode_path)` 在部分 Windows 環境（特別是中文路徑）不穩定；改用 `Image.open(io.BytesIO(path.read_bytes()))` 讓 Pillow 只處理 bytes，路徑讀取交給 Python pathlib |
| 2026-06-03 | Gallery 相片卡片進場動畫：opacity 用 `@keyframes`，transform 用 `transition` | 若對同一屬性同時套用 animation fill-mode 與 hover transition，animation 層疊優先級較高，hover 的 transition 會被覆蓋；將 opacity（revealFade animation）與 transform（CSS transition）分屬不同機制，消除衝突：scale 0.96→1 由 transition 負責，opacity 0→1 由 animation 負責，hover 的 scale+translateY 仍可正常 transition |
| 2026-06-03 | 刪除/清除照片時同步清除兩種縮圖快取 | `delete_incoming` 和 `clear_incoming` 原本只刪除管理端縮圖（`{filename}.thumb.webp`），遺漏公開縮圖（`pub_{md5}.webp`），導致 `storage/thumbs/` 累積孤兒快取；修正後呼叫 `_pub_thumb_path(filename)` 一併刪除 |
| 2026-06-03 | `list_incoming` / `get_gallery_list` 的 `stat()` 改為逐項 try/except | 兩個函數原先用 list comprehension 呼叫 `p.stat().st_mtime`，若另一請求在 `iterdir()` 與 `stat()` 之間刪除該檔案，會拋出 `FileNotFoundError` 使整個 API 500；改為逐項 try/except 跳過消失的檔案 |
| 2026-06-03 | `photo_download_page` 改用 `_get_html()` 快取讀取 `download.html` | 原先每次取件頁面請求都直接 `read_text()` 讀磁碟，未使用與其他頁面一致的記憶體快取；改用 `_get_html("download.html")` 後首次後快取在記憶體，後續請求不再觸碰磁碟 |
| 2026-06-03 | `_wm_font()` 新增 `msyh.ttc`（微軟正黑體）與 `simsun.ttc`（新細明體）備援 | 原先只嘗試 meiryo（需日文語言支援）與 msgothic；若未安裝日文語言包，浮水印中文字符渲染失敗（顯示方塊）；加入更常見的繁/簡中文字型優先順序 |
| 2026-06-03 | `_session_cleanup_task` 每小時順帶清理 `_code_request_log` 中的孤兒 IP 鍵 | IP 速率限制 dict 的值（timestamp list）會被清空，但鍵本身（IP 字串）永不移除，造成緩慢的記憶體增長；每小時清理一次所有 window 內無有效記錄的 IP 鍵 |

---

## 安全性規則（禁止違反）

- **不得**使用 SHA-256 / MD5 / SHA-1 做密碼雜湊；必須用 `_hash_password_pbkdf2()`
- **不得**在取件碼或照片端點跳過速率限制（`_check_code_rate_limit`）
- **不得**在不驗證路徑的情況下讀取或刪除用戶端提供的 filename
- **不得**在 WebSocket endpoint 跳過 Session 驗證
- **不得**在 HTML 模板中直接插入未驗證的用戶輸入（使用 `.strip().upper()` 過濾後的取件碼除外，且只有在查表成功後才插入）
- **不得**在 `main.py` 中定義新的魔法數字或字串常數 — 必須加到 `config.py`
- **不得**在公開 Gallery 端點改回 `<img src="...">` 渲染 — 必須維持 Canvas + blob URL 模式
- **不得**對公開縮圖端點（`/api/gallery/thumb/{filename}`）加上 Auth 保護後省略浮水印 — 浮水印是防止 DevTools 直接取圖的最後防線
- **不得**直接傳 `Path` 物件給 `Image.open()` — 必須改用 `io.BytesIO(path.read_bytes())`

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

## 深/淺色模式

**admin.html：已完整實作** | login.html / download.html / index.html：尚未擴展

### 設計決策
- CSS 自訂屬性（variables）方案：在 `:root` 定義 `--wa-cream`、`--wa-gray`、`--wa-light`、`--bg-card`、`--bg-input`、`--border`、`--text-main`、`--shadow-sm` 等 token；深色模式套用 `[data-theme="dark"]` selector 覆寫
- 偏好以 `localStorage.getItem('pb-theme')` 持久化（`"light"` / `"dark"`，預設 `"light"`）
- `html` 元素加 `data-theme="light"` 初始屬性；JS 啟動時讀 localStorage 覆寫

### 規則
- 切換按鈕（`.btn-icon`）放在 admin header 右上角，登出按鈕左側
- 不引入額外函式庫；`document.documentElement.setAttribute('data-theme', theme)` 套用
- Tailwind CDN 版本設定 `darkMode: 'class'`，但實際顏色全部走 CSS variables，Tailwind 只負責 layout utilities

### 擴展到其他頁面
複製 `:root` / `[data-theme="dark"]` token block 與 `toggleTheme()` 函數到目標頁面即可。login / download 目前無需 dark mode。

---

## 多語系 i18n

**admin.html：已完整實作** | login.html / download.html / index.html：尚未擴展

### 設計決策
- 純 JS 方案：在 HTML `<script>` 中定義 `const TRANSLATIONS = { 'zh-TW': {...}, 'en': {...} }`
- 以 `data-i18n="key"` 屬性標記需翻譯的靜態元素；`t(key)` 函數取值，`setLang(lang)` 統一刷新
- 語言偏好存 `localStorage.getItem('pb-lang')`（`"zh-TW"` / `"en"`，預設 `"zh-TW"`）
- 支援語言：**正體中文（zh-TW）** 和 **英文（en）**
- 語言切換按鈕（`.btn-icon`）放在 admin header，深/淺色切換旁

### 規則
- 翻譯物件在各 HTML 的 `<script>` 區塊，不用外部 JSON 或 i18n 函式庫
- 動態產生的 DOM（renderIncomingCard、renderAccounts 等）需在產生時呼叫 `t(key)` 取當前語系字串
- `config.py` 不需改動（後端 message 字串語言由前端決定是否顯示）

---

## 前端視覺語言（共用設計元素）

以下元件在 admin / login / download 頁面保持一致，新增頁面或修改前端時應遵循：

| 元件 | 說明 |
|------|------|
| `.frame-corner` | 四個角的裝飾線框；`position: absolute`，用 `::before` / `::after` 繪製 L 型 |
| `.vert-label` | 垂直排列的裝飾文字；`writing-mode: vertical-rl`，字重 300，低對比 |
| Noto Sans JP | 字重引入 100 / 200 / 300 / 400；標題用 100，一般文字用 300 |
| `fadeUp` animation | `.anim .d1`–`.d5` 依序延遲淡入；admin 各區塊使用 |
| 色調 | `#b8c5d6`（wa-blue）為主強調色；主文字 `#2b2b2b`；背景 `#f5f5f0` |

---

## 不需要做的事

- **不需要** migrations — 沒有資料庫，所有資料存在 JSON 文件
- **不需要** 安裝 bcrypt / argon2 — 已用 Python 內建 `hashlib.pbkdf2_hmac`
- **不需要** 前端建置工具 — Tailwind 透過 CDN 載入
- **不需要** Docker — 設計為 Windows 單機直接執行
- **不需要** i18n 函式庫（i18next 等）— 純 JS 翻譯物件即可
