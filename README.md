# 拍貼機系統 (PhotoBooth Core)

智能展場級拍貼系統 — 支援 WebSocket 即時預覽、取件碼系統、LINE BOT 整合。

## 專案結構

```
photobooth-core/
├── backend/
│   ├── app/
│   │   ├── config.py              # 集中式配置管理（含字型 / 圖片 / 安全常數）
│   │   ├── main.py                # FastAPI 主應用（全部路由）
│   │   ├── watcher.py             # incoming/ 資料夾監聽 → WebSocket 廣播
│   │   ├── auth.py                # Session 管理、PBKDF2 密碼雜湊
│   │   ├── ngrok_manager.py       # pyngrok 隧道控制
│   │   ├── line_bot.py            # LINE Webhook 處理
│   │   ├── services/
│   │   │   ├── template_service.py   # 模板透明槽位自動偵測（Pillow + numpy）
│   │   │   └── composite_service.py  # 照片裁切 / 貼入槽位 / 模板疊合 / JPEG 輸出
│   │   └── templates/
│   │       ├── admin.html         # 管理後台介面
│   │       ├── app.html           # 客戶自拍頁面（/app）
│   │       ├── login.html
│   │       ├── index.html
│   │       └── download.html      # 照片取件頁面
│   ├── requirements.txt
│   └── storage/
│       ├── incoming/              # 相機照片輸入資料夾
│       ├── bg/                    # 首頁底圖（bg.jpg + bg.webp）
│       ├── thumbs/                # 縮圖快取（480px WebP，按需生成）
│       ├── fonts/                 # 自訂字型檔案（TTF / OTF / WOFF / WOFF2）
│       ├── accounts.json
│       ├── fonts_meta.json        # 自訂字型元資料（按需生成）
│       ├── gallery_config.json    # Gallery 啟用狀態 + 浮水印文字（按需生成）
│       ├── templates/             # 合成模板 PNG（按需生成）
│       ├── templates.json         # 模板中繼資料與槽位座標（按需生成）
│       ├── selfie_config.json     # 自拍活動開關（預設關閉，按需生成）
│       ├── line_config.json
│       ├── ngrok_config.json
│       ├── photo_codes.json
│       └── index_text.json        # 首頁文字設定（按需生成）
├── python/                        # Windows 內嵌 Python（不進版控）
├── start.sh                       # Linux 啟動（首次執行會建立 venv 並安裝依賴）
├── first_run_setup.bat            # Windows 首次安裝
├── start.bat
├── AGENTS.md                      # AI 代理開發指引
└── README.md
```

## 快速開始

### Linux
先安裝 Python 3、venv 與 pip。Ubuntu / Debian 可執行：
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip fonts-noto-cjk
```
`fonts-noto-cjk`（或 `fonts-wqy-zenhei`）用於 Gallery 浮水印的繁體中文；未安裝時中文會顯示為方塊。安裝後重啟服務，偵測到浮水印字型改變會自動清除舊縮圖快取。

在專案根目錄執行：
```bash
chmod +x start.sh
./start.sh
```
首次執行會在 `.venv/` 建立虛擬環境並安裝依賴，之後再次執行會直接啟動。

### Windows
首次安裝使用內嵌 Python：
```bat
first_run_setup.bat
```
首次啟動會產生隨機管理員密碼並輸出於伺服器日誌；也可在啟動前設定至少 12 字元的 `PB_INITIAL_ADMIN_PASSWORD`。完成後執行 `start.bat` 啟動伺服器。

### 手動安裝 / 開發模式
```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt

