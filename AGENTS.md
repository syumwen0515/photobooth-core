# AGENTS.md — AI 代理開發指引

本文件供 AI 代理（Claude Code 等）在此專案工作時參考。說明如何執行專案、程式碼慣例、架構決策，以及禁止事項。

---

## 技術棧

| 層次 | 技術 |
|------|------|
| Runtime | Python 3.14（Linux 系統 Python；Windows 可使用內嵌 Python）|
| Web 框架 | FastAPI + Uvicorn |
| 即時通訊 | WebSocket（FastAPI 原生）|
| 檔案監聽 | Watchdog |
| 圖片處理 | Pillow + numpy（Pillow 操作必須用 `run_in_executor` 非同步化；numpy 僅用於模板透明槽位偵測）|
| 外網穿透 | pyngrok |
| LINE 整合 | line-bot-sdk v3 |
| 前端 | 純 HTML + Axios CDN（無建置工具）；`admin.html` 使用 Tailwind CDN，其餘頁面已移除 |

---

## 執行專案

```bash
# Linux — 首次執行會建立 .venv 並安裝依賴
cd /path/to/photobooth-core
./start.sh

# Linux 開發模式（自動重載 + 開放 API 文件）
source .venv/bin/activate
cd backend
ENABLE_API_DOCS=true RELOAD_ADMIN_HTML=true python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```powershell
# Windows — 使用內嵌 Python
cd backend
..\python\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 開發模式（自動重載 + 開放 API 文件）
$env:ENABLE_API_DOCS="true"; $env:RELOAD_ADMIN_HTML="true"
..\python\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生產部署（敏感 Token 透過環境變數注入，不落盤）
$env:SECURE_COOKIES="true"
$env:NGROK_AUTHTOKEN="your_ngrok_token"
$env:LINE_CHANNEL_SECRET="your_line_secret"
$env:LINE_CHANNEL_ACCESS_TOKEN="your_line_token"
..\python\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`start.sh` / `start.bat` 以 `PORT` 環境變數指定監聽埠（預設 8000）。回歸測試位於 `backend/tests/`，於 `backend/` 下執行 `python -m pytest -q tests`。

語法檢查（不執行應用，只做靜態分析）：
```bash
python -c "import ast; ast.parse(open('app/main.py', encoding='utf-8').read()); print('OK')"
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
├── services/        ← 同步 CPU 工作（由路由以 run_in_executor 呼叫）
│   ├── template_service.py   ← 模板 Alpha 透明槽位偵測
│   └── composite_service.py  ← 照片裁切、貼槽位、模板疊合、JPEG 輸出
├── ngrok_manager.py ← pyngrok 隧道生命週期
└── templates/       ← 純靜態 HTML，啟動時載入並快取於記憶體
    ├── app.html     ← 客戶自拍頁（/app）
    ├── index.html   ← 公開首頁（Hero + Gallery 雙區塊 scroll-snap）
    ├── admin.html   ← 管理後台
    ├── login.html
    └── download.html
```

`storage/` 目錄由程式自動建立，不應納入版本控制（`accounts.json` 含密碼雜湊，`line_config.json` 含 API Token）。

**縮圖快取命名規則：**
- 管理端縮圖：`storage/thumbs/{filename}.thumb.webp`（含原始檔名）
- 公開縮圖（含浮水印）：`storage/thumbs/pub_{md5(filename)}.webp`（hash 命名，避免中文/特殊字元相容問題）

