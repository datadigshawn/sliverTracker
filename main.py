"""
超級白銀哨兵 - Railway 部署版
功能：
1. 定期監控 COMEX 與上海白銀價格
2. 每小時定期回報
3. 價格變動 ±0.3 告警
4. CME 保證金公告監控
"""

import time
import requests
import yfinance as yf
import feedparser
import os
import sys
from datetime import datetime
import traceback

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

# 是否為測試模式（本地開發用）
TEST_MODE = os.environ.get("TEST_MODE", "False").lower() == "true"

# ==========================================
# Telegram 通訊模組
# ==========================================

def send_telegram(message, silent=False):
    """發送 Telegram 訊息（增強版）"""
    if not TG_TOKEN or not TG_CHAT_ID:
        if TEST_MODE:
            print(f"\n📱 [Telegram 訊息預覽]")
            print("━" * 50)
            # 移除 HTML 標籤顯示純文字
            import re
            clean_msg = re.sub(r'<[^>]+>', '', message)
            print(clean_msg)
            print("━" * 50)
        # 無 Token 時靜默返回，不影響程式運行
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": silent  # 支援靜音發送
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            else:
                print(f"⚠️ Telegram 發送失敗 (嘗試 {attempt+1}/{max_retries}): {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram 連線錯誤 (嘗試 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    return False

# ==========================================
# 價格監控模組（整合剛才的穩定架構）
# ==========================================

def get_comex_price():
    """
    獲取 COMEX 白銀價格（優化版）
    策略：盤中用 1 分鐘線，盤後/週末用日線
    """
    try:
        ticker = yf.Ticker("SI=F")
        
        # 策略 1: 嘗試 1 分鐘線（盤中最即時）
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            # 合理性檢查（白銀價格通常在 15-50 美元）
            if 15 < price < 50:
                return price
        
        # 策略 2: 使用日線（更穩定）
        data = ticker.history(period="7d", interval="1d")
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            if 15 < price < 50:
                return price
                
    except Exception as e:
        print(f"   ❌ COMEX 抓取失敗: {e}")
    
    return None


def get_shfe_price_sina():
    """
    從新浪財經獲取上海白銀價格（K線版，週末穩定）
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn/'
    }
    
    url = "https://stock2.finance.sina.com.cn/futures/api/json.php/IndexService.getInnerFuturesDailyKLine?symbol=ag0"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code != 200:
            return None
            
        data = res.json()
        
        if data and isinstance(data, list) and len(data) > 0:
            last_record = data[-1]
            if 'c' in last_record:
                price = float(last_record['c'])
                # 合理性檢查（上海白銀價格通常在 5000-8000 人民幣/公斤）
                if 5000 < price < 8000:
                    return price
                    
    except Exception as e:
        print(f"   ❌ 新浪 API 錯誤: {e}")
    
    return None


def get_shfe_price_eastmoney():
    """
    備用數據源：東方財富網
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url = "http://push2.eastmoney.com/api/qt/stock/get?secid=113.agm&fields=f43,f44,f45,f46"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        
        if data.get('data') and 'f43' in data['data']:
            price = float(data['data']['f43'])
            if 5000 < price < 8000:
                return price
                
    except Exception as e:
        print(f"   ❌ 東方財富網錯誤: {e}")
    
    return None


def get_shfe_price():
    """
    獲取上海白銀價格（多數據源策略）
    """
    # 優先新浪
    price = get_shfe_price_sina()
    if price:
        return price
    
    # 備用東方財富網
    print("   [系統] 新浪失敗，切換至東方財富網...")
    price = get_shfe_price_eastmoney()
    if price:
        return price
    
    return None


def get_usdcny():
    """
    獲取美元對人民幣匯率（修正版）
    """
    try:
        # 正確的匯率代碼
        ticker = yf.Ticker("USDCNY=X")
        data = ticker.history(period="5d", interval="1d")
        
        if not data.empty:
            rate = float(data['Close'].iloc[-1])
            # 合理性檢查（匯率通常在 6-8 之間）
            if 6 < rate < 8:
                return rate
    except Exception as e:
        print(f"   ⚠️ 匯率抓取失敗: {e}")
    
    # 回退到預設值
    return 7.28


# ==========================================
# CME 公告監控模組（優化版）
# ==========================================

def check_cme_news(last_seen_links):
    """
    監控 CME 官方公告（透過 Google News RSS）
    改進：更精準的關鍵字過濾，避免誤報
    """
    
    # 使用 Google News RSS 搜尋 CME 官網的白銀/保證金相關新聞
    rss_url = (
        "https://news.google.com/rss/search?"
        "q=site:cmegroup.com+%22Silver%22+OR+%22Margin%22+OR+%22Performance+Bond%22"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    
    try:
        feed = feedparser.parse(rss_url)
        new_alerts = []
        
        for entry in feed.entries[:10]:  # 檢查前 10 則
            title = entry.title
            link = entry.link
            published = entry.get('published', 'N/A')
            
            # 如果是新公告
            if link not in last_seen_links:
                
                # 關鍵字過濾（更精準）
                # 必須包含 silver 相關字眼
                silver_keywords = ["silver", "white metal", "ag"]
                has_silver = any(k in title.lower() for k in silver_keywords)
                
                # 且包含保證金相關字眼
                margin_keywords = [
                    "margin", "performance bond", "collateral",
                    "initial margin", "maintenance margin",
                    "margin increase", "margin decrease"
                ]
                has_margin = any(k in title.lower() for k in margin_keywords)
                
                if has_silver and has_margin:
                    msg = (
                        f"🚨 <b>CME 保證金公告！</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"📋 標題: <b>{title}</b>\n"
                        f"📅 時間: {published}\n"
                        f"🔗 連結: <a href='{link}'>查看完整公告</a>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"⚠️ 請立即確認是否影響倉位！"
                    )
                    new_alerts.append((title, msg))
                
                # 記錄所有新連結（避免重複處理）
                last_seen_links.add(link)
        
        # 發送告警
        if new_alerts:
            print(f"\n🚨 發現 {len(new_alerts)} 則新公告！")
            for title, msg in new_alerts:
                send_telegram(msg)
                print(f"   ├─ {title}")
        
        return last_seen_links
        
    except Exception as e:
        print(f"   ❌ CME RSS 錯誤: {e}")
        return last_seen_links


# ==========================================
# 狀態管理
# ==========================================

class MonitorState:
    """監控狀態管理"""
    def __init__(self):
        self.benchmark_price = None
        self.last_report_time = time.time()
        self.last_comex = None
        self.last_shfe = None
        self.consecutive_failures = 0
        self.total_checks = 0
        self.successful_checks = 0
        
    def update_success(self):
        self.consecutive_failures = 0
        self.total_checks += 1
        self.successful_checks += 1
        
    def update_failure(self):
        self.consecutive_failures += 1
        self.total_checks += 1
        
    def get_success_rate(self):
        if self.total_checks == 0:
            return 0
        return (self.successful_checks / self.total_checks) * 100


# ==========================================
# 主監控邏輯
# ==========================================

def monitoring_cycle(state, last_seen_links):
    """
    單次監控循環
    返回：更新後的 last_seen_links
    """
    
    # --- 1. 抓取價格數據 ---
    current_comex = get_comex_price()
    current_shfe = get_shfe_price()
    rate = get_usdcny()
    current_time = time.time()
    
    # --- 2. 數據驗證 ---
    if current_comex is None or current_shfe is None:
        state.update_failure()
        
        # 顯示診斷資訊
        status = []
        if current_comex is None:
            status.append("COMEX=失敗")
        if current_shfe is None:
            status.append("上海=失敗")
            
        print(f"⚠️ 數據缺失 ({', '.join(status)}) | 連續失敗: {state.consecutive_failures}")
        
        # 連續失敗告警
        if state.consecutive_failures == 5:
            send_telegram(
                "⚠️ <b>系統警告</b>\n"
                "數據抓取連續失敗 5 次\n"
                "請檢查網路連線或 API 狀態"
            )
        
        return last_seen_links
    
    # --- 3. 計算價差 ---
    state.update_success()
    shfe_usd = (current_shfe / rate) / 32.1507466  # 公斤轉盎司
    spread = shfe_usd - current_comex
    
    # 初始化基準價格
    if state.benchmark_price is None:
        state.benchmark_price = current_comex
        print(f"📌 基準價格設定: ${current_comex:.2f}")
    
    # --- 4. 顯示監控狀態 ---
    timestamp = datetime.now().strftime("%H:%M:%S")
    success_rate = state.get_success_rate()
    
    print(
        f"[{timestamp}] "
        f"COMEX: ${current_comex:.2f} | "
        f"上海: ¥{current_shfe:.0f} (${shfe_usd:.2f}) | "
        f"價差: ${spread:+.2f} | "
        f"成功率: {success_rate:.1f}%"
    )
    
    # --- 5. 整點報告 ---
    if (current_time - state.last_report_time) >= REPORT_INTERVAL:
        print(f"\n⏰ 發送整點報告...")
        
        # 計算與基準的變化
        change = current_comex - state.benchmark_price
        change_pct = (change / state.benchmark_price) * 100 if state.benchmark_price else 0
        
        msg = (
            f"⏰ <b>整點戰情室</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🇺🇸 COMEX: <b>${current_comex:.2f}</b>\n"
            f"🇨🇳 上海: ${shfe_usd:.2f} (¥{current_shfe:.0f}/kg)\n"
            f"💱 匯率: {rate:.4f}\n"
            f"💰 價差: ${spread:+.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📊 基準價: ${state.benchmark_price:.2f}\n"
            f"📈 變動: ${change:+.2f} ({change_pct:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ 系統健康度: {success_rate:.1f}%"
        )
        
        send_telegram(msg, silent=True)  # 靜音發送
        state.last_report_time = current_time
    
    # --- 6. 價格波動告警 ---
    diff = current_comex - state.benchmark_price
    
    if abs(diff) >= PRICE_ALERT_THRESHOLD:
        emoji = "📈" if diff > 0 else "📉"
        trend = "急漲" if diff > 0 else "急跌"
        change_pct = (diff / state.benchmark_price) * 100
        
        msg = (
            f"🚨 <b>{emoji} {trend}警報！</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📍 現價: <b>${current_comex:.2f}</b>\n"
            f"📊 基準: ${state.benchmark_price:.2f}\n"
            f"📈 變動: <b>${diff:+.2f}</b> ({change_pct:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🇨🇳 上海: ${shfe_usd:.2f}\n"
            f"💰 價差: ${spread:+.2f}\n"
            f"⏰ 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        send_telegram(msg)
        print(f"\n🚨 {trend}警報觸發！變動: ${diff:+.2f}")
        
        # 更新基準價格
        state.benchmark_price = current_comex
    
    # --- 7. CME 公告監控 ---
    last_seen_links = check_cme_news(last_seen_links)
    
    # 記錄最新價格
    state.last_comex = current_comex
    state.last_shfe = current_shfe
    
    return last_seen_links


# ==========================================
# 主程式
# ==========================================

def main():
    """主程式入口"""
    
    print("\n" + "="*60)
    print("🤖 超級白銀哨兵 v2.0 - 已啟動")
    print("="*60)
    print(f"📅 啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔧 測試模式: {'開啟' if TEST_MODE else '關閉'}")
    print(f"⏱️  檢查間隔: {CHECK_INTERVAL} 秒")
    print(f"📊 告警門檻: ±${PRICE_ALERT_THRESHOLD}")
    print(f"⏰ 報告間隔: {REPORT_INTERVAL//3600} 小時")
    
    # 檢查 Telegram 設定
    if not TG_TOKEN or not TG_CHAT_ID:
        print("\n⚠️ 警告: Telegram 未設定")
        print("   系統將以「僅監控模式」運行（無通知功能）")
        print("   如需啟用通知，請設定環境變數:")
        print("   - TG_TOKEN=你的Bot Token")
        print("   - TG_CHAT_ID=你的Chat ID")
        print("   💡 或啟用測試模式查看訊息內容: TEST_MODE=true")
        print("\n✅ 繼續運行...僅在終端機顯示監控資訊")
    else:
        print("✅ Telegram 已連接")
        
        # 發送啟動通知
        startup_msg = (
            f"🤖 <b>超級白銀哨兵已上線</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏱️  監控間隔: {CHECK_INTERVAL}s\n"
            f"📊 告警門檻: ±${PRICE_ALERT_THRESHOLD}\n"
            f"⏰ 報告間隔: {REPORT_INTERVAL//3600}h\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ 系統已就緒，開始監控..."
        )
        send_telegram(startup_msg)
    
    print("="*60)
    
    # --- 初始化狀態 ---
    state = MonitorState()
    
    # --- 初始化 CME 公告追蹤 ---
    print("\n[初始化] 建立 CME 公告資料庫...")
    last_seen_links = set()
    
    try:
        rss_url = (
            "https://news.google.com/rss/search?"
            "q=site:cmegroup.com+%22Silver%22+OR+%22Margin%22"
            "&hl=en-US&gl=US&ceid=US:en"
        )
        feed = feedparser.parse(rss_url)
        for entry in feed.entries:
            last_seen_links.add(entry.link)
        print(f"[初始化] 已載入 {len(last_seen_links)} 則歷史公告")
    except Exception as e:
        print(f"[初始化] 公告資料庫載入失敗: {e}")
    
    print(f"\n{'='*60}")
    print("🎯 開始雙重監控...\n")
    
    # --- 主監控迴圈 ---
    while True:
        try:
            last_seen_links = monitoring_cycle(state, last_seen_links)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ 收到中斷信號，正在關閉...")
            
            # 顯示統計資訊
            print(f"\n📊 運行統計:")
            print(f"   總檢查次數: {state.total_checks}")
            print(f"   成功率: {state.get_success_rate():.1f}%")
            print(f"   關閉時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 發送關閉通知（如果有設定 Telegram）
            if TG_TOKEN and TG_CHAT_ID:
                shutdown_msg = (
                    f"🛑 <b>系統已停止</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📊 總檢查次數: {state.total_checks}\n"
                    f"✅ 成功率: {state.get_success_rate():.1f}%\n"
                    f"⏰ 關閉時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                send_telegram(shutdown_msg)
            
            break
            
        except Exception as e:
            print(f"\n❌ 主迴圈錯誤: {e}")
            traceback.print_exc()
            
            # 嚴重錯誤告警
            if state.consecutive_failures > 10:
                error_msg = (
                    f"🔥 <b>系統異常</b>\n"
                    f"連續失敗超過 10 次\n"
                    f"錯誤: {str(e)[:200]}"
                )
                send_telegram(error_msg)
            
            time.sleep(10)  # 錯誤後等待較長時間
        
        # 清空輸出緩衝（Railway 需要）
        sys.stdout.flush()
        
        # 等待下次檢查
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