# 開發模式（Linux / macOS）
cd backend
ENABLE_API_DOCS=true python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生產模式可改為不帶 --reload
```

### 更改連接埠
預設為 8000，若衝突可用 `PORT` 環境變數指定：
```bash
PORT=8080 ./start.sh          # Linux
set PORT=8080 && start.bat    # Windows (cmd)
```
ngrok 隧道會自動使用伺服器實際監聽的 port，無須手動填寫。

若已訂閱 ngrok 並設定自訂網域（Domains），可在後台「外網穿透」填入「自訂網域」（如 `photo.example.com`），或以 `NGROK_DOMAIN` 環境變數指定；留空則使用 ngrok 免費隨機網域。

### 訪問應用
- **公開首頁**: http://localhost:8000
- **管理後台**: http://localhost:8000/admin（帳號 `admin`；初始密碼會輸出於首次啟動日誌，或由 `PB_INITIAL_ADMIN_PASSWORD` 指定）
- **健康檢查**: http://localhost:8000/api
- **API 文件**: 預設關閉，需設定 `ENABLE_API_DOCS=true` 後訪問 `/api/docs`

## 核心功能

### 已完成
- [x] 管理員登入 / 登出 / Session 管理（5 次失敗鎖定 10 分鐘）
- [x] 帳號管理（新增 / 刪除 / 改密碼，密碼最短 8 字元；改密碼使用頁內 Modal + 密碼遮罩 + 確認欄位，不使用明碼 `prompt()`）
- [x] 首頁底圖上傳 / 刪除（自動輸出 JPEG + WebP 雙格式）
- [x] 首頁文字客製化（主標題 / 副標題 / 中段文字 / 字體）
- [x] 自訂字型上傳（TTF / OTF / WOFF / WOFF2，最大 20 MB，**支援多選批次上傳**，可在字體選單選用）
- [x] 相機照片自動監聽（Watchdog）
- [x] WebSocket 即時推播到管理後台（連線管理使用 set，斷線移除 O(1)）
- [x] 取件碼自動指派（6 碼，去除易混淆字元 0/O/1/I）
- [x] 照片取件頁面（`/download/{code}`）
- [x] 縮圖快取系統（480px WebP，`storage/thumbs/`，按需生成；以 `FileResponse` 串流回傳；刪除/清除照片時同步移除管理端與公開縮圖兩份快取）
- [x] LINE BOT 整合（Webhook / 輸入取件碼查詢）
- [x] ngrok 外網穿透（API + 管理 UI）
- [x] 系統一鍵重置（清除所有照片、設定、取件碼、首頁文字、自訂字型）
- [x] 管理後台「開啟資料夾」快速開啟 incoming 目錄（跨平台；僅本機存取可用，ngrok 等遠端連線自動隱藏按鈕並由後端 403 雙重封鎖）
- [x] 管理後台重組為 4 個分類 Tab（外觀 / 服務 / 照片 / 系統）
- [x] 管理後台深/淺色模式切換（CSS variables + `data-theme`，偏好存 `localStorage`）
- [x] 管理後台多語系（正體中文 / 英文，`data-i18n` 屬性 + `TRANSLATIONS` 物件，偏好存 `localStorage`）
- [x] **全頁面多語系擴展**（login / index / download 全部支援 zh-TW / en；自動偵測 `navigator.language`，`zh` 開頭→繁中，其餘→英文；`localStorage('pb-lang')` 跨頁持久化，admin.html 手動切換後其他頁面跟隨）
- [x] login.html / download.html UI 改版（移除 Tailwind CDN；統一 frame-corner / vertical-label 視覺語言）
- [x] 公開照片集 Gallery（首頁向下捲動切換；scroll-snap 兩區塊設計）
- [x] 公開 Gallery 縮圖保護（Canvas + 浮水印 + 480px 低解析度；前端攔截只降低一般另存便利，不能阻止使用者擷取已傳至瀏覽器的資料）
- [x] 取件頁下載流程（`<img>` 顯示縮圖，fetch 下載原圖；**下載按鈕優先使用 Web Share API**，iOS 15+ / Android 86+ 可直接分享或存入相簿；不支援時使用 blob URL 下載）
- [x] 取件頁下載進度條（`ReadableStream` 逐塊讀取；有 `Content-Length` 顯示 0–100% 進度條；無則顯示 shimmer 動畫 + 已接收 bytes；完成後自動淡出；**Web Share API 僅在觸控設備觸發**，桌機直接下載不跳分享視窗）
- [x] 取件頁照片顯示修正（`<img>` + WebP/JPEG 自動切換 + ngrok 攔截繞過）：`<img>` 取代 canvas + blob URL；`/api/photo/{code}/thumb` 依 `Accept` header 自動回 WebP 或 JPEG；預覽圖改用 `fetch()` 載入並帶 `ngrok-skip-browser-warning: 1` header（ngrok free tier 對子資源也可能回 HTML 警告頁），下載按鈕同步修正；`-webkit-touch-callout: none` 阻止 iOS 長按儲存
- [x] 公開縮圖浮水印（Server-side Pillow 斜向重複浮水印；快取以 MD5 hash 命名，避免中文檔名相容問題）
- [x] Gallery 相片動畫（相片載入後 stagger 淡入 + scale 放大進場；hover 輕微浮起；gallery header 滑入動畫）
- [x] **Gallery 管理後台控制**（管理員可開啟/關閉 Gallery 區塊；可自訂浮水印文字最多 40 字元；浮水印變更後伺服器自動清除公開縮圖快取，前端以 `?v={wm_version}` query 參數同步使瀏覽器快取失效）
- [x] 並發刪除防護（`list_incoming` / `get_gallery_list` 的 `stat()` 逐項 try/except，避免並發刪除導致 500）
- [x] **管理員網頁上傳照片**（管理後台照片 tab 新增「上傳照片」按鈕；支援多選 JPG / PNG，最大 50 MB；自動產生安全檔名（timestamp + 清除特殊字元）並立即指派取件碼；上傳完成後即時插入照片卡片並廣播 WebSocket，`prependIncomingCard` 加冪等防護避免 Watchdog 重複廣播造成雙卡片）
- [x] **全域佇列上傳 + 右下角懸浮進度視窗**（前端全域 `_uploadQueue` + `_drainUploadQueue` 最多 2 線程並發消化；第一次點擊立即啟動 2 個 worker，第二次點擊（有上傳進行中）只追加到同一佇列等待，不再開啟新的 pool；後端單檔端點讓每個請求有獨立 `onUploadProgress` 回調；右下角懸浮面板逐檔顯示即時進度條、完成打勾（綠）/ 失敗顯示重傳按鈕（紅色循環箭頭，hover 旋轉）；**有失敗未處理時不自動關閉**（`data-upload-failed` 屬性標記，重傳後清除）；全部成功或取消後 3 秒自動收起；點 ✕ 有上傳進行中時跳出確認提示，確認後清空佇列並透過 `AbortController` 中止所有進行中請求）
- [x] 取件頁面模板快取（`download.html` 改用 `_get_html()` 記憶體快取，不再逐次讀磁碟）
- [x] 浮水印字型備援強化（`_wm_font()` 新增 `msyh.ttc` / `simsun.ttc`，確保無日文語言包環境仍可渲染中文）
- [x] 浮水印字型支援 Linux 繁體中文（字型候選清單移至 `config.py` 的 `WM_FONT_CANDIDATES`，新增 Noto Sans CJK / WenQuanYi / Droid Fallback 與 `fc-match :lang=zh-tw` 動態備援；`_wm_font()` 加 `lru_cache`）
- [x] 浮水印字型變更自動清除公開縮圖快取（啟動時比對 `storage/thumbs/wm_font.marker`；`wm_version` 改含字型路徑，瀏覽器快取同步失效；修正安裝 CJK 字型後重存相同文字仍顯示方塊的問題）
- [x] IP 速率限制記憶體清理（`_session_cleanup_task` 每小時一併清理 `_code_request_log` 孤兒鍵）
- [x] 登入以 Axios `application/json` POST 提交；表單不使用原生 `method` / `action`
- [x] CSP header 全面強化（補齊 `default-src`、`script-src`、`style-src`、`font-src`、`img-src`、`connect-src`、`form-action`，消除 ZAP 的 4 個 Medium CSP 警告）
- [x] Axios CDN 加 SRI（`integrity="sha384-..."` + 固定版本 `axios@1.16.1`，防止 CDN 供應鏈攻擊）
- [x] 密碼雜湊比較改用 `hmac.compare_digest()`（消除 timing side channel，CWE-697）
- [x] `delete_bg` / `delete_font` 消除 TOCTOU 競態（先 exists() 再 unlink() 改為直接 unlink() + 捕捉 FileNotFoundError，CWE-367）
- [x] LINE API 呼叫設定 10 秒 timeout（防止 LINE 服務無回應時 worker 永久掛起）
- [x] **ZAP 弱點掃描全面修補**（ZAP by Checkmarx，2026-06-04 掃描結果）
  - **CSP `style-src 'unsafe-inline'` 最小化**（Medium/High）：`index.html` 移除 Tailwind Play CDN；4 個模板 111 個 `style=""` inline attribute 全部改為具名 CSS class + `<style nonce>` 區塊；middleware 對公開路徑（`/`、`/login`、`/download/`）改為 `style-src 'nonce-{nonce}'`；`/admin` 路徑保留 `'unsafe-inline'`（Tailwind Play CDN 動態注入 `<style>` 的必要條件，且 admin 為已驗證路徑）
  - **SRI 缺失修補**（Medium/High）：Tailwind Play CDN 為動態 JIT CDN，回應內容不固定無法計算 SRI hash；從 `index.html` 移除解決根本問題
  - **Anti-CSRF 表面消除**（Medium/Low）：login form 的 `method="post" action="..."` 屬性移除；登入以 `Content-Type: application/json` axios POST 提交，天然抵抗 CSRF，無需 server-side token
  - **跨域 JS 來源消除**（Low/Medium）：`index.html` 移除 Tailwind CDN 後，公開頁面不再載入外部 JS（admin.html 保留 Tailwind CDN，後台頁已驗證身分）
- [x] **admin.html 互動功能回歸修復**（ZAP 修補後遺症）：ZAP 修補將 `style="display:none"` 移至 CSS 規則後，JS 中 `element.style.display = ''` 無法再顯示元素（空字串只清除 inline style，CSS 規則仍生效）；修復：`#gallerySettingsMsg` 的顯示改為 `style.display = 'inline'`；`showUploadPanel()` 的可見性判斷改用 `getComputedStyle(panel).display === 'none'`，且改為 `style.display = 'block'`