**Gallery 設定：**
- `storage/gallery_config.json` — `{"enabled": true, "watermark_text": "..."}` （預設值定義在 `config.py` 的 `GALLERY_CONFIG_DEFAULTS`）
- 浮水印文字變更時，呼叫 `_invalidate_public_thumbs()` 刪除所有 `pub_*.webp`；啟動時 `_sync_wm_font_cache()` 比對 `THUMB_DIR/wm_font.marker`，浮水印字型改變也會清快取；`/api/gallery` 回應帶 `wm_version`（`md5(浮水印文字|字型路徑)` 前 8 碼），前端縮圖 URL 帶 `?v={wm_version}` 使瀏覽器快取同步失效

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
| 2026-11-11 | `admin` 為最高管理者（`config.py::SUPER_ADMIN_USERNAME`）；改密碼僅限本人，刪帳號僅 admin；改自己密碼後前端跳轉 `/login`，後台 axios 401 攔截器導向登入 | 原本任一管理者可改/刪任何帳號；改密碼會銷毀該帳號 session，前端未跳轉導致後續請求 401 才發現；`/api/admin/accounts` 回傳 `current` / `super_admin` 供前端隱藏無權限按鈕，後端仍為權限判斷依據 |
| 2026-11-13 | 合成功能以「選用」形式回歸（部分推翻 2026-06-02 移除 compositor）：模板上傳 + Alpha 槽位偵測 + 客戶自拍頁 `/app` + `/api/v1/customer/*` | 客戶需要自拍並套用版型。破壞性最小設計：**未上傳模板且未開啟 `selfie_config.json` 的 `enabled` 時行為與原本完全相同**；合成結果寫入 `incoming/` 並走既有取件碼、Gallery、縮圖、`protect_static_incoming`，**不新增 `/static/exports`、`/static/qr` 公開路徑**（會繞過取件碼）；偵測用 Pillow + numpy 逐列連續區段 union-find（不引入 OpenCV）；後台沿用 `/api/admin`，僅客戶公開端點使用 `/api/v1/customer`；LINE 沿用「輸入取件碼」流程，**不接受客戶端傳入 LINE userId、不新增 push**；公開端點須通過活動開關、`_check_selfie_rate_limit`（IP 維度）、單張 12 MB / 50M 像素上限、`_composite_semaphore` 併發上限；模板 id 由伺服器產生（`tpl_` + 12 hex），路徑經 regex + `relative_to` 驗證；相機控制與列印不在此階段 |
| 2026-11-13 | 合成採「等比例放大填滿槽位、置中裁切」（`ImageOps.fit`），不留白、不變形；`/app` 相簿上傳不在瀏覽器端裁切 | 客戶要求照片直接符合框架；曾試過 `ImageOps.contain`（完整放入、留白）但被否決；相簿照片只在瀏覽器端縮到最長邊 1600px，裁切統一由伺服器處理，避免相機與相簿兩條路徑結果不一致、也避免二次裁切 |
| 2026-11-13 | 模板支援左右對稱 `mirror_rows`：同一列（垂直重疊超過一半）的槽位共用一張照片；上傳時若每列恰好 2 槽位則自動啟用，後台可勾選/取消 | 客戶版型為左右對稱（4 列 × 2 = 8 槽放 4 張）；`template_service.photo_groups()` 是「需要幾張照片」的唯一依據，`/api/v1/customer/templates` 只回傳每組的代表槽位，`customer_composite` 驗證照片數須等於組數；舊模板無此欄位視為 false，行為不變 |
| 2026-11-13 | 後台可刪除誤判槽位（確認後立即儲存，至少保留 1 個）；`/app` 新增「從相簿選取照片」（可多選，依序補滿槽位）；相機被拒絕時仍可用相簿 | 偵測可能誤判；使用者不一定能用相機；HTTPS 檢查失敗（非安全環境）時仍整頁顯示提示，不提供相簿上傳 |
| 2026-11-14 | 新增選用「列印」（部分推翻 2026-06-02 移除 printer）：`print_config.json`（預設關閉）、`print_service.py`、`GET/POST /api/admin/print-settings`、`POST /api/admin/print/{filename}` | 店內需要直接列印；僅管理員、僅本機連線（避免經 ngrok 遠端觸發）、需啟用；Windows 用 `os.startfile(..., "print")`（指定印表機則 `mspaint /pt`），其他系統用 `lp`；失敗回 500 不影響其他功能；Windows 實機行為待現場驗證 |
| 2026-11-14 | 後台「相機拍照」採 USB 網路攝影機模式（Sony USB Streaming / Imaging Edge Webcam、Canon EOS Webcam Utility），以瀏覽器 `getUserMedia` 擷取並推入既有上傳佇列；`/admin` 的 `Permissions-Policy` 同為 `camera=(self)` | digiCamControl 對 Sony 僅支援舊 Wi-Fi API；不引入相機 SDK、後端零新依賴；解析度受 UVC 限制；需 localhost 或 HTTPS；`/admin` 需登入，故放寬僅限已驗證頁面 |
| 2026-11-14 | 槽位偵測過濾邊緣透明區 | 模板外圍透明留白會被誤判為槽位；若透明區碰到影像邊緣且存在內部透明區則捨棄，全部皆碰邊（滿版槽位）則保留；取捨：混合版型中刻意貼邊的槽位會被丟棄，需調整模板 |
| 2026-11-13 | `/app` 路徑的 `Permissions-Policy` 為 `camera=(self)`，其餘路徑維持 `camera=()` | `getUserMedia` 需要相機權限，原全站 `camera=()` 會直接封鎖；僅對 `SELFIE_PAGE_ROUTE` 放寬到同源，其餘頁面不變；CSP 未改動（`/app` 與其他公開頁一樣 `style-src` nonce-only） |
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
| 2026-11-10 | 浮水印字型變更自動使公開縮圖快取失效（`_sync_wm_font_cache()` + `wm_version` 含字型） | 安裝 CJK 字型後，舊的方塊版 `pub_*.webp` 仍留在快取；後台重存「相同」浮水印文字不會觸發 `_invalidate_public_thumbs()`（僅文字變更才清），所以純中文一直顯示舊圖，加一個數字（文字改變）才重新產生；啟動時比對 `THUMB_DIR/wm_font.marker` 記錄的字型路徑，不同則清快取；`wm_version` 改為 `md5(文字\|字型路徑)`，使瀏覽器 24 小時快取一併失效 |
| 2026-11-10 | `_wm_font()` 字型清單移至 `config.py::WM_FONT_CANDIDATES`，新增 Linux CJK 字型與 `fc-match` 備援 | Linux 上原清單只剩 DejaVu / Liberation（無 CJK 字形），Windows 路徑不存在，繁中浮水印顯示方塊；清單改為 Windows → Noto Sans CJK → WenQuanYi → Droid Fallback → macOS → 拉丁字型，並以 `fc-match :lang=zh-tw` 補足；結果以 `lru_cache` 快取；Linux 需安裝 `fonts-noto-cjk` 或 `fonts-wqy-zenhei`；更換字型後須重存浮水印文字以觸發 `_invalidate_public_thumbs()` |
| 2026-11-12 | ngrok 支援自訂網域（`NGROK_DOMAIN` / 後台「自訂網域」→ `ngrok_config.json` 的 `domain`；`POST /api/admin/ngrok/domain`） | 原 `ngrok.connect(port, "http")` 未帶 `domain`，訂閱用戶只能使用隨機免費網域；`ngrok_manager.normalize_domain()` 驗證並去除協定／路徑，`start_tunnel(..., domain=)` 有值才傳給 pyngrok；環境變數優先序高於 JSON，與 token 一致；token 與 domain 共用同一設定檔，儲存任一項須先讀取再合併（`_read_ngrok_config`），不可覆蓋另一欄位 |
| 2026-06-03 | `_session_cleanup_task` 每小時順帶清理 `_code_request_log` 中的孤兒 IP 鍵 | IP 速率限制 dict 的值（timestamp list）會被清空，但鍵本身（IP 字串）永不移除，造成緩慢的記憶體增長；每小時清理一次所有 window 內無有效記錄的 IP 鍵 |
| 2026-06-03 | Login form 加 `method="post" action="/api/auth/login"`（CWE-598）| 表單未設 method 屬性時預設為 GET；若 JS 停用，帳號密碼會出現在 URL query string，被 server log / browser history 記錄；加上 method/action 確保即使 JS 停用也走 POST |
| 2026-06-03 | CSP header 全面強化 | 原 CSP 只設 3 條（frame-ancestors / object-src / base-uri），ZAP 掃出 4 個 Medium 警告：未定義 form-action（無 fallback）、script-src / style-src / 其他資源指令未設（等同允許所有來源）；補上 default-src / script-src / style-src / font-src / img-src / connect-src / form-action |
| 2026-06-03 | Axios CDN 加 SRI（Subresource Integrity）+ 固定版本 | 直接載入 `npm/axios/dist/axios.min.js` 無版本鎖定，CDN 若被汙染可注入任意 JS；改為 `axios@1.16.1` 並加 `integrity="sha384-..."` + `crossorigin="anonymous"`，瀏覽器驗證 hash 失敗時拒絕執行 |
| 2026-06-03 | Gallery 設定存入 `gallery_config.json`，不拆散到 `index_text.json` | Gallery 啟用狀態與浮水印文字與首頁文字是不同的功能域；分開檔案讓 reset 時可精確選擇是否清除 gallery 設定 |
| 2026-06-03 | 浮水印文字變更後呼叫 `_invalidate_public_thumbs()` 清空快取 | 浮水印已 bake 進縮圖 WebP；若不清快取，舊浮水印文字繼續顯示直到永遠（`max-age=86400` 且快取命名只用 filename hash）；強制清除確保下次請求立即重新生成 |
| 2026-06-03 | `/api/gallery` 加入 `enabled` 欄位；index.html 頁面載入時先 fetch 一次 | 原本 gallery lazy-load 在 scroll 25% 時才觸發；disabled 時 scroll-hint 仍可見，誘導用戶嘗試捲動；提早在 `DOMContentLoaded` 後立即 fetch，disabled 則同步隱藏 scroll-hint 與 gallery-section |
| 2026-06-03 | 縮圖 URL 帶 `?v={wm_version}` query 使瀏覽器快取失效 | 公開縮圖帶 `Cache-Control: private, max-age=86400`；伺服器端刪除舊快取後，瀏覽器仍會使用已快取的回應長達 24 小時；`wm_version` 是浮水印文字的 MD5 前 8 碼，浮水印一改 URL 就變，瀏覽器視為新資源強制重新 fetch，無需修改 Cache-Control 設定 |
| 2026-06-03 | `_verify_password()` 改用 `hmac.compare_digest()` | 字串 `==` 比較是 short-circuit，長度或前段不同時提前返回，造成 timing side channel；`hmac.compare_digest` 保證恆定時間比較，消除此攻擊面（CWE-697）；即使 PBKDF2 計算時間已主導整體延遲，此變更代價為零，無理由不採用 |
| 2026-06-03 | `delete_bg` / `delete_font` 改用 try-except 而非先 exists() 再 unlink() | 先檢查 exists() 再 unlink() 是 TOCTOU 競態（CWE-367）：另一請求可能在兩者之間刪除該檔案，使 unlink 拋出 `FileNotFoundError`；改為直接 unlink 並捕捉 `FileNotFoundError` 才是原子操作的正確寫法；`webp_path.unlink(missing_ok=True)` 同理消除伴生 WebP 的競態 |
| 2026-06-03 | LINE API 呼叫設定 10 秒 timeout | `MessagingApi.reply_message` 若 LINE 伺服器無回應，預設無 timeout 會讓 worker 永久掛起；10 秒已足夠正常回應，逾時後由 SDK 拋出例外，不影響主事件迴圈（因為 `_handle_text` 不在 async context 中直接等待） |
| 2026-06-04 | 管理員上傳照片用 timestamp 前綴命名 | 上傳檔名可能含中文/空格等不安全字元；以 `{timestamp_ms}_{sanitized_stem}{ext}` 產生安全檔名，並在碰撞時遞增 suffix；比完全隨機 UUID 更容易在磁碟上依時間排序、除錯 |
| 2026-06-04 | `prependIncomingCard` 加冪等檢查 | 上傳端點廣播 WebSocket 後，Watchdog 在 0.5 秒後也會觸發相同廣播；若不檢查，同一張照片會被插入兩次；加上 `getElementById` 存在檢查，第二次廣播直接 return，不重複插卡 |
| 2026-06-04 | 上傳進度用右下角懸浮視窗 + 全域佇列 2 線程並發 | 單次多檔選取後拆成獨立請求依序送出；`_drainUploadQueue` 以最多 2 個 async worker 消化全域 `_uploadQueue` 佇列；後端端點改為單檔（`UploadFile`）接收，讓每個請求都有獨立的 `onUploadProgress` 回調，進度條才能逐檔即時更新；懸浮面板（`#uploadFloatPanel`）固定在右下角，列出每張照片的個別進度條、完成打勾（綠）/ 失敗打叉（紅）；3 秒後所有項目完成則自動關閉，✕ 按鈕可手動關閉 |
| 2026-06-04 | 上傳改用全域佇列；第二次點擊繼續排隊不另開 pool | **舊做法**：`uploadIncomingPhotos` 每次呼叫都 `_runUploadPool(tasks, 4)` 建立全新的 4-worker pool，第二次點擊時與第一批平行跑，互不等待。**新做法**：`_uploadQueue` 是全域陣列，所有批次共享；`uploadIncomingPhotos` 只做 push + 呼叫 `_drainUploadQueue()`；`_drainUploadQueue` 用 `_uploadActiveCount` 計數，已有 2 個進行中時直接 return，新項目靜靜排在佇列等待現有 worker 完成後自動提取；消除了多批次並行導致的連線數爆增，也讓第二次點擊的行為符合直覺（繼續排隊）|
| 2026-06-04 | 上傳取消用 `AbortController` + `_cancelledUids` Set | X 按鈕呼叫 `_onUploadPanelClose()`；若有 `.upload-bar-active` 項目則出現 `confirm` 提示；確認後呼叫 `_cancelAllUploads()`：(1) `_uploadQueue.splice(0)` 清空等待佇列，(2) 查詢所有 `upload-bar-active` 元素，UIDs 加入 `_cancelledUids` 並視覺標記為灰色 `—`，(3) 中止 `_uploadControllers` 中所有 AbortController；`_uploadSingleFile` 在發出請求前先檢查 `_cancelledUids`，已取消則直接 return；axios abort 拋出 `ERR_CANCELED`，`_uploadOneSafe` 的 catch block 判斷後不呼叫 `_setUploadError`（避免覆蓋取消狀態） |
| 2026-06-04 | `_cancelledUids.clear()` 必須在所有 worker 跑完後才能執行 | **Bug**：`closeUploadPanel()` 原本含 `_cancelledUids.clear()`，導致剛標記的取消 UIDs 立刻被清空；worker 再去檢查 `_cancelledUids.has(uid)` 時得到 false，排隊中的請求全部繼續發送。**Fix**：`_cancelledUids.clear()` 移至 `_scheduleUploadAutoClose()` 計時器回調內（`!upload-bar-active` 確認所有 worker 完全跑完後才清空），`closeUploadPanel()` 本身不再碰這個 Set |
| 2026-06-04 | 有失敗項目時不自動關閉懸浮上傳面板 | **Bug**：`_scheduleUploadAutoClose()` 只檢查 `.upload-bar-active`（進行中），所有上傳結束後（無論成功或失敗）3 秒必然自動關閉，失敗項目在用戶來不及注意時就消失，導致漏傳照片。**Fix**：`_setUploadError` 在 item div 加上 `data-upload-failed="1"` 屬性；`_scheduleUploadAutoClose` 同時檢查 `[data-upload-failed]`，有任何未處理的失敗時不關閉；用戶按下重傳按鈕（`_retryUpload`）後移除該屬性；手動按 ✕ 仍可強制關閉 |
| 2026-06-04 | 取件碼改用 `secrets.choice()` 而非 `random.choices()` | `random` 模組使用梅森旋轉演算法，不具密碼學安全性；攻擊者若能觀測足夠多的碼值，可還原內部狀態並預測後續碼；取件碼是照片存取的唯一憑證，必須用 Python 內建 `secrets.choice()` 確保 CSPRNG；`import random` 已移除，`import secrets` 已加入，`_generate_code()` 改為 `"".join(secrets.choice(_CODE_CHARS) for _ in range(length))` |
| 2026-06-04 | LINE 設定新增環境變數優先序（`LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN`） | ngrok token 已支援 `NGROK_AUTHTOKEN` env var 覆蓋，但 LINE 憑證只能存 JSON 明文；展場部署時 token 一旦落盤即在 `storage/` 下明文可見；`_load_line_config()` 改為先讀 `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` 環境變數，有設定時直接回傳且不讀檔，fallback 至 JSON；與 ngrok 的設計模式對齊 |
| 2026-06-04 | `_load_gallery_config()` 加 write-through 記憶體快取 | 公開 `/api/gallery` 是熱點端點（每次訪客進頁面或 Gallery 捲動觸發都呼叫），原始實作每次都做 JSON 磁碟讀取；加 `_gallery_config_cache` 模組級變數，`_load_gallery_config()` 命中快取則直接回傳 `dict(cache)`，miss 時讀磁碟並填充快取；`_save_gallery_config()` 寫入後同步更新快取（write-through），確保快取永遠與磁碟一致；`_invalidate_public_thumbs()` 不需額外清快取，因為總是在 `_save_gallery_config()` 之後呼叫 |
| 2026-06-04 | `/static/incoming/` 受 `protect_static_incoming` middleware 保護 | 攻擊者可 GET `/api/gallery` 取得所有照片 filename，再直接 GET `/static/incoming/{filename}` 繞過取件碼取得全解析度原圖（浮水印保護完全失效）；middleware 在 auth 失敗時回傳 401，管理員 session 正常通過，不影響後台功能 |
| 2026-06-04 | 登入端點新增 IP 維度速率限制（`_check_login_rate_limit`） | 帳號維度鎖定（5 次 / 10 分鐘）可被「帳號噴灑攻擊」規避（每帳號各試 4 次，無限輪流）；IP 維度限制（預設 10 次 / 分鐘，`LOGIN_RATE_LIMIT` 環境變數可調整）為補充防線；記錄在 `_login_request_log` 並隨 `_session_cleanup_task` 每小時清理孤兒鍵 |
| 2026-06-04 | `_get_client_ip()` 改為僅在 `TRUSTED_PROXY_IPS` 命中時才信任 `X-Forwarded-For` | 原實作無條件信任 `X-Forwarded-For`；攻擊者設定任意假 IP 標頭即可規避取件碼與登入的所有速率限制；改為「信任白名單代理 IP」模式，與業界 nginx / haproxy 搭配的標準做法對齊；獨立部署（無反向代理）則完全不信任 |
| 2026-06-04 | `open_incoming_folder()` 改用 `request.client.host` 做本機判斷 | 原本以 `Host` header 檢查是否為 localhost；`Host` header 是 HTTP 層欄位，用戶端可偽造；透過 ngrok 的外部請求可設 `Host: localhost` 繞過判斷，觸發 `explorer.exe` 開啟資料夾（雖需 admin auth，但資訊洩漏風險）；改用 TCP 連線遠端 IP（`request.client.host`）才能真正確認是本機連線 |
| 2026-06-04 | `download.html` 照片改用 Canvas 渲染；下載按鈕改為 Web Share API 優先；顯示改用縮圖；下載進度條 | 原 `<img src="/api/photo/{code}">` 在 DOM 暴露圖片 URL，右鍵即可另存；改用 Canvas + blob URL（同 Gallery 做法）避免 URL 暴露。**顯示效率**：Canvas 載入 `/api/photo/{code}/thumb`（480px WebP 縮圖，重用 `{filename}.thumb.webp` 快取，無浮水印）；下載時才 fetch 全尺寸原圖。**下載邏輯**：`_fetchWithProgress()` 以 `ReadableStream` reader 逐塊讀取回應並回報進度；有 `Content-Length` 時顯示 `0%→100%` 百分比進度條，無 `Content-Length` 時改為 `dlSweep` shimmer 動畫 + 已接收 bytes；下載完成後進度條短暫停留再淡出；**Web Share API 僅限觸控設備**（`window.matchMedia('(pointer: coarse)').matches`），桌機即使支援 `navigator.canShare` 也跳過，直接 blob URL 下載；AbortError 視為取消；行動裝置（`pointer: coarse`）且無 Web Share 時顯示 `.mobile-hint`。**照片顯示**：改用 `<img src="/api/photo/{code}/thumb">` 直接顯示縮圖（不用 canvas + blob URL）。Canvas 在 iOS Safari 有 `opacity: 0`（來自 `.anim`）與 `.loading` class 覆蓋 `fadeUp` animation 的衝突，導致元素永遠不可見；加上 iOS Safari 的 blob URL → canvas drawImage 不穩定。download 頁 `{code}` 本身即可見，img src 無額外洩漏。防儲存靠：CSS `-webkit-touch-callout: none`（iOS 長按選單）+ `pointer-events: none` + 覆蓋 overlay div + JS contextmenu/dragstart 攔截。body `overflow-x: hidden` 允許垂直捲動。`dl.loadError` 翻譯鍵供 img.onerror 顯示錯誤提示。**縮圖格式**：`/api/photo/{code}/thumb` 依 `Accept` header 自動選格式 — 含 `image/webp` 回 WebP（`.thumb.webp`），否則回 JPEG（`.thumb.jpg`）；iOS 13 等舊版瀏覽器不帶 `image/webp`，故自動降為 JPEG；`_generate_thumbnail` 加 `fmt` 參數（預設 `"WEBP"`，向下相容）；刪除/清除照片時兩種縮圖皆清除。**ngrok 攔截**：預覽圖改為 `fetch()` 載入（而非 `<img src="">` 直接載入），請求帶 `ngrok-skip-browser-warning: 1` header 繞過 ngrok free tier 的瀏覽器警告頁（不帶此 header 時 ngrok 對 `<img>` 子資源請求也可能回傳 HTML 警告頁，觸發 `img.onerror`）；同時帶 `Accept: image/webp,...` 或 `Accept: image/jpeg,...`（由 canvas.toDataURL 偵測 WebP 支援度決定）；`_fetchWithProgress` 也加上同樣的 header，確保下載按鈕在 ngrok 環境也能正常取得原圖 |
| 2026-06-04 | 字型上傳改為支援多選批次 | 使用者每次只能選一個字型檔上傳，多字型需重複操作；`upload_font` 後端改為 `files: List[UploadFile]`，逐檔驗證（格式 / 大小），全部成功才一次寫入 metadata，部分失敗時仍儲存成功的字型並以 `errors` 陣列回傳失敗清單；前端 `fontFile` input 加 `multiple` 屬性，`uploadFont()` 改用 `files.forEach(f => formData.append('files', f))` 打包；成功後顯示上傳數量，部分失敗時另以 `alert` 列出失敗檔名與原因 |
| 2026-06-04 | ngrok 重置、啟動驗證、Token 狀態提示；Gallery 快取重置；pyngrok in-memory 清理；重置後 Gallery UI 不同步 | **Bug 1（重置未清 ngrok）**：`reset_system()` 未清除 `ngrok_config.json` 也未停止隧道；**Fix**：重置最前面加「停止並清除 ngrok 設定」區塊，`stop_tunnel()` → 刪 `NGROK_CONFIG_FILE` → `conf.get_default().auth_token = None`（清 pyngrok in-memory）。**Bug 2（重啟後 Token 輸入框空白）**：`/api/admin/ngrok/status` 不含 token 是否存在的資訊，UI 無法顯示「已儲存」；**Fix**：`get_ngrok_status()` 新增 `has_token` 欄位；`applyNgrokUI()` 加第三參數，非活動狀態時顯示/隱藏 `#ngrokTokenSaved` 徽章；`loadNgrokStatus()` 傳入 `res.data.has_token`；reset handler 補呼叫 `loadNgrokStatus()`。**Bug 3（pyngrok 快取繞過重置）**：pyngrok 自有 token 快取（`~/.ngrok2/ngrok.yml`），重置後不需 token 即可啟動；**Fix 1（API 層）**：`start_ngrok()` 先驗證 `_load_ngrok_token() is not None`，None 則 400；**Fix 2（in-memory）**：重置時呼叫 `conf.get_default().auth_token = None` 清除當前進程的快取。**Bug 4（Gallery 快取未重置）**：`reset_system()` 完全未處理 `gallery_config.json`（未刪除），且即使刪了 `_gallery_config_cache` 仍持有舊資料，重置後 gallery 設定不變；`_invalidate_public_thumbs()` 也未呼叫導致舊浮水印縮圖仍被服務；**Fix**：重置加「重置 Gallery 設定」區塊，刪 `GALLERY_CONFIG_FILE` → `_gallery_config_cache = None` → `_invalidate_public_thumbs()`。**Bug 5（重置後 Gallery UI 不同步）**：`resetSystem()` JS handler 呼叫了 `loadIncoming`、`loadNgrokStatus`、`loadLineConfig` 等，但漏掉 `loadGallerySettings()`，導致 Gallery 區塊的浮水印文字等設定在 admin UI 仍顯示舊值，必須手動重新整理才能看到正確狀態；**Fix**：在 reset handler 的更新序列加入 `loadGallerySettings()` |
| 2026-06-04 | CSP `unsafe-inline` 移除：採用 Nonce 方案 | 備選方案「抽出 .js/.css 靜態檔」須新增 mount 且 JS 與 HTML 緊密耦合，維護負擔大；「靜態 CSP Hash」每次改 inline 內容都要重算 hash，與直接編輯 HTML 的開發流程衝突；Nonce 方案：`add_security_headers` middleware 在 `call_next` 之前生成 `secrets.token_urlsafe(16)` 存入 `request.state.csp_nonce`，路由層呼叫 `_apply_nonce(html, nonce)` 替換 `__CSP_NONCE__` 佔位符；4 個 HTML 模板的 `<script>`（無 src）與 `<style>` 標籤均已加 `nonce="__CSP_NONCE__"`；HTML cache 仍有效（快取含佔位符的模板，替換在記憶體進行，開銷遠小於磁碟 I/O） |
| 2026-06-04 | `style-src` 無法移除 `unsafe-inline`（Tailwind Play CDN 根本限制） | Tailwind Play CDN（`cdn.tailwindcss.com`）以 JavaScript 動態插入 `<style>` 元素，無法預先帶 nonce；CSP Level 2 規定：當 `style-src` 含 `nonce-*` 時 `unsafe-inline` 自動被忽略，因此 `style-src 'nonce-{nonce}' 'unsafe-inline'` 也不可行；`<meta property="csp-nonce">` 機制亦測試確認無效；唯一有效方案是 `style-src 'unsafe-inline'`（不含 nonce），Tailwind 動態 style 才能通過；CSS injection 危害遠低於 script injection，為可接受的設計決策 |
| 2026-06-04 | HTML 模板全面移除 inline event handler（attribute 形式），改用 `addEventListener` | inline event handler（`onclick="…"`、`onchange="…"` 等 attribute 形式）屬於「inline script」；在 `script-src` 含有 `nonce-*` 但不含 `unsafe-inline` 的 CSP Level 3 環境下，瀏覽器對這類 attribute event handler **一律封鎖**，且無法為其附加 nonce（nonce 只對 `<script>` 元素本體有效）；0.4.9 nonce 化完成後，所有頁面的互動按鈕功能全部靜默失效（無 console error，僅 handler 不執行）；修正方式：admin.html 22 個 handler 全部移至 `DOMContentLoaded` 的 `addEventListener` 呼叫，動態生成的重試按鈕改用 `data-uid` + 事件委派；index.html 1 個；login.html 的 hover 效果改為 CSS `:hover`；download.html 無 script，無需修改 |
| 2026-06-06 | Login form 移除 `method="post" action="/api/auth/login"`（ZAP Anti-CSRF — 撤銷 2026-06-03 決策）| ZAP 將此 form 標記為「缺少 Anti-CSRF Token」；登入動作從未依賴 HTML native submit — JS 以 `e.preventDefault()` 攔截，改用 `axios.post` 送出 `Content-Type: application/json`（非 simple request，瀏覽器自動做 CORS preflight），天然抵抗 CSRF；保留 `method/action` 屬性徒增表單端點暗示；移除後 ZAP Anti-CSRF finding 消失，且無需新增 server-side CSRF token |
| 2026-06-06 | `index.html` 移除 Tailwind Play CDN；公開頁面 `style-src` 改用 `nonce-{nonce}`；`/admin` 路徑保留 `'unsafe-inline'`（ZAP SRI / 跨域 JS / style-src unsafe-inline 警告）| `cdn.tailwindcss.com` 是 JIT 動態 CDN，每次回應內容不固定，SRI hash 無法計算（ZAP SRI finding）；同時被 ZAP 標記為跨域 JS 來源（cross-domain JS finding）；解法：從 `index.html` 完全移除 Tailwind CDN，所有 utility class 改寫為具名 CSS class 置入 `<style nonce>` 區塊；`admin.html` 保留 Tailwind CDN（後台頁，已驗證身分，遷移成本高）；**Tailwind Play CDN 執行時動態注入無 nonce 的 `<style>` 元素，CSP `style-src nonce` 會封鎖這些注入，導致所有 utility class 失效、layout 崩潰**；解法：`add_security_headers` middleware 根據 `request.url.path` 切換：`/admin` 路徑用 `'unsafe-inline'`（允許 Tailwind CDN 注入），其餘路徑用 `'nonce-{nonce}'`；4 個模板共 111 個 inline `style=""` attribute 全部轉換為具名 CSS class |
| 2026-06-06 | 動態 `@font-face` 注入改用預埋 `<style nonce>` + CSSOM 修改（`style-src nonce` 修補的必要手段）| `applyFont()` 原本以 `document.createElement('style')` 動態插入 `@font-face`；移除 `style-src 'unsafe-inline'` 後，動態建立的 `<style>` 元素無 nonce，被 CSP 封鎖；解法：HTML 預埋 `<style id="custom-font-style" nonce="__CSP_NONCE__">` 空元素，JS 改為 `document.getElementById('custom-font-style').textContent = "@font-face{...}"`（CSSOM `.textContent` 操作已通過 nonce 審核的元素，不觸發 CSP 重新驗證）；`element.style.property = value`（CSSOM API）亦不受 CSP style-src 管控，可安全使用 |

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
- **不得**縮減 `add_security_headers` 中的 CSP 指令 — 若需新增外部資源來源（CDN、字型服務），應將其加入對應指令白名單，而非移除限制
- **不得**移除 `axios@1.16.1` script tag 的 `integrity` 屬性，或將 CDN URL 改回無版本形式（`npm/axios/dist/axios.min.js`）；升級 axios 版本時必須同步更新 URL 和 hash
- **不得**在 login form 加回 `method="post"` 或 `action="..."` 屬性 — 登入以 `application/json` axios POST 提交，天然抵抗 CSRF；method/action 屬性增加攻擊面暗示（已於 2026-06-06 ZAP 修補中移除）
- **不得**在 `update_gallery_settings` 移除 `_invalidate_public_thumbs()` 呼叫 — 浮水印已 bake 進縮圖，不清快取舊浮水印永不消失
- **不得**在 `loadPhotoToCanvas` 移除 `?v={wm_version}` query — 這是唯一能繞過瀏覽器 24 小時快取使浮水印變更即時生效的機制
- **不得**在 `_verify_password()` 將 `hmac.compare_digest()` 改回 `==` 字串比較 — `==` 有 short-circuit timing side channel（CWE-697），`hmac.compare_digest` 是正確的恆定時間比較方式
- **不得**在 `delete_bg` / `delete_font` 中恢復先 `.exists()` 再 `.unlink()` 的模式 — 必須直接 `.unlink()` 並捕捉 `FileNotFoundError`，以消除 TOCTOU 競態（CWE-367）
- **不得**在 `upload_incoming` 中直接使用原始 `file.filename` 作為儲存路徑 — 必須先用 `re.sub(r'[^\w\-]', '', stem)` 清除非安全字元，並以 timestamp 前綴確保唯一性，才能寫入 `INCOMING_DIR`
- **不得**將 `upload_font` 端點改回接受單一 `UploadFile` — 已改為 `List[UploadFile]` 支援多字型批次上傳；前端 `fontFile` 的 `multiple` 屬性與 `uploadFont()` 中的 `files.forEach(f => formData.append('files', f))` 對應此行為；改回單檔會破壞多選功能
- **不得**將 `upload_incoming` 端點改回接受 `List[UploadFile]` — 並發由前端 `_drainUploadQueue` 的全域佇列控制，單檔端點才能讓每個 HTTP 請求有獨立的 `onUploadProgress` 回調；多檔合批上傳會導致進度條只能顯示整批進度
- **不得**將 `_generate_code()` 改回使用 `random.choices()` — `random` 為偽亂數，攻擊者可從足夠樣本推算後續碼值；必須使用 `secrets.choice()` 確保密碼學安全性（CSPRNG）
- **不得**在 `_load_gallery_config()` 移除快取機制 — 此函數是公開 `/api/gallery` 熱點路徑，快取消除了每次請求的磁碟 I/O；修改 gallery 設定時必須透過 `_save_gallery_config()` 寫入以同步更新快取，不可繞過直接寫檔
- **不得**移除 `protect_static_incoming` middleware — 此 middleware 是防止「/api/gallery 枚舉檔名 → /static/incoming/ 直接下載全解析度照片」攻擊鏈的關鍵；移除後攻擊者不需任何取件碼即可取得所有照片原檔
- **不得**在 `_get_client_ip()` 恢復無條件信任 `X-Forwarded-For` 的寫法 — 此 header 可被任何用戶端偽造；必須透過 `TRUSTED_PROXY_IPS` 環境變數明確設定可信代理後才信任；否則攻擊者可輪換假 IP 規避所有速率限制
- **不得**在 `login()` 端點移除 `_check_login_rate_limit(client_ip)` 呼叫 — 帳號維度的鎖定（`is_account_locked`）無法防止帳號噴灑攻擊（攻擊者輪流嘗試大量帳號各試 4 次，永遠不觸發鎖定）；IP 維度速率限制是必要的補充防線
- **不得**恢復 `admin/admin` 預設密碼 — 新安裝必須使用 `PB_INITIAL_ADMIN_PASSWORD`（至少 12 字元）或由 `secrets.token_urlsafe()` 產生一次性密碼；舊的 `admin/admin` 帳號在啟動時必須輪替
- **不得**在 `open_incoming_folder()` 恢復使用 `Host` header 做本機檢查 — `Host` header 是用戶端可控制的 HTTP 標頭；透過 ngrok 的請求可偽造 `Host: localhost` 通過檢查；必須改用 `request.client.host`（TCP 連線來源 IP）
- **不得**移除 `change_password` / `delete_account` 路由的權限檢查 — 改密碼僅限本人或 `SUPER_ADMIN_USERNAME`；刪帳號僅 `SUPER_ADMIN_USERNAME`，且該帳號不可被刪（`auth.delete_account` 亦拒絕）；僅隱藏前端按鈕不足以防護
- **不得**在 `script-src` 中重新加入 `'unsafe-inline'` — nonce 已替代 `unsafe-inline`，重新加入使 XSS 攻擊者可注入任意 script；`style-src` 的 `'unsafe-inline'` 僅允許存在於 `/admin` 路徑（Tailwind Play CDN 動態注入 `<style>` 的必要條件），**不得**擴展到 `/`、`/login`、`/download/` 等公開路徑
- **不得**在任何 HTML 模板中新增無 `nonce` 屬性的 `<script>` 標籤（無 `src`）— 缺少 nonce 的 inline script 會被 `script-src 'nonce-...'` 阻擋，造成 JS 功能中斷
- **不得**對 `_apply_nonce(html, nonce)` 傳入靜態或可預測的 nonce 字串 — nonce 必須來自 `request.state.csp_nonce`（每請求由 `secrets.token_urlsafe(16)` 生成），重用或可預測的 nonce 使 CSP nonce 保護失效
- **不得**在 HTML 模板中使用 attribute 形式的 inline event handler（`onclick="…"`、`onchange="…"`、`onmouseover="…"` 等）— CSP Level 3 `script-src 'nonce-*'` 會封鎖所有 attribute event handler（nonce 對 `<script>` 元素有效，對 HTML attribute 無效）；所有事件綁定必須在 `<script nonce="__CSP_NONCE__">` 區塊內以 `addEventListener` 完成；動態生成的元素（如重試按鈕）改用 `data-*` 屬性 + 事件委派（event delegation）
- **不得**將 `download.html` 下載按鈕改回 `<a href="/api/photo/{code}?dl=1">` — 需透過 JS handler（Web Share API 優先，fallback 為 blob URL）才能在支援 Web Share 的行動瀏覽器（iOS Safari 15+ / Android Chrome 86+）觸發分享選單，讓用戶直接存入相簿；改回 `<a>` 會導致行動端只能下載至檔案管理員
- **不得**將 `/api/photo/{code}/thumb` 端點改為回傳公開縮圖（`_generate_public_thumbnail`）— 取件頁用戶持有合法取件碼，預覽不應有浮水印；公開縮圖（含浮水印）僅供 Gallery 展示頁；兩個端點的快取路徑分別為 `{filename}.thumb.webp`（無浮水印）和 `pub_{md5}.webp`（含浮水印）
- **不得**移除 `window.matchMedia('(pointer: coarse)').matches` 的 Web Share 前置判斷 — Chrome on Windows 11 支援 `navigator.canShare`，若只判斷 `canShare` 桌機用戶點下載會跳出分享選單而非直接下載；`pointer: coarse` 才是可靠的觸控設備判斷
- **不得**在 `download.html` 的照片顯示改回 `<canvas>` + blob URL 方案 — `.anim` class 的靜態 `opacity: 0` 與 `.photo-wrap.loading` 的 animation 覆蓋造成元素永久不可見；iOS Safari blob URL → drawImage 亦不穩定；`<img>` + `-webkit-touch-callout: none` + overlay 方案在所有行動瀏覽器均可靠運作
- **不得**在 `download.html` 的 `<img class="photo-img">` 移除 `-webkit-touch-callout: none` CSS 規則 — 這是阻止 iOS Safari 長按「儲存影像」選單的關鍵；移除後 iOS 用戶可長按直接儲存圖片
- **不得**將 `serve_photo_thumb` 改回固定回傳 WebP — iOS 13 及以下的 Safari 不支援 WebP，`Accept` header 中不含 `image/webp`；移除判斷後舊版 iOS 完全無法顯示取件頁照片；必須保留 `if "image/webp" in accept` 邏輯以自動降格為 JPEG
- **不得**在 `download.html` 的預覽圖載入改回直接 `<img src="/api/photo/{code}/thumb">` — ngrok free tier 對 `<img>` 子資源請求可能回傳 HTML 警告頁，觸發 `onerror`；必須改用 `fetch()` 並帶 `ngrok-skip-browser-warning: 1` header，收到回應後確認 content-type 以 `image/` 開頭才建立 blob URL 並設為 img.src
- **不得**在 `delete_incoming` / `clear_incoming` 只清除 `.thumb.webp` — 現在 `serve_photo_thumb` 也會產生 `.thumb.jpg`；兩種縮圖快取必須一起清除，否則舊縮圖殘留 `storage/thumbs/`
- **不得**在 `customer_composite` 移除活動開關檢查、`_check_selfie_rate_limit`、單張大小上限或 `_composite_semaphore` — 該端點無認證且為 CPU 密集操作，這些是唯一的資源濫用防線
- **不得**為合成結果新增公開靜態目錄（`/static/exports`、`/static/qr` 等）— 結果必須寫入 `incoming/` 並以取件碼交付，否則繞過取件碼機制
- **不得**讓客戶端傳入 LINE userId 觸發 push — 任何人可填他人 ID 濫用 bot；LINE 交付維持「客戶輸入取件碼」流程
- **不得**繞過 `template_service.photo_groups()` 自行以槽位數計算所需照片數 — 左右對稱模板（`mirror_rows`）的照片數是「列數」而非槽位數；前後端與 `customer_composite` 必須一致
- **不得**在 `/app` 相簿上傳於瀏覽器端依槽位比例裁切 — 裁切（`ImageOps.fit`）只在 `composite_service.compose` 進行
- **不得**將 `Permissions-Policy: camera=(self)` 擴展到 `/app`、`/admin` 以外的路徑
- **不得**讓列印端點（`POST /api/admin/print/{filename}`）移除管理員認證、本機（`request.client.host`）限制、啟用開關或 `validate_filename_safety` + `relative_to` 檢查；印表機名稱必須通過 `PRINT_PRINTER_NAME_PATTERN` 白名單，且以 list 參數執行子程序（不得 `shell=True`）
- **不得**在模板槽位偵測移除邊緣透明區過濾（與影像邊緣相連、且存在內部透明區時捨棄），否則模板外圍透明區會被誤判為槽位
- **不得**在 HTML 模板中使用 `style=""` inline attribute — `style-src 'nonce-*'` 封鎖所有 `style=""` HTML attribute；所有樣式必須以具名 CSS class 形式置入 `<style nonce="__CSP_NONCE__">` 區塊；CSSOM API（`element.style.property = value`）不受此限，可安全使用
- **不得**在任何 HTML 模板新增無 `nonce="__CSP_NONCE__"` 屬性的 `<style>` 元素 — 缺少 nonce 的 `<style>` 會被 `style-src 'nonce-*'` 封鎖，造成樣式失效；動態注入 CSS 改用預埋空 `<style id="..." nonce="__CSP_NONCE__">` + CSSOM `.textContent` 方式
- **不得**將原本 `style="display:none"` inline attribute 移至 CSS 規則後，仍以 `element.style.display = ''`（空字串）顯示元素 — 空字串只清除 inline style，CSS 規則 `display:none` 仍生效，元素永遠不可見；正確寫法：`element.style.display = 'block'`（或 `'inline'`、`'flex'` 視元素而定）；同理，以 `element.style.display === 'none'` 判斷元素可見性時，若初始狀態由 CSS 而非 inline 控制，應改用 `getComputedStyle(element).display === 'none'`

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

