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
│   │   └── templates/
│   │       ├── admin.html         # 管理後台介面
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
│       ├── line_config.json
│       ├── ngrok_config.json
│       ├── photo_codes.json
│       └── index_text.json        # 首頁文字設定（按需生成）
├── python/                        # 內嵌 Python 執行環境
├── first_run_setup.bat            # 首次安裝：設定 pip + 安裝依賴 + 可選清除舊資料
├── start.bat
├── AGENTS.md                      # AI 代理開發指引
└── README.md
```

## 快速開始

### 首次安裝（Windows 嵌入式 Python）
```bat
first_run_setup.bat
```
會自動啟用 pip、安裝所有依賴，並詢問是否清除前次資料（適用於移到新電腦時）。

### 安裝依賴（一般環境）
```bash
cd backend
pip install -r requirements.txt
```

### 運行伺服器
```bash
# 開發模式（自動重載，同時開放 API 文件）
ENABLE_API_DOCS=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生產模式
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或直接執行 `start.bat`。

### 訪問應用
- **公開首頁**: http://localhost:8000
- **管理後台**: http://localhost:8000/admin（預設帳密：`admin / admin`，請立即修改）
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
- [x] 照片防下載保護 — Gallery（Canvas 渲染 + blob URL 立即撤銷 + contextmenu/drag/鍵盤快捷鍵攔截 + CSS print 隱藏）
- [x] 照片防下載保護 — 取件頁面（同 Gallery：Canvas + 透明 overlay 攔截右鍵/長按/拖曳，無法從頁面直接另存；**下載按鈕優先使用 Web Share API**，iOS 15+ / Android 86+ 用戶可直接從分享選單「存入相簿」；不支援時 fallback 為 blob URL 下載；無 Web Share 的手機用戶顯示引導提示）
- [x] 取件頁下載進度條（`ReadableStream` 逐塊讀取；有 `Content-Length` 顯示 0–100% 進度條；無則顯示 shimmer 動畫 + 已接收 bytes；完成後自動淡出；**Web Share API 僅在觸控設備觸發**，桌機直接下載不跳分享視窗）
- [x] 公開縮圖浮水印（Server-side Pillow 斜向重複浮水印；快取以 MD5 hash 命名，避免中文檔名相容問題）
- [x] Gallery 相片動畫（相片載入後 stagger 淡入 + scale 放大進場；hover 輕微浮起；gallery header 滑入動畫）
- [x] **Gallery 管理後台控制**（管理員可開啟/關閉 Gallery 區塊；可自訂浮水印文字最多 40 字元；浮水印變更後伺服器自動清除公開縮圖快取，前端以 `?v={wm_version}` query 參數同步使瀏覽器快取失效）
- [x] 並發刪除防護（`list_incoming` / `get_gallery_list` 的 `stat()` 逐項 try/except，避免並發刪除導致 500）
- [x] **管理員網頁上傳照片**（管理後台照片 tab 新增「上傳照片」按鈕；支援多選 JPG / PNG，最大 50 MB；自動產生安全檔名（timestamp + 清除特殊字元）並立即指派取件碼；上傳完成後即時插入照片卡片並廣播 WebSocket，`prependIncomingCard` 加冪等防護避免 Watchdog 重複廣播造成雙卡片）
- [x] **全域佇列上傳 + 右下角懸浮進度視窗**（前端全域 `_uploadQueue` + `_drainUploadQueue` 最多 2 線程並發消化；第一次點擊立即啟動 2 個 worker，第二次點擊（有上傳進行中）只追加到同一佇列等待，不再開啟新的 pool；後端單檔端點讓每個請求有獨立 `onUploadProgress` 回調；右下角懸浮面板逐檔顯示即時進度條、完成打勾（綠）/ 失敗顯示重傳按鈕（紅色循環箭頭，hover 旋轉）；**有失敗未處理時不自動關閉**（`data-upload-failed` 屬性標記，重傳後清除）；全部成功或取消後 3 秒自動收起；點 ✕ 有上傳進行中時跳出確認提示，確認後清空佇列並透過 `AbortController` 中止所有進行中請求）
- [x] 取件頁面模板快取（`download.html` 改用 `_get_html()` 記憶體快取，不再逐次讀磁碟）
- [x] 浮水印字型備援強化（`_wm_font()` 新增 `msyh.ttc` / `simsun.ttc`，確保無日文語言包環境仍可渲染中文）
- [x] IP 速率限制記憶體清理（`_session_cleanup_task` 每小時一併清理 `_code_request_log` 孤兒鍵）
- [x] Login form 修補 CWE-598（加 `method="post"`，密碼不再可能出現於 URL query string）
- [x] CSP header 全面強化（補齊 `default-src`、`script-src`、`style-src`、`font-src`、`img-src`、`connect-src`、`form-action`，消除 ZAP 的 4 個 Medium CSP 警告）
- [x] Axios CDN 加 SRI（`integrity="sha384-..."` + 固定版本 `axios@1.16.1`，防止 CDN 供應鏈攻擊）
- [x] 密碼雜湊比較改用 `hmac.compare_digest()`（消除 timing side channel，CWE-697）
- [x] `delete_bg` / `delete_font` 消除 TOCTOU 競態（先 exists() 再 unlink() 改為直接 unlink() + 捕捉 FileNotFoundError，CWE-367）
- [x] LINE API 呼叫設定 10 秒 timeout（防止 LINE 服務無回應時 worker 永久掛起）

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
| GET | `/api/admin/accounts` | 帳號列表 |
| POST | `/api/admin/accounts` | 新增帳號 |
| PUT | `/api/admin/accounts/{username}/password` | 改密碼 |
| DELETE | `/api/admin/accounts/{username}` | 刪除帳號 |

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
| POST | `/api/admin/upload-incoming` | 上傳照片到 incoming 資料夾（支援多檔，JPG / PNG，最大 50 MB）|
| GET | `/api/admin/incoming/thumb/{filename}` | 取得縮圖（480px WebP，有快取）|
| DELETE | `/api/admin/incoming/{filename}` | 刪除單張 |
| DELETE | `/api/admin/incoming` | 清除全部 |
| POST | `/api/admin/open-incoming-folder` | 以系統檔案總管開啟 incoming 資料夾（僅限本機，遠端回傳 403）|