## 工作流程

```
1. 相機將照片放入 storage/incoming/
2. Watchdog 偵測 → 指派 6 碼取件碼 → WebSocket 廣播
3. 管理後台即時顯示新照片 + 取件碼
4. 客人透過 /download/{code} 頁面或 LINE BOT 輸入碼取得照片
```

## API 端點

### 系統
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api` | 健康檢查 |
| GET | `/` | 首頁 |
| GET | `/admin` | 管理後台（需登入）|
| GET | `/login` | 登入頁面 |
| POST | `/api/admin/reset` | 系統一鍵重置 |

### 身份驗證
| 方法 | 端點 | 說明 |
|------|------|------|
| POST | `/api/auth/login` | 登入 |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 取得目前登入帳號 |

### 帳號管理
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/accounts` | 帳號列表（含 `current` 目前登入者、`super_admin`）|
| POST | `/api/admin/accounts` | 新增帳號 |
| PUT | `/api/admin/accounts/{username}/password` | 改密碼（僅本人；`admin` 可改任何人，否則 403）|
| DELETE | `/api/admin/accounts/{username}` | 刪除帳號（僅 `admin` 可刪，且 `admin` 本身不可刪）|

### 首頁底圖
| 方法 | 端點 | 說明 |
|------|------|------|
| POST | `/api/admin/upload-bg` | 上傳底圖 |
| DELETE | `/api/admin/bg` | 刪除底圖 |
| GET | `/api/admin/bg-status` | 底圖狀態（需登入） |