### Axios CDN SRI

`login.html` 與 `admin.html` 的 axios `<script>` tag 已鎖定版本與 integrity hash：

```html
<script src="https://cdn.jsdelivr.net/npm/axios@1.16.1/dist/axios.min.js"
        integrity="sha384-LEhCeSYMzzIZgXNDqOnt039uBFADh2Yf9gaWTpae2Da9UHXEkW6C95emO9aEKIlp"
        crossorigin="anonymous"></script>
```

升級 axios 時必須同步更新兩個 HTML 的 URL 和 hash。計算新 hash 的方式：

```bash
curl -s https://cdn.jsdelivr.net/npm/axios@X.Y.Z/dist/axios.min.js | \
  openssl dgst -sha384 -binary | openssl base64 -A
```

### CSP 外部資源白名單

目前 `add_security_headers`（`main.py`）CSP 允許的外部來源：

| 指令 | 允許來源 |
|------|---------|
| `script-src` | `cdn.jsdelivr.net`、`cdn.tailwindcss.com` |
| `style-src` | `fonts.googleapis.com` |
| `font-src` | `fonts.gstatic.com` |

新增外部 CDN 資源時，必須更新對應指令的白名單，不可使用萬用字元（`*`）。

---

## CSP Nonce — `script-src` 移除 `unsafe-inline`；`style-src` 按路徑分流（✅ 完成）

