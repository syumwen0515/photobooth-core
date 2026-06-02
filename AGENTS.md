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

### 決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-06-02 | 移除 compositor.py | 不需要合成功能，直接使用 incoming 原圖 |
| 2026-06-02 | 移除 printer.py | 不需要列印整合 |
| 2026-06-02 | 移除 borders/ 目錄與邊框 API | 同上，取消合成功能 |
| 2026-06-02 | 移除 2×3/2×4 版型功能 | 簡化流程，不需多版型選片 |
| 2026-06-02 | 移除 final 照片 API 與 storage/final/ | 合成功能已移除，FINAL_DIR 從未被寫入，屬於死碼 |

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
├── accounts.json
├── line_config.json
├── ngrok_config.json
└── photo_codes.json
```

## 管理後台 Tab 結構

- **設定**
  - 首頁底圖（上傳 / 刪除）
  - LINE BOT（Channel Secret / Access Token 設定 + Webhook URL 顯示）
  - 外網穿透（ngrok token + 啟動 / 停止）
  - 帳號管理（列表 / 新增 / 改密碼 / 刪除）
- **拍攝照片**
  - incoming 照片 grid（縮圖 via `/api/admin/incoming/thumb/{filename}`，含取件碼顯示）
  - 單張刪除 / 清除全部 / 開啟資料夾