### 首頁文字
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/index-text` | 取得首頁文字設定（公開）|
| POST | `/api/admin/index-text` | 儲存首頁文字設定 |

### 自訂字型
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/fonts` | 取得已上傳字型列表（公開）|
| POST | `/api/admin/fonts` | 上傳字型（TTF / OTF / WOFF / WOFF2，最大 20 MB，支援多檔批次上傳）|
| DELETE | `/api/admin/fonts/{filename}` | 刪除字型 |

### 拍攝照片（incoming）
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/incoming` | 照片列表（含取件碼）|
| POST | `/api/admin/upload-incoming` | 單一請求上傳一張照片（JPG / PNG，最大 50 MB）；管理介面支援多選並逐檔送出 |
| GET | `/api/admin/incoming/thumb/{filename}` | 取得縮圖（480px WebP，有快取）|
| DELETE | `/api/admin/incoming/{filename}` | 刪除單張 |
| DELETE | `/api/admin/incoming` | 清除全部 |
| POST | `/api/admin/open-incoming-folder` | 以系統檔案總管開啟 incoming 資料夾（僅限本機，遠端回傳 403）|

### ngrok
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/ngrok/status` | 隧道狀態 |
| POST | `/api/admin/ngrok/token` | 儲存 Auth Token |
| POST | `/api/admin/ngrok/domain` | 儲存自訂網域（空字串＝清除，改用免費網域）|
| POST | `/api/admin/ngrok/start` | 啟動隧道 |
| POST | `/api/admin/ngrok/stop` | 停止隧道 |
| GET | `/api/ngrok-url` | 取得公開網址（公開）|