**目標**：移除 `script-src 'unsafe-inline'`（XSS）；在不破壞 admin.html Tailwind CDN 的前提下，盡量限縮 `style-src 'unsafe-inline'` 的範圍。  
**方案**：script-src 全路徑 nonce；style-src 按 `request.url.path` 分流：

| 路徑 | `style-src` |
|------|------------|
| `/admin` | `'unsafe-inline' https://fonts.googleapis.com`（Tailwind Play CDN 動態注入 `<style>` 的必要條件）|
| 其餘路徑 | `'nonce-{nonce}' https://fonts.googleapis.com`（嚴格 nonce）|

> **Tailwind Play CDN 根本限制**：Tailwind Play CDN 在瀏覽器中執行時，掃描 DOM class list 並以 JavaScript 動態 `document.head.appendChild(style)` 注入 CSS。這些 `<style>` 元素沒有 nonce，`style-src 'nonce-*'` 會封鎖全部注入，所有 utility class（`flex`、`p-4`、`min-h-screen` 等）失效，layout 完全崩潰。唯一解法是保留 `'unsafe-inline'`，或將 admin.html 完全遷離 Tailwind CDN（成本過高）。

> **script-src `unsafe-inline` 移除**（0.4.9）：per-request nonce（`secrets.token_urlsafe(16)`）存入 `request.state.csp_nonce`，路由層呼叫 `_apply_nonce(html, nonce)` 替換 `__CSP_NONCE__` 佔位符，所有無 src 的 `<script>` 標籤加 nonce 屬性，attribute event handler 全數移除改用 `addEventListener`。
>
> **style-src 公開路徑 nonce 化**（0.5.x ZAP 修補）：`index.html` 移除 Tailwind Play CDN，所有 4 個模板的 111 個 `style=""` inline attribute 轉換為具名 CSS class 置入 `<style nonce>` 區塊；動態 `@font-face` 注入改用預埋空 `<style id="custom-font-style" nonce>` + CSSOM `.textContent`；middleware 對非 `/admin` 路徑改用 `'nonce-{nonce}'`。