### ngrok
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/ngrok/status` | 隧道狀態 |
| POST | `/api/admin/ngrok/token` | 儲存 Auth Token |
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
| `CORS_ORIGINS` | 空（不允許跨來源） | 逗號分隔的允許來源，例如 `https://example.ngrok.io` |
| `PUBLIC_BASE_URL` | 空 | 未使用 ngrok 時的固定公開網址 |
| `NGROK_AUTHTOKEN` | — | ngrok Auth Token（優先序高於後台儲存的 Token）|
| `LINE_CHANNEL_SECRET` | — | LINE Channel Secret（**優先序高於後台儲存的設定**，建議生產部署使用）|
| `LINE_CHANNEL_ACCESS_TOKEN` | — | LINE Channel Access Token（同上，兩個都設定才生效）|
| `LOG_LEVEL` | `INFO` | 日誌等級：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `RELOAD_ADMIN_HTML` | `false` | 設為 `true` 停用 HTML 快取（開發用）|
| `LOGIN_RATE_LIMIT` | `10` | 每個 IP 每分鐘最多幾次登入嘗試（可調高，建議不低於 5）|
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
| Content-Security-Policy | `default-src 'self'`；`script-src` 使用 per-request nonce（`secrets.token_urlsafe(16)`）+ jsdelivr / tailwind CDN 白名單，**無 `unsafe-inline`**（XSS script injection 完全封鎖）；HTML 模板所有 attribute event handler 已移除並改用 `addEventListener`（CSP Level 3 的 nonce 不覆蓋 attribute handler，移除才能讓按鈕在嚴格 CSP 下正常運作）；`style-src` 保留 `'unsafe-inline'`（Tailwind Play CDN 動態注入樣式的必要限制）；`font-src` 白名單 fonts.gstatic.com；`img-src` 允許 `data:` / `blob:`；`connect-src 'self'`；`form-action 'self'`；`frame-ancestors 'none'`；`object-src 'none'`；`base-uri 'self'` |
| Subresource Integrity | `login.html` / `admin.html` 的 Axios CDN 標籤加上 `integrity="sha384-..."` + 版本固定為 `axios@1.16.1`，瀏覽器驗證 hash 失敗時拒絕執行，防止 CDN 供應鏈攻擊 |
| 本機限定功能 | `open-incoming-folder` 端點驗證 TCP 連線來源 IP（非 `Host` header，防止 ngrok 環境下的 Host 偽造），非 localhost 回傳 403 |
| LINE Webhook | 驗證 `X-Line-Signature`（HMAC-SHA256）|
| 公開照片防下載 | **Gallery**：Canvas 渲染（不暴露 img src）+ blob URL 使用後立即撤銷 + 右鍵/拖曳/Ctrl+S 攔截；即使 DevTools Network tab 取得的也只是含浮水印的 480px 縮圖。**取件頁面**：同 Canvas + overlay 設計，無法右鍵/長按另存；下載按鈕優先使用 Web Share API（iOS 15+ / Android 86+），讓用戶直接從分享選單「存入相簿」，舊版或桌機 fallback 為 blob URL 下載 |
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

