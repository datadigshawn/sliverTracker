import time
import requests
import yfinance as yf
import os
import sys

# ==========================================
# 設定區 (Railway 會透過環境變數注入這些值)
# ==========================================
# 為了資安，不要將 Token 直接寫在程式碼裡上傳 Github
# 請在 Railway 的 Variables 頁面設定這些變數
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# 監控間隔 (秒)，建議 60 秒檢查一次
CHECK_INTERVAL = 60 

# 漲幅警報門檻 (美元)
ALERT_THRESHOLD = 0.1

def send_telegram(message):
    """發送 Telegram 訊息"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 未設定 Telegram Token 或 Chat ID，無法發送通知")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML" # 支援粗體等格式
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Telegram 發送失敗: {resp.text}")
    except Exception as e:
        print(f"⚠️ Telegram 連線錯誤: {e}")

def get_comex_price():
    """獲取 COMEX 白銀價格 (yfinance)"""
    try:
        # 抓取最近 1 天的 1 分鐘線 (若盤中) 或日線
        # 使用 period='1d' 比較能確保拿到最新即時價
        ticker = yf.Ticker("SI=F")
        data = ticker.history(period="1d", interval="1m")
        
        if data.empty:
            # 如果盤後或是週末沒1分鐘線，改抓日線收盤
            data = ticker.history(period="5d")
            
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"❌ COMEX 抓取錯誤: {e}")
    return None

def get_shfe_price_sina():
    """獲取上海白銀價格 (新浪K線穩定版)"""
    url = "https://stock2.finance.sina.com.cn/futures/api/json.php/IndexService.getInnerFuturesDailyKLine?symbol=ag0"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data and isinstance(data, list):
            return float(data[-1]['c']) # 回傳收盤價
    except Exception:
        pass
    return None

def get_usdcny():
    """獲取匯率"""
    try:
        return float(yf.Ticker("CNY=X").history(period="1d")['Close'].iloc[-1])
    except:
        return 7.28 # 備用預設值

def main():
    print("--- 🤖 白銀價差監控機器人啟動 ---")
    send_telegram("🤖 <b>白銀監控機器人已上線 (Railway)</b>\n開始監測 COMEX 與 上海白銀價差...")

    # 初始化變數
    last_comex_price = None
    last_shfe_price = None
    
    # 這是用來記錄「上一次通知時」的價格，用來計算漲幅
    benchmark_price = None 

    while True:
        try:
            # 1. 獲取數據
            current_comex = get_comex_price()
            current_shfe = get_shfe_price_sina()
            rate = get_usdcny()

            if current_comex and current_shfe:
                # 計算價差
                shfe_usd = (current_shfe / rate) / 32.1507
                spread = shfe_usd - current_comex
                
                # --- 邏輯 A: 定期檢視 (例如每小時報一次，或僅在變化時報) ---
                # 這裡我們先做一個簡單的 Log 輸出到 Railway Console
                print(f"[監控中] COMEX: {current_comex:.2f} | SHFE: {current_shfe} | 價差: {spread:.2f}")

                # --- 邏輯 B: COMEX 漲幅告警 (每漲 0.1) ---
                # 初始化基準價格 (第一次執行時)
                if benchmark_price is None:
                    benchmark_price = current_comex
                
                # 觸發條件：當前價格 >= 基準價格 + 0.1
                if current_comex >= (benchmark_price + ALERT_THRESHOLD):
                    msg = (
                        f"🚨 <b>COMEX 白銀急漲警報！</b>\n"
                        f"目前價格: <b>${current_comex:.2f}</b>\n"
                        f"------------------\n"
                        f"上次基準: ${benchmark_price:.2f}\n"
                        f"上海現貨: ¥{current_shfe:.0f}\n"
                        f"目前價差: ${spread:.2f}"
                    )
                    send_telegram(msg)
                    print("🚀 觸發上漲警報！")
                    
                    # 更新基準價格，準備抓下一個 0.1 的漲幅
                    benchmark_price = current_comex
                
                # 追蹤止跌機制 (可選)：如果價格跌了，基準價格要不要跟著降？
                # 如果希望「反彈 0.1」也通知，那就要跟著降。
                # 這裡設定：如果價格跌破基準，就將基準下調，這樣如果之後反彈也會通知。
                elif current_comex < benchmark_price:
                    benchmark_price = current_comex

            else:
                print("⚠️ 部分數據抓取失敗，跳過本次檢查")

        except Exception as e:
            print(f"❌ 主迴圈發生錯誤: {e}")
            # 避免錯誤導致無窮迴圈狂發請求，休息久一點
            time.sleep(60)

        # 休息一下再跑下一次
        sys.stdout.flush() # 確保 Railway Log 即時顯示
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()