### Phase 1：後端 Nonce 基礎設施（`main.py`）

在 `add_security_headers` middleware 中，於 `call_next` **之前**生成 nonce 並存入 `request.state`：

```python
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    # /admin keeps unsafe-inline for Tailwind Play CDN; all other paths use nonce
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
    # ... 其餘 headers 不變
    return response
```

新增 helper function（置於 `_html_cache` 附近）：

```python
def _apply_nonce(html: str, nonce: str) -> str:
    return html.replace("__CSP_NONCE__", nonce)
```

更新所有頁面路由，於回傳前注入 nonce（`download.html` 需同時處理 `{code}` 替換）：

```python
@app.get("/", response_class=HTMLResponse, tags=["Pages"])
async def get_index(request: Request) -> str:
    return _apply_nonce(_get_html("index.html"), request.state.csp_nonce)

@app.get("/login", response_class=HTMLResponse, tags=["Pages"])
async def get_login_page(request: Request) -> str:
    return _apply_nonce(_get_html("login.html"), request.state.csp_nonce)

@app.get("/admin", response_class=HTMLResponse, tags=["Pages"])
async def get_admin_page(request: Request, pb_session: Optional[str] = Cookie(default=None)) -> Response:
    if not auth.validate_session(pb_session):
        return RedirectResponse(url="/login", status_code=302)
    return HTMLResponse(_apply_nonce(_get_html("admin.html"), request.state.csp_nonce))

# download 路由：先 replace nonce，再 replace code
html = _apply_nonce(_get_html("download.html"), request.state.csp_nonce).replace("{code}", code)
```