**版本**: 0.5.4 | **更新**: 2026-06-04（修正桌機誤觸 Web Share：Web Share API 僅在 pointer:coarse 觸控設備啟用，桌機直接 blob URL 下載）| **狀態**: 生產就緒

## 開發中 / 規劃中功能

| 功能 | 頁面 | 狀態 | 說明 |
|------|------|------|------|
| 深/淺色模式切換 | admin.html | ✅ 完成 | CSS variables + `data-theme`，header 切換按鈕 |
| 深/淺色模式切換 | login / index | 🚧 規劃中 | 尚未擴展 |
| 多語系（i18n）| admin.html | ✅ 完成 | `TRANSLATIONS` 物件 + `data-i18n`，支援 zh-TW / en |
| 多語系（i18n）| login / index / download | ✅ 完成 | 右上角語言切換按鈕；TRANSLATIONS + applyLang + data-i18n；偏好跨頁持久化 |
| Gallery 管理後台控制 | admin.html | ✅ 完成 | 照片 tab 新增 Gallery 設定卡片：開/關切換（toggle switch）+ 浮水印文字自訂；浮水印變更自動清伺服器快取並以 `wm_version` 使瀏覽器快取失效 |
| 管理員網頁上傳照片 | admin.html | ✅ 完成 | 照片 tab 新增「上傳照片」按鈕；多選 JPG / PNG；自動安全命名 + 取件碼；即時插卡並廣播 WebSocket |
| 全域佇列上傳 + 懸浮進度視窗 | admin.html | ✅ 完成 | 2 線程並發全域佇列；第二次點擊繼續排隊不另開 pool；右下角懸浮面板逐檔顯示進度條；完成綠勾 / 失敗紅叉；3 秒自動收起 |
| CSP `script-src unsafe-inline` 移除 | 全頁面 | ✅ 完成 | Nonce 方案：middleware 生成 per-request nonce，`_apply_nonce()` 注入 4 個 HTML 模板；`script-src` 移除 `unsafe-inline`（改用 nonce，XSS script injection 封鎖）；`style-src` 保留 `unsafe-inline`（Tailwind Play CDN 動態注入 style 的根本限制）；**所有 HTML 模板的 attribute event handler（`onclick=`、`onchange=` 等）已全數移除，改用 `addEventListener`**（CSP Level 3 nonce 不覆蓋 attribute handler，須移除才能讓互動功能在嚴格 CSP 下正常） |
