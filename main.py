import time
import requests
import yfinance as yf
import os
import sys

# ==========================================
# 設定區
# ==========================================
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# 監控間隔 (秒)，建議 60 秒檢查一次
CHECK_INTERVAL = 60 

# 告警門檻：漲跌超過此數字 (美元) 即通知
ALERT_THRESHOLD = 0.3

# 定期通知間隔 (秒)：3600 = 1小時
REPORT_INTERVAL = 3600

def send_telegram(message):
    """發送 Telegram 訊息"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 未設定 Telegram Token 或 Chat ID")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Telegram 發送失敗: {resp.text}")
    except Exception as e:
        print(f"⚠️ Telegram 連線錯誤: {e}")

def get_comex_price():
    """獲取 COMEX 白銀價格"""
    try:
        # 優先抓取 1 分鐘即時線
        ticker = yf.Ticker("SI=F")
        data = ticker.history(period="1d", interval="1m")
        
        if data.empty:
            # 盤後/週末抓日線收盤
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
            return float(data[-1]['c'])
    except Exception:
        pass
    return None

def get_usdcny():
    """獲取匯率"""
    try:
        return float(yf.Ticker("CNY=X").history(period="1d")['Close'].iloc[-1])
    except:
        return 7.28

def main():
    print("--- 🤖 白銀監控機器人 v2.0 啟動 ---")
    send_telegram(
        f"🤖 <b>白銀監控機器人已升級</b>\n"
        f"1. 波動告警: ±${ALERT_THRESHOLD}\n"
        f"2. 定期回報: 每 1 小時"
    )

    # 初始化變數
    benchmark_price = None 
    last_report_time = time.time() # 記錄上次定期報告的時間

    while True:
        try:
            # 1. 獲取數據
            current_comex = get_comex_price()
            current_shfe = get_shfe_price_sina()
            rate = get_usdcny()
            current_time = time.time()

            if current_comex and current_shfe:
                # 計算價差
                shfe_usd = (current_shfe / rate) / 32.1507
                spread = shfe_usd - current_comex
                
                # 初始化基準價格
                if benchmark_price is None:
                    benchmark_price = current_comex

                # Log 輸出 (方便在 Railway 看 Console)
                print(f"[監控] COMEX: {current_comex:.2f} | 基準: {benchmark_price:.2f} | 價差: {spread:.2f}")

                # =========================================
                # 邏輯 A: 每小時定期報告 (Hourly Report)
                # =========================================
                if (current_time - last_report_time) >= REPORT_INTERVAL:
                    msg = (
                        f"⏰ <b>整點行情報告</b>\n"
                        f"🇺🇸 COMEX: <b>${current_comex:.2f}</b>\n"
                        f"🇨🇳 上海: ${shfe_usd:.2f} (¥{current_shfe:.0f})\n"
                        f"💰 價差: ${spread:.2f}"
                    )
                    send_telegram(msg)
                    last_report_time = current_time # 重置計時器

                # =========================================
                # 邏輯 B: 波動告警 (漲跌超過 0.3)
                # =========================================
                diff = current_comex - benchmark_price
                
                # 使用 abs() 取絕對值，同時偵測漲與跌
                if abs(diff) >= ALERT_THRESHOLD:
                    emoji = "📈 急漲" if diff > 0 else "📉 急跌"
                    
                    msg = (
                        f"🚨 <b>{emoji}警報！波動 > {ALERT_THRESHOLD}</b>\n"
                        f"目前價格: <b>${current_comex:.2f}</b>\n"
                        f"前次基準: ${benchmark_price:.2f}\n"
                        f"變動幅度: {diff:+.2f}\n"
                        f"------------------\n"
                        f"目前價差: ${spread:.2f}"
                    )
                    send_telegram(msg)
                    print(f"🚀 觸發{emoji}警報！")
                    
                    # 更新基準價格，準備抓下一波 0.3 的波動
                    benchmark_price = current_comex

            else:
                print("⚠️ 部分數據抓取失敗，跳過本次檢查")

        except Exception as e:
            print(f"❌ 主迴圈發生錯誤: {e}")
            time.sleep(60)

        sys.stdout.flush() 
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