### LINE BOT
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/line/config` | 取得設定 + Webhook URL |
| POST | `/api/admin/line/config` | 儲存設定 |
| POST | `/api/line/webhook` | LINE Webhook 接收端 |

### 公開照片集（Gallery）
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/gallery` | 照片列表（公開，按拍攝時間排序；含 `enabled` / `wm_version` 欄位）|
| GET | `/api/gallery/thumb/{filename}` | 公開縮圖（480px WebP，含浮水印，MD5 hash 快取；接受 `?v=` query 用於瀏覽器快取失效）|

### Gallery 設定
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/gallery-settings` | 取得 Gallery 設定（需登入）|
| POST | `/api/admin/gallery-settings` | 儲存 Gallery 設定（`enabled`、`watermark_text`）；浮水印變更時自動清除公開縮圖快取 |

### 自拍活動與模板（選用）
未上傳模板、未開啟「自拍活動」時，系統行為與原本完全相同。合成結果寫入 `incoming/`，沿用取件碼、Gallery 與縮圖機制。

| 方法 | 端點 | 說明 |
|------|------|------|
| GET/POST | `/api/admin/selfie-settings` | 取得 / 儲存自拍活動開關（需登入）|
| GET | `/api/admin/templates` | 模板列表（需登入）|
| POST | `/api/admin/templates` | 上傳模板 PNG 並自動偵測透明槽位（`file`、選填 `name`；需登入）|
| POST | `/api/admin/templates/{id}/slots` | 微調槽位座標（需登入）|
| DELETE | `/api/admin/templates/{id}` | 刪除模板（需登入）|
| GET | `/api/admin/templates/{id}/image` | 模板圖檔（需登入）|
| GET | `/app` | 客戶自拍頁（需 HTTPS 才能開啟相機；僅此路徑 `Permissions-Policy: camera=(self)`）|
| GET | `/api/v1/customer/templates` | 可用模板列表（活動關閉時 `enabled:false`）|
| GET | `/api/v1/customer/templates/{id}/image` | 模板圖檔（活動關閉時 403）|
| POST | `/api/v1/customer/composite` | `multipart/form-data`：`template_id` + `files`（照片數須等於槽位數，依槽位順序）；回傳 `code` 與 `download_url`。速率限制：`SELFIE_RATE_LIMIT`/分/IP |

LINE 交付沿用現有流程：客戶在 LINE 輸入取件碼取得 `/download/{code}` 連結。

### 照片取件
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/download/{code}` | 取件頁面（速率限制：30 次/分/IP）|
| GET | `/api/photo/{code}` | 取得照片原檔（`?dl=1` 強制下載；速率限制同上）|
| GET | `/api/photo/{code}/thumb` | 取件頁預覽縮圖（480px WebP，無浮水印；速率限制同上；有快取）|