> **注意**：`_html_cache` 快取的是含 `__CSP_NONCE__` 佔位符的模板字串，每次請求的字串替換開銷遠小於磁碟 I/O，快取機制不受影響。

### Phase 2：HTML 模板標記（4 個 template 檔案）

所有**無 `src` 屬性**的 `<script>` 加上 `nonce="__CSP_NONCE__"`（受 script-src nonce 強制驗證）；  
`<style>` 標籤同樣加上 `nonce="__CSP_NONCE__"`（受 style-src nonce 強制驗證）；  
**所有 `style=""` inline attribute 必須移除**，改為具名 CSS class 置入 `<style nonce>` 區塊（`style-src nonce` 封鎖所有 `style=""` HTML attribute）；  
**所有 attribute 形式的 inline event handler（`onclick=`、`onchange=` 等）必須移除**，改為在 `<script nonce>` 區塊以 `addEventListener` 綁定（CSP Level 3 的 nonce 只對 `<script>` 元素有效，attribute handler 同樣被封鎖）：

```html
<!-- Before -->
<script>tailwind.config = { darkMode: 'class' }</script>
<style> ... </style>
<script> /* 主 JS */ </script>

<!-- After -->
<script nonce="__CSP_NONCE__">tailwind.config = { darkMode: 'class' }</script>
<style nonce="__CSP_NONCE__"> ... </style>
<script nonce="__CSP_NONCE__"> /* 主 JS */ </script>
```

