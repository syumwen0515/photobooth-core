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

# 生產部署（敏感 Token 透過環境變數注入，不落盤）
$env:SECURE_COOKIES="true"
$env:NGROK_AUTHTOKEN="your_ngrok_token"
$env:LINE_CHANNEL_SECRET="your_line_secret"
$env:LINE_CHANNEL_ACCESS_TOKEN="your_line_token"
..\python\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
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

**Gallery 設定：**
- `storage/gallery_config.json` — `{"enabled": true, "watermark_text": "..."}` （預設值定義在 `config.py` 的 `GALLERY_CONFIG_DEFAULTS`）
- 浮水印文字變更時，呼叫 `_invalidate_public_thumbs()` 刪除所有 `pub_*.webp`；`/api/gallery` 回應帶 `wm_version`（浮水印 MD5 前 8 碼），前端縮圖 URL 帶 `?v={wm_version}` 使瀏覽器快取同步失效

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
- **不得**在 login form 移除 `method="post"` 屬性
- **不得**在 `update_gallery_settings` 移除 `_invalidate_public_thumbs()` 呼叫 — 浮水印已 bake 進縮圖，不清快取舊浮水印永不消失
- **不得**在 `loadPhotoToCanvas` 移除 `?v={wm_version}` query — 這是唯一能繞過瀏覽器 24 小時快取使浮水印變更即時生效的機制
- **不得**在 `_verify_password()` 將 `hmac.compare_digest()` 改回 `==` 字串比較 — `==` 有 short-circuit timing side channel（CWE-697），`hmac.compare_digest` 是正確的恆定時間比較方式
- **不得**在 `delete_bg` / `delete_font` 中恢復先 `.exists()` 再 `.unlink()` 的模式 — 必須直接 `.unlink()` 並捕捉 `FileNotFoundError`，以消除 TOCTOU 競態（CWE-367）
- **不得**在 `upload_incoming` 中直接使用原始 `file.filename` 作為儲存路徑 — 必須先用 `re.sub(r'[^\w\-]', '', stem)` 清除非安全字元，並以 timestamp 前綴確保唯一性，才能寫入 `INCOMING_DIR`
- **不得**將 `upload_incoming` 端點改回接受 `List[UploadFile]` — 並發由前端 `_drainUploadQueue` 的全域佇列控制，單檔端點才能讓每個 HTTP 請求有獨立的 `onUploadProgress` 回調；多檔合批上傳會導致進度條只能顯示整批進度
- **不得**將 `_generate_code()` 改回使用 `random.choices()` — `random` 為偽亂數，攻擊者可從足夠樣本推算後續碼值；必須使用 `secrets.choice()` 確保密碼學安全性（CSPRNG）
- **不得**在 `_load_gallery_config()` 移除快取機制 — 此函數是公開 `/api/gallery` 熱點路徑，快取消除了每次請求的磁碟 I/O；修改 gallery 設定時必須透過 `_save_gallery_config()` 寫入以同步更新快取，不可繞過直接寫檔

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