### 即時通訊
| 方法 | 端點 | 說明 |
|------|------|------|
| WS | `/ws/photos` | 新照片即時推播（需登入）|

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `SECURE_COOKIES` | `false` | 設為 `true` 時 Session Cookie 加上 `Secure` flag，透過 ngrok HTTPS 部署時必須啟用 |
| `ENABLE_API_DOCS` | `false` | 設為 `true` 開放 `/api/docs`、`/api/redoc`、`/api/openapi.json` |
| `PORT` | `8000` | 伺服器監聽埠；`start.sh` / `start.bat` 與 ngrok 預設埠共用 |
| `PB_INITIAL_ADMIN_PASSWORD` | 空（隨機產生） | 首次建立 `admin` 帳號的初始密碼，至少 12 字元；未設定時產生隨機密碼並輸出於日誌 |
| `CORS_ORIGINS` | 空（不允許跨來源） | 逗號分隔的允許來源，例如 `https://example.ngrok.io` |
| `PUBLIC_BASE_URL` | 空 | 未使用 ngrok 時的固定公開網址 |
| `NGROK_AUTHTOKEN` | — | ngrok Auth Token（優先序高於後台儲存的 Token）|
| `NGROK_DOMAIN` | — | ngrok 自訂網域（需付費方案；優先序高於後台儲存的網域，留空則使用免費網域）|
| `LINE_CHANNEL_SECRET` | — | LINE Channel Secret（**優先序高於後台儲存的設定**，建議生產部署使用）|
| `LINE_CHANNEL_ACCESS_TOKEN` | — | LINE Channel Access Token（同上，兩個都設定才生效）|
| `LOG_LEVEL` | `INFO` | 日誌等級：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `RELOAD_ADMIN_HTML` | `false` | 設為 `true` 停用 HTML 快取（開發用）|
| `LOGIN_RATE_LIMIT` | `10` | 每個 IP 每分鐘最多幾次登入嘗試（可調高，建議不低於 5）|
| `SELFIE_RATE_LIMIT` | `6` | 客戶自拍合成端點每個 IP 每分鐘最多幾次 |
| `TRUSTED_PROXY_IPS` | 空（不信任） | 逗號分隔的可信代理 IP，設定後才信任 `X-Forwarded-For`；例如 `127.0.0.1,::1`（放在 nginx 後方時使用）|

> **安全建議**：生產展場部署時，建議透過環境變數注入所有敏感 Token（`NGROK_AUTHTOKEN`、`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`），避免憑證以明文形式落盤於 `storage/` 目錄。

## 安全性設計