帶 `src` 的**外部 CDN script**（Axios、Tailwind）**不需加 nonce**，已由 domain 白名單覆蓋：

```html
<!-- 不需修改 -->
<script src="https://cdn.jsdelivr.net/npm/axios@1.16.1/dist/axios.min.js"
        integrity="sha384-..." crossorigin="anonymous"></script>
<script src="https://cdn.tailwindcss.com"></script>
```

### 驗收標準

- 瀏覽器 Console 無任何 CSP 違規訊息（`Content Security Policy` 開頭的錯誤）
- 所有頁面功能正常：admin 4-tab、上傳、Gallery、WebSocket 推播
- `curl -I http://localhost:8000/` 的 `Content-Security-Policy` 響應標頭：`script-src` **不含** `unsafe-inline`；`style-src` **含** `nonce-*`，**不含** `unsafe-inline`
- `curl -I http://localhost:8000/admin` 的 `Content-Security-Policy` 響應標頭：`script-src` **不含** `unsafe-inline`；`style-src` **含** `unsafe-inline`（/admin 路徑 Tailwind CDN 允許）

### 不應採用的替代方案

| 方案 | 捨棄原因 |
|------|---------|
| 抽出為外部 `.js` / `.css` 靜態檔 | 需新增 `StaticFiles` mount 且 JS/CSS 與 HTML 緊密耦合，維護負擔大 |
| CSP Hash（`sha256-...`）靜態計算 | 每次修改 inline script 都須手動重算 hash，與直接編輯 HTML 的開發流程衝突 |
| 保留 Tailwind CDN + `style-src 'unsafe-inline'` | CSS injection 風險雖低於 script injection，但 ZAP 仍評為 Medium；已改用移除 Tailwind CDN + nonce 方案消除此警告 |
| `<meta property="csp-nonce">` 讓 Tailwind CDN 讀取 nonce | Tailwind Play CDN 不支援此機制（測試確認無效），此方案已被排除 |

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

