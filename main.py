import time
import requests
import yfinance as yf
import feedparser
import os
import sys
from datetime import datetime

# ==========================================
# 設定區
# ==========================================
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# 監控頻率 (秒)
CHECK_INTERVAL = 60 

# 價格告警門檻 (美元)
PRICE_ALERT_THRESHOLD = 0.3

# 定期價格回報 (秒) - 1小時
REPORT_INTERVAL = 3600

# ==========================================
# 核心功能區
# ==========================================

def send_telegram(message):
    """發送 Telegram 訊息"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 未設定 Telegram Token 或 Chat ID")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Telegram 發送失敗: {resp.text}")
    except Exception as e:
        print(f"⚠️ Telegram 連線錯誤: {e}")

# --- 價格監控模組 ---

def get_comex_price():
    try:
        ticker = yf.Ticker("SI=F")
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            data = ticker.history(period="5d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except:
        pass
    return None

def get_shfe_price_sina():
    url = "https://stock2.finance.sina.com.cn/futures/api/json.php/IndexService.getInnerFuturesDailyKLine?symbol=ag0"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        if data and isinstance(data, list):
            return float(data[-1]['c'])
    except:
        pass
    return None

def get_usdcny():
    try:
        return float(yf.Ticker("CNY=X").history(period="1d")['Close'].iloc[-1])
    except:
        return 7.28

# --- CME 公告監控模組 (Google RSS) ---

def check_cme_news(last_seen_links):
    """
    監控 Google News RSS，鎖定 site:cmegroup.com 
    並搜尋 Silver, Margin, Performance Bond 等關鍵字
    """
    print("[系統] 正在掃描 CME 官方公告...")
    
    # 搜尋語法: site:cmegroup.com AND (Silver OR Margin OR "Performance Bond")
    # 這會只抓取 CME 官網被 Google 收錄的最新頁面
    rss_url = "https://news.google.com/rss/search?q=site:cmegroup.com+%22Silver%22+OR+%22Margin%22+OR+%22Performance+Bond%22&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        new_links = []
        
        # 遍歷 RSS 中的新聞
        for entry in feed.entries[:5]: # 只看最新的 5 則
            title = entry.title
            link = entry.link
            published = entry.published
            
            # 如果這條新聞沒看過，且標題包含關鍵字
            if link not in last_seen_links:
                # 關鍵字過濾 (再次確認，避免 Google 給出不相干的廣告)
                keywords = ["silver", "margin", "performance bond", "collateral", "white metal"]
                if any(k in title.lower() for k in keywords):
                    
                    msg = (
                        f"🚨 <b>CME 發布重大公告 (疑似)</b>\n"
                        f"------------------\n"
                        f"標題: <b>{title}</b>\n"
                        f"時間: {published}\n"
                        f"連結: <a href='{link}'>點擊查看官方公告</a>\n"
                        f"------------------\n"
                        f"⚠️ 請立即檢查是否為調升保證金公告！"
                    )
                    send_telegram(msg)
                    print(f"🚨 發現新公告: {title}")
                
                # 加入已讀清單
                new_links.append(link)
                last_seen_links.add(link)
                
        return last_seen_links
        
    except Exception as e:
        print(f"❌ RSS 監控錯誤: {e}")
        return last_seen_links

# ==========================================
# 主程式
# ==========================================

def main():
    print("--- 🤖 超級白銀哨兵 (價格+公告) 啟動 ---")
    send_telegram(
        f"🛡️ <b>超級白銀哨兵已上線</b>\n"
        f"1. 價格監控: ±${PRICE_ALERT_THRESHOLD}\n"
        f"2. 公告監控: CME Margins\n"
        f"3. 掃描頻率: 每 {CHECK_INTERVAL} 秒"
    )

    # 初始化價格變數
    benchmark_price = None 
    last_report_time = time.time()
    
    # 初始化公告變數 (用 Set 來儲存看過的連結，避免重複發送)
    # 剛啟動時，先抓一次當作「已知」，不發送，避免一啟動就狂跳舊聞
    print("[初始化] 建立公告資料庫...")
    last_seen_links = set()
    try:
        rss_url = "https://news.google.com/rss/search?q=site:cmegroup.com+%22Silver%22+OR+%22Margin%22&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        for entry in feed.entries:
            last_seen_links.add(entry.link)
    except:
        pass
    print(f"[初始化] 已記錄 {len(last_seen_links)} 則舊公告，開始監控新公告...")

    while True:
        try:
            # --- 任務 A: 價格監控 ---
            current_comex = get_comex_price()
            current_shfe = get_shfe_price_sina()
            rate = get_usdcny()
            current_time = time.time()

            if current_comex and current_shfe:
                shfe_usd = (current_shfe / rate) / 32.1507
                spread = shfe_usd - current_comex
                
                if benchmark_price is None:
                    benchmark_price = current_comex

                print(f"[監控] COMEX: {current_comex:.2f} | 價差: {spread:.2f}")

                # 1. 整點報告
                if (current_time - last_report_time) >= REPORT_INTERVAL:
                    msg = (
                        f"⏰ <b>整點戰情室</b>\n"
                        f"🇺🇸 COMEX: <b>${current_comex:.2f}</b>\n"
                        f"🇨🇳 上海: ${shfe_usd:.2f} (¥{current_shfe:.0f})\n"
                        f"💰 價差: ${spread:.2f}"
                    )
                    send_telegram(msg)
                    last_report_time = current_time

                # 2. 波動告警
                diff = current_comex - benchmark_price
                if abs(diff) >= PRICE_ALERT_THRESHOLD:
                    emoji = "📈 急漲" if diff > 0 else "📉 急跌"
                    msg = (
                        f"🚨 <b>{emoji}警報！波動 > {PRICE_ALERT_THRESHOLD}</b>\n"
                        f"現價: <b>${current_comex:.2f}</b>\n"
                        f"基準: ${benchmark_price:.2f}\n"
                        f"價差: ${spread:.2f}"
                    )
                    send_telegram(msg)
                    benchmark_price = current_comex

            # --- 任務 B: 公告監控 ---
            # 傳入目前的已知清單，並接收更新後的清單
            last_seen_links = check_cme_news(last_seen_links)

        except Exception as e:
            print(f"❌ 主迴圈錯誤: {e}")
            time.sleep(60)

        sys.stdout.flush() 
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