| 機制 | 說明 |
|------|------|
| 密碼雜湊 | **PBKDF2-HMAC-SHA256**（260,000 rounds + 隨機 salt）；舊 SHA-256 帳號於下次登入時自動靜默升級；雜湊比較使用 `hmac.compare_digest()`（恆定時間，消除 timing side channel）|
| Session Cookie | `pb_session`（HttpOnly、SameSite=Lax、7 天 TTL；`SECURE_COOKIES=true` 時加上 Secure flag）|
| Session 清理 | 服務啟動後每小時自動清理過期 session 與速率限制記錄，防止記憶體無限成長 |
| 帳號鎖定 | 同一帳號 10 分鐘內失敗 5 次 → 鎖定 10 分鐘（防止單一帳號枚舉）|
| 登入 IP 速率限制 | 每個 IP 每分鐘最多 10 次登入嘗試（`LOGIN_RATE_LIMIT`，可透過環境變數調整）；阻擋分散式帳號噴灑攻擊 |
| 取件碼速率限制 | 取件碼端點（`/download/{code}`、`/api/photo/{code}`）每個 IP 每分鐘最多 30 次，超過回傳 429 |
| 原始照片存取保護 | `/static/incoming/` 目錄受 middleware 保護，需有效管理員 session 才能存取原始高解析度照片；公開訪客只能透過 `/api/photo/{code}`（需取件碼）或 `/api/gallery/thumb/{filename}`（含浮水印縮圖）存取 |
| X-Forwarded-For 防偽 | 僅在連線來源 IP 屬於 `TRUSTED_PROXY_IPS`（環境變數）時才信任 `X-Forwarded-For` 標頭；預設不信任，防止攻擊者偽造 IP 規避速率限制 |
| WebSocket 認證 | `/ws/photos` 連線時驗證 Session Cookie，未登入者返回 1008 Policy Violation |
| API 文件 | 預設關閉；需明確設定 `ENABLE_API_DOCS=true` 才開放 |
| 路徑驗證 | 所有檔案操作透過 `validate_filename_safety` + `Path.resolve().relative_to()` 雙重防護 |
| XSS 防護 | 前端照片卡片 filename 以 HTML escape + `data-*` 屬性 + 事件委派處理；**全頁面所有事件綁定改用 `addEventListener`（已移除所有 `onclick=`、`onchange=` 等 attribute 形式 inline handler）**；CSP Level 3 `script-src 'nonce-*'` 封鎖所有 attribute handler，動態生成元素改用 `data-uid` + delegation |
| 密碼輸入遮罩 | 改密碼透過頁內 Modal（`type="password"` 欄位）完成，不使用原生 `prompt()`（明碼顯示）|
| 安全標頭 | `X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy`、`Permissions-Policy`；HTTPS 環境下另加 `Strict-Transport-Security` |
| Content-Security-Policy | `default-src 'self'`；`script-src` 使用 per-request nonce（`secrets.token_urlsafe(16)`）+ jsdelivr / tailwind CDN 白名單，**無 `unsafe-inline`**（XSS script injection 完全封鎖）；HTML 模板所有 attribute event handler 已移除並改用 `addEventListener`（CSP Level 3 的 nonce 不覆蓋 attribute handler，移除才能讓按鈕在嚴格 CSP 下正常運作）；`style-src` 按路徑分流：**公開路徑（`/`、`/login`、`/download/`）使用 per-request nonce，無 `unsafe-inline`**（CSS injection 封鎖）；`/admin` 路徑保留 `'unsafe-inline'`（Tailwind Play CDN 動態注入 `<style>` 的必要條件，admin 為已驗證路徑）；`font-src` 白名單 fonts.gstatic.com；`img-src` 允許 `data:` / `blob:`；`connect-src 'self'`；`form-action 'self'`；`frame-ancestors 'none'`；`object-src 'none'`；`base-uri 'self'` |
| Subresource Integrity | `login.html` / `admin.html` 的 Axios CDN 標籤加上 `integrity="sha384-..."` + 版本固定為 `axios@1.16.1`，瀏覽器驗證 hash 失敗時拒絕執行，防止 CDN 供應鏈攻擊 |
| 本機限定功能 | `open-incoming-folder` 端點驗證 TCP 連線來源 IP（非 `Host` header，防止 ngrok 環境下的 Host 偽造），非 localhost 回傳 403 |
| LINE Webhook | 驗證 `X-Line-Signature`（HMAC-SHA256）|
| 公開照片存取 | **Gallery**：公開內容僅有 480px 浮水印縮圖；Canvas 與右鍵/拖曳攔截只能降低一般另存便利，不能阻止使用者擷取瀏覽器已取得的資料。原圖需有效取件碼或管理員 session。**取件頁面**：`<img>` 顯示縮圖；下載按鈕優先使用 Web Share API（iOS 15+ / Android 86+），不支援時以 blob URL 下載 |
| 縮圖快取命名 | 公開縮圖以 `MD5(filename)` 命名（`pub_<hash>.webp`），避免中文/特殊字元檔名在 Windows 路徑比對不一致；Pillow 讀圖改用 BytesIO，避免 Unicode path 相容問題 |
| 取件碼生成 | 使用 Python `secrets.choice()`（CSPRNG）生成 6 碼取件碼，確保攻擊者無法從已知碼推算後續碼；`random.choices()`（梅森旋轉，非密碼學安全）已移除 |
| 敏感 Token 環境變數注入 | `NGROK_AUTHTOKEN`、`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN` 均支援環境變數覆蓋，優先序高於 JSON 落盤設定；建議展場生產部署時以環境變數注入，不將 Token 存入 `storage/` 明文檔 |

