# 拍貼機系統 (PhotoBooth Core)

智能展場級拍貼系統 — 支援 WebSocket 即時預覽、取件碼系統、LINE BOT 整合。

## 專案結構

```
photobooth-core/
├── backend/
│   ├── app/
│   │   ├── config.py              # 集中式配置管理
│   │   ├── main.py                # FastAPI 主應用（全部路由）
│   │   ├── watcher.py             # incoming/ 資料夾監聽 → WebSocket 廣播
│   │   ├── auth.py                # Session 管理
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
│       ├── bg/                    # 首頁底圖
│       ├── thumbs/                # 縮圖快取（480px WebP，按需生成）
│       ├── accounts.json
│       ├── line_config.json
│       ├── ngrok_config.json
│       ├── photo_codes.json
│       └── index_text.json        # 首頁文字設定（按需生成）
├── python/                        # 內嵌 Python 執行環境
├── first_run_setup.bat            # 首次安裝：設定 pip + 安裝依賴 + 可選清除舊資料
├── start.bat
└── AGENTS.md                      # 開發進度追蹤
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
# 開發模式 (自動重載)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生產模式
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或直接執行 `start.bat`。

### 訪問應用
- **管理後台**: http://localhost:8000/admin
- **API 文檔**: http://localhost:8000/api/docs
- **健康檢查**: http://localhost:8000/api

## 核心功能

### 已完成
- [x] 管理員登入 / 登出 / Session 管理
- [x] 帳號管理（新增 / 刪除 / 改密碼）
- [x] 首頁底圖上傳 / 刪除
- [x] 首頁文字客製化（主標題 / 副標題 / 中段文字 / 字體）
- [x] 相機照片自動監聽（Watchdog）
- [x] WebSocket 即時推播到管理後台
- [x] 取件碼自動指派（6 碼，去除易混淆字元）
- [x] 照片取件頁面（`/download/{code}`）
- [x] 縮圖快取系統（480px WebP，`storage/thumbs/`，按需生成）
- [x] LINE BOT 整合（Webhook / 輸入取件碼查詢）
- [x] ngrok 外網穿透（API + 管理 UI）
- [x] 系統一鍵重置（清除所有照片、設定、取件碼、首頁文字）
- [x] 管理後台「開啟資料夾」快速開啟 incoming 目錄（跨平台；僅本機存取可用，ngrok 等遠端連線自動隱藏按鈕並由後端 403 雙重封鎖）
- [x] 管理後台重組為 4 個分類 Tab（外觀 / 服務 / 照片 / 系統）

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
| GET | `/api/admin/bg-status` | 底圖狀態 |

### 首頁文字
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/index-text` | 取得首頁文字設定（公開）|
| POST | `/api/admin/index-text` | 儲存首頁文字設定 |

### 拍攝照片（incoming）
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/admin/incoming` | 照片列表（含取件碼）|
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

### 照片取件
| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/download/{code}` | 取件頁面 |
| GET | `/api/photo/{code}` | 取得照片檔案（?dl=1 強制下載）|

### 即時通訊
| 方法 | 端點 | 說明 |
|------|------|------|
| WS | `/ws/photos` | 新照片即時推播 |

## 環境變數

```bash
# CORS 設定（多個來源用逗號分隔）
CORS_ORIGINS=http://localhost:3000,http://example.com

# 日誌等級 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# 固定公開網址（ngrok 未啟用時使用）
PUBLIC_BASE_URL=https://your-domain.com

# ngrok Auth Token（優先序高於管理後台設定）
NGROK_AUTHTOKEN=your_token_here
```

## 故障排除

### 照片沒有推播到管理後台
1. 確認 WebSocket 連線正常（瀏覽器 DevTools → Network → WS）
2. 確認 `storage/incoming/` 資料夾有讀寫權限
3. 調高日誌等級：`LOG_LEVEL=DEBUG`

### WebSocket 連接失敗
1. 確認防火牆未擋 8000 port
2. 查看伺服器日誌

### LINE BOT 無法收到訊息
1. 確認 ngrok 隧道已啟動
2. 在 LINE Developers Console 設定 Webhook URL 為 `管理後台顯示的 Webhook URL`
3. 啟用 Use webhook 選項

---

**版本**: 0.4.0 | **更新**: 2026-06-02 | **狀態**: 生產就緒
