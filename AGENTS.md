# 拍貼機專案開發進度

## 技術棧
- Backend: Python 3.14 / FastAPI
- File Watching: Watchdog
- Image Handling: Pillow（底圖格式轉換 + 縮圖快取生成）
- Real-time: WebSocket
- Tunnel: pyngrok
- LINE Integration: line-bot-sdk

## 開發進度

### 第一階段：基礎架構 ✅
- [x] 專案目錄結構設計
- [x] FastAPI 基礎骨架建立
- [x] 靜態檔案伺服器（incoming / bg）
- [x] 管理員後台 HTML 骨架

### 第二階段：系統優化 ✅
- [x] 集中式配置管理（config.py）
- [x] 日誌系統
- [x] CORS 安全性設定
- [x] Swagger / OpenAPI 自動文檔（`/api/docs`）
- [x] 安全性標頭 middleware

### 第三階段：核心功能 ✅
- [x] Auth 系統（登入 / 登出 / Session cookie）
- [x] 帳號管理（新增 / 刪除 / 改密碼）
- [x] 首頁底圖上傳 / 刪除
- [x] incoming 照片列表 / 刪除單張 / 清除全部
- [x] 管理後台「開啟資料夾」按鈕（`POST /api/admin/open-incoming-folder`，跨平台開啟 incoming 目錄，僅限本機存取：前端依 hostname 隱藏按鈕，後端檢查 Host header 回傳 403）
- [x] WebSocket 即時推播新照片
- [x] Watchdog 監聽 incoming/ 資料夾
- [x] 縮圖快取系統（480px WebP，storage/thumbs/，API `/api/admin/incoming/thumb/{filename}`）

### 第四階段：取件碼 + 外部整合 ✅
- [x] 6 碼取件碼自動指派（去除 0/O/1/I 易混淆字元）
- [x] 取件碼持久化（photo_codes.json）
- [x] 取件頁面 `/download/{code}`
- [x] `/api/photo/{code}` 照片服務端點
- [x] ngrok 外網穿透（token 儲存 / 啟動 / 停止 API + UI）
- [x] LINE BOT 整合（Webhook / 輸入碼查詢照片）
- [x] 系統一鍵重置 API（`POST /api/admin/reset`）

### 第五階段：外觀客製化 ✅
- [x] 首頁文字客製化（主標題 / 副標題 / 中段文字）— `GET /api/index-text`、`POST /api/admin/index-text`
- [x] 字體選擇（Noto Sans JP / Noto Serif JP / M PLUS Rounded 1c / Zen Kaku Gothic New / Shippori Mincho）
- [x] 自訂字型上傳（TTF / OTF / WOFF / WOFF2，存入 `storage/fonts/`，元資料寫入 `fonts_meta.json`）
- [x] 首頁動態載入文字設定（JS fetch，支援重置恢復預設）
- [x] 管理後台 Tab 重組（外觀 / 服務 / 照片 / 系統）

### 第六階段：系統強化 ✅
- [x] **安全 — XSS 修復**：`renderIncomingCard` 中 filename 改以 HTML 轉義 + `data-filename` + 事件委派取代 inline `onclick`
- [x] **安全 — 密碼長度提示**：`changePassword` 的 `prompt` 文字統一修正為「至少 8 個字元」（與 auth.py 規則一致）
- [x] **效能 — 縮圖 FileResponse**：`get_incoming_thumb` 改用 `FileResponse` 取代 `Response(content=read_bytes())`，避免整檔載入記憶體
- [x] **效能 — PIL 非同步化**：縮圖生成（`_generate_thumbnail`）及底圖上傳（`_process_bg_image`）拆成同步 helper，以 `run_in_executor` 執行，不再阻塞 asyncio 事件迴圈
- [x] **品質 — 常數集中至 config.py**：`GOOGLE_FONTS`、`SUPPORTED_FONT_EXTS`、`MAX_FONT_SIZE_BYTES` 從 main.py 移至 config.py
- [x] **品質 — WebSocket 連線改用 set**：`ConnectionManager.active_connections` 由 `list` 改為 `set`，斷線移除從 O(n) 降至 O(1)
- [x] **品質 — PIL 頂層 import**：`from PIL import Image, ImageOps` 與 `import io` 移至模組頂層
- [x] **品質 — 重置邏輯可讀性**：`reset_system` 中 `not p.unlink()` 取巧計數改為明確 for 迴圈，加 `list()` 避免迭代期間刪除的問題

### 決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-06-02 | 移除 compositor.py | 不需要合成功能，直接使用 incoming 原圖 |
| 2026-06-02 | 移除 printer.py | 不需要列印整合 |
| 2026-06-02 | 移除 borders/ 目錄與邊框 API | 同上，取消合成功能 |
| 2026-06-02 | 移除 2×3/2×4 版型功能 | 簡化流程，不需多版型選片 |
| 2026-06-02 | 移除 final 照片 API 與 storage/final/ | 合成功能已移除，FINAL_DIR 從未被寫入，屬於死碼 |
| 2026-06-02 | PIL 圖片處理改用 run_in_executor | PIL 是 CPU 密集操作，在 async 函數中直接呼叫會阻塞整個事件迴圈，影響 WebSocket 推播 |
| 2026-06-02 | WebSocket ConnectionManager 改用 set | list 的 remove 是 O(n)，在多連線高頻廣播場景下有效能損耗；set.discard 為 O(1) |
| 2026-06-02 | 設定常數（GOOGLE_FONTS 等）集中至 config.py | main.py 中與邏輯無關的純設定值應統一由 config.py 管理，便於日後擴充與版本同步 |

## 目前檔案結構

```
backend/app/
├── config.py
├── main.py
├── watcher.py
├── auth.py
├── ngrok_manager.py
├── line_bot.py
└── templates/
    ├── admin.html
    ├── login.html
    ├── index.html
    └── download.html

backend/storage/
├── incoming/        # 相機照片輸入（Watchdog 監聽）
├── bg/              # 首頁底圖
├── thumbs/          # 縮圖快取（480px WebP，按需生成）
├── fonts/           # 自訂字型檔案（TTF / OTF / WOFF / WOFF2）
├── accounts.json
├── fonts_meta.json  # 自訂字型元資料（family / filename / format）
├── line_config.json
├── ngrok_config.json
├── photo_codes.json
└── index_text.json  # 首頁文字設定（主標題 / 副標題 / 中段文字 / 字體）
```

## 管理後台 Tab 結構

- **外觀**（預設開啟頁）
  - 首頁底圖（上傳 / 刪除）
  - 首頁文字（主標題 / 副標題 / 中段文字 / 字體選擇，存入 index_text.json）
- **服務**
  - LINE BOT（Channel Secret / Access Token 設定 + Webhook URL 顯示）
  - 外網穿透（ngrok token + 啟動 / 停止）
- **照片**
  - incoming 照片 grid（縮圖 via `/api/admin/incoming/thumb/{filename}`，含取件碼顯示）
  - 單張刪除 / 清除全部 / 開啟資料夾
- **系統**
  - 帳號管理（列表 / 新增 / 改密碼 / 刪除）
  - 系統重置（清除照片 / LINE 設定 / 底圖 / 首頁文字）