## 故障排除

### 照片沒有推播到管理後台
1. 確認 WebSocket 連線正常（瀏覽器 DevTools → Network → WS）
2. 確認 `storage/incoming/` 資料夾有讀寫權限
3. 確認管理員已登入（WebSocket 現在需要 Session）
4. 調高日誌等級：`LOG_LEVEL=DEBUG`

### LINE BOT 無法收到訊息
1. 確認 ngrok 隧道已啟動
2. 在 LINE Developers Console 設定 Webhook URL 為管理後台顯示的網址
3. 啟用 Use webhook 選項

### ngrok HTTPS 環境下 Cookie 失效
設定環境變數 `SECURE_COOKIES=true` 再重啟伺服器。

---

**版本**: 0.5.11 | **更新**: 2026-11-11（帳號權限：admin 為最高管理者、改密碼僅限本人、改自己密碼後自動跳轉登入、後台 401 自動導向登入；前次：Linux 繁中浮水印字型；前次：Linux 啟動、初始化管理員密碼、Gallery 停用端點封鎖、帳號 session 撤銷與回歸測試）| **狀態**: 上線前驗證中

## 開發中 / 規劃中功能

| 功能 | 頁面 | 狀態 | 說明 |
|------|------|------|------|
| 深/淺色模式切換 | admin.html | ✅ 完成 | CSS variables + `data-theme`，header 切換按鈕 |
| 深/淺色模式切換 | login / index | 🚧 規劃中 | 尚未擴展 |
| 多語系（i18n）| admin.html | ✅ 完成 | `TRANSLATIONS` 物件 + `data-i18n`，支援 zh-TW / en |
| 多語系（i18n）| login / index / download | ✅ 完成 | 自動偵測瀏覽器語言；TRANSLATIONS + applyLang + data-i18n；偏好跨頁持久化 |
| Gallery 管理後台控制 | admin.html | ✅ 完成 | 照片 tab 新增 Gallery 設定卡片：開/關切換（toggle switch）+ 浮水印文字自訂；浮水印變更自動清伺服器快取並以 `wm_version` 使瀏覽器快取失效 |
| 模板自動偵測 + 客戶自拍合成 | admin.html / app.html | ✅ 完成 | 後台上傳含透明區域的 PNG 自動偵測槽位（可微調）；`/app` 自拍頁依槽位順序拍攝後合成，結果進入取件碼流程；相機控制與列印尚未實作 |
| 管理員網頁上傳照片 | admin.html | ✅ 完成 | 照片 tab 新增「上傳照片」按鈕；多選 JPG / PNG；自動安全命名 + 取件碼；即時插卡並廣播 WebSocket |
| 全域佇列上傳 + 懸浮進度視窗 | admin.html | ✅ 完成 | 2 線程並發全域佇列；第二次點擊繼續排隊不另開 pool；右下角懸浮面板逐檔顯示進度條；完成綠勾 / 失敗紅叉；3 秒自動收起 |
| CSP `script-src unsafe-inline` 移除；`style-src` 公開路徑 nonce 化 | 全頁面 | ✅ 完成 | Nonce 方案：middleware 生成 per-request nonce，`_apply_nonce()` 注入 4 個 HTML 模板；`script-src` 全路徑移除 `unsafe-inline`；`style-src` 按路徑分流（公開路徑 nonce，`/admin` 保留 `unsafe-inline` 供 Tailwind CDN）；`index.html` 移除 Tailwind Play CDN；4 個模板 111 個 `style=""` inline attribute 全數轉為具名 CSS class；**所有 attribute event handler 已移除，改用 `addEventListener`** |
| ZAP 弱點掃描修補 | 全頁面 | ✅ 完成 | style-src unsafe-inline 最小化（公開路徑 nonce-only）、SRI 問題（Tailwind CDN 移除）、Anti-CSRF 表面消除（login form method/action 移除）、跨域 JS 來源消除（index.html 無外部 JS） |