**全頁面已完整實作**（admin / login / index / download）

### 設計決策
- 純 JS 方案：在 HTML `<script>` 中定義 `const TRANSLATIONS = { 'zh-TW': {...}, 'en': {...} }`
- 以 `data-i18n="key"` 屬性標記需翻譯的靜態元素；`t(key)` 函數取值，`applyLang(lang)` 統一刷新
- 支援語言：**正體中文（zh-TW）** 和 **英文（en）**
- 語言切換按鈕（`.btn-icon`）僅在 **admin.html** header 右上角，供管理員手動切換

#### 語言偵測優先序（login / index / download）
```
localStorage('pb-lang')          ← 有值（管理員在 admin 切換過）則直接使用
         ↓ 否則
navigator.language               ← zh 開頭 → 'zh-TW'；其餘 → 'en'
```
偵測結果會寫回 `localStorage`，之後該裝置的所有頁面保持一致語系。

### 規則
- 翻譯物件在各 HTML 的 `<script>` 區塊，不用外部 JSON 或 i18n 函式庫
- 動態產生的 DOM（renderIncomingCard、renderAccounts 等）需在產生時呼叫 `t(key)` 取當前語系字串
- `config.py` 不需改動（後端 message 字串語言由前端決定是否顯示）
- login / index / download 的 `applyLang` 為簡化版（純 `textContent` 賦值），無需處理 placeholder / optgroup
- download.html 額外支援 `data-i18n-alt` 屬性（用於 `<img alt>`）
- login / index / download **不得**加回手動切換按鈕（設計決策：這三頁是訪客頁面，語言應自動符合裝置設定）

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
