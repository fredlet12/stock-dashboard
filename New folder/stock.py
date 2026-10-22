import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from datetime import datetime
import os
import requests

# 跨平台音效處理
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# 引入 Plotly 互動式圖表模組
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==================== 設定區 ====================
TICKERS = ["0303.HK", "2388.HK", "1211.HK", "3110.HK","0288.hk"]
REFRESH_INTERVAL = 360  # 檢查頻率（秒）
CSV_LOG_FILE = "realtime_stock_signals.csv"
SAVE_INTERACTIVE_CHARTS = True

# Telegram 推播設定
ENABLE_TELEGRAM = True  # 開啟/關閉 Telegram 推播功能
TELEGRAM_BOT_TOKEN = "8680874924:AAGkX321FVoKiPgeqd79KWYRltEuwZkHMlM"
TELEGRAM_CHAT_ID = "7791139302"
# ================================================

previous_signals = {ticker: "HOLD" for ticker in TICKERS}

def send_telegram_message(message):
    """發送 Telegram 文字訊息"""
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Telegram 訊息發送失敗: {e}")

def send_telegram_document(file_path, caption=""):
    """發送 HTML 互動圖表檔案至 Telegram"""
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as doc:
            files = {'document': doc}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
            requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print(f"⚠️ Telegram 檔案發送失敗: {e}")

def save_interactive_chart(ticker, df):
    """繪製並儲存包含 4 個面板 (陰陽燭, RSI, KD, MACD) 的 Plotly 互動式 HTML 圖表"""
    chart_df = df.tail(120).copy()

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.48, 0.17, 0.17, 0.18],
        subplot_titles=(f"📈 {ticker} 互動式技術分析走勢圖", "RSI (14) 動能指標", "KD 隨機指標", "MACD (12, 26, 9)")
    )

    # 1. 陰陽燭 (升:綠, 跌:紅)
    fig.add_trace(
        go.Candlestick(
            x=chart_df.index,
            open=chart_df['Open'],
            high=chart_df['High'],
            low=chart_df['Low'],
            close=chart_df['Close'],
            name='陰陽燭',
            increasing_line_color='#00e676',
            decreasing_line_color='#ff334b'
        ),
        row=1, col=1
    )

    # 均線與支撐位
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['SMA_20'], name='20日均線', line=dict(color='#00bcff', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['SMA_200'], name='200日均線', line=dict(color='#ffaa00', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Support_20L'], name='20日支撐位', line=dict(color='#ff00ff', width=1, dash='dash')), row=1, col=1)

    # 買賣訊號點 (買入:亮藍, 賣出:橙色)
    buy_signals = chart_df[chart_df['Signal'] == '買入 (BUY)']
    sell_signals = chart_df[chart_df['Signal'] == '賣出/止損 (SELL)']

    if not buy_signals.empty:
        fig.add_trace(go.Scatter(
            x=buy_signals.index, y=buy_signals['Close'],
            mode='markers', name='買入訊號',
            marker=dict(symbol='triangle-up', size=13, color='#00d2ff')
        ), row=1, col=1)

    if not sell_signals.empty:
        fig.add_trace(go.Scatter(
            x=sell_signals.index, y=sell_signals['Close'],
            mode='markers', name='賣出訊號',
            marker=dict(symbol='triangle-down', size=13, color='#ff9900')
        ), row=1, col=1)

    # 2. RSI
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['RSI_14'], name='RSI(14)', line=dict(color='#b366ff', width=1.5)), row=2, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=2, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="gray", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#00e676", row=2, col=1)

    # 3. KD
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['K'], name='K線', line=dict(color='#00ffaa', width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['D'], name='D線', line=dict(color='#ffaa00', width=1.5)), row=3, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=3, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="#00e676", row=3, col=1)

    # 4. MACD
    hist_colors = np.where(chart_df['MACD_Hist'] >= 0, '#00e676', '#ff334b')
    fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['MACD_Hist'], name='MACD柱狀圖', marker_color=hist_colors, opacity=0.7), row=4, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MACD'], name='MACD快線', line=dict(color='#00d2ff', width=1.5)), row=4, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MACD_Signal'], name='Signal慢線', line=dict(color='#ffaa00', width=1.5)), row=4, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=4, col=1)

    fig.update_layout(
        template='plotly_dark',
        height=950,
        showlegend=True,
        xaxis_rangeslider_visible=False,
        hovermode='x unified'
    )

    filename = f"{ticker}_interactive.html"
    fig.write_html(filename, include_plotlyjs='cdn')
    return filename

def analyze_stock(ticker):
    df = yf.download(ticker, period="1y", interval="1d", progress=False)
    if df.empty:
        return None, None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 計算技術指標
    df['SMA_20'] = ta.sma(df['Close'], length=20)
    df['SMA_200'] = ta.sma(df['Close'], length=200)
    df['RSI_14'] = ta.rsi(df['Close'], length=14)

    stoch = ta.stoch(df['High'], df['Low'], df['Close'], k=14, d=3, smooth_k=3)
    if stoch is not None and not stoch.empty:
        df['K'] = stoch['STOCHk_14_3_3']
        df['D'] = stoch['STOCHd_14_3_3']
    else:
        return None, None

    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None and not macd.empty:
        df['MACD'] = macd['MACD_12_26_9']
        df['MACD_Signal'] = macd['MACDs_12_26_9']
        df['MACD_Hist'] = macd['MACDh_12_26_9']
    else:
        return None, None

    df['VOL_SMA_20'] = ta.sma(df['Volume'], length=20)
    df['Support_20L'] = df['Low'].rolling(window=20).min()

    df.dropna(inplace=True)
    if len(df) < 2:
        return None, None

    # 交叉計算
    df['MA_Golden_Cross'] = (df['SMA_20'] > df['SMA_200']) & (df['SMA_20'].shift(1) <= df['SMA_200'].shift(1))
    df['MA_Death_Cross'] = (df['SMA_20'] < df['SMA_200']) & (df['SMA_20'].shift(1) >= df['SMA_200'].shift(1))
    df['KD_Golden_Cross'] = (df['K'] > df['D']) & (df['K'].shift(1) <= df['D'].shift(1))
    df['KD_Death_Cross'] = (df['K'] < df['D']) & (df['K'].shift(1) >= df['D'].shift(1))
    df['MACD_Golden_Cross'] = (df['MACD'] > df['MACD_Signal']) & (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))
    df['MACD_Death_Cross'] = (df['MACD'] < df['MACD_Signal']) & (df['MACD'].shift(1) >= df['MACD_Signal'].shift(1))

    # 買賣條件
    cond_buy = (
        df['MA_Golden_Cross'] |
        df['MACD_Golden_Cross'] |
        (df['KD_Golden_Cross'] & (df['K'] < 50) & (df['Close'] > df['SMA_200'])) |
        ((df['Close'] > df['SMA_200']) & (df['Close'] > df['SMA_20']) & (df['RSI_14'] > 50) & (df['RSI_14'] < 70) & (df['Volume'] > df['VOL_SMA_20'] * 1.5))
    )

    cond_sell = (
        df['MA_Death_Cross'] |
        df['MACD_Death_Cross'] |
        (df['KD_Death_Cross'] & (df['K'] > 70)) |
        (df['Close'] < df['Support_20L']) |
        (df['RSI_14'] > 80)
    )

    conditions = [cond_buy, cond_sell]
    choices = ['買入 (BUY)', '賣出/止損 (SELL)']
    df['Signal'] = np.select(conditions, choices, default='持有/觀望 (HOLD)')

    latest = df.iloc[-1]

    cross_status = "無"
    if latest['MA_Golden_Cross']:
        cross_status = "🌟 MA黃金交叉"
    elif latest['MA_Death_Cross']:
        cross_status = "💀 MA死亡交叉"
    elif latest['MACD_Golden_Cross']:
        cross_status = "📊 MACD黃金交叉"
    elif latest['MACD_Death_Cross']:
        cross_status = "📉 MACD死亡交叉"
    elif latest['KD_Golden_Cross']:
        cross_status = "✨ KD黃金交叉"
    elif latest['KD_Death_Cross']:
        cross_status = "☠️ KD死亡交叉"

    res_dict = {
        '時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '股票代碼': ticker,
        '最新現價': round(float(latest['Close']), 2),
        '200天線': round(float(latest['SMA_200']), 2),
        'RSI(14)': round(float(latest['RSI_14']), 2),
        'K值': round(float(latest['K']), 1),
        'D值': round(float(latest['D']), 1),
        'MACD': round(float(latest['MACD']), 2),
        '交叉狀態': cross_status,
        '訊號': latest['Signal']
    }
    
    return res_dict, df

def main():
    print("=" * 75)
    print(f"🚀 股票即時監控系統 (整合 Telegram Bot 自動推播)")
    print(f"📌 監控目標: {', '.join(TICKERS)}")
    print(f"⏱️ 刷新頻率: 每 {REFRESH_INTERVAL} 秒")
    print("按下 Ctrl + C 可終止程式")
    print("=" * 75 + "\n")

    send_telegram_message("🚀 *股票監控系統已成功啟動* \n監控目標: " + ", ".join(TICKERS))

    while True:
        try:
            current_results = []
            now_str = datetime.now().strftime('%H:%M:%S')
            print(f"[{now_str}] 正在進行行情掃描...")

            for ticker in TICKERS:
                res, df_data = analyze_stock(ticker)
                if res and df_data is not None:
                    current_results.append(res)
                    
                    chart_filename = None
                    if SAVE_INTERACTIVE_CHARTS:
                        chart_filename = save_interactive_chart(ticker, df_data)

                    current_signal = res['訊號']
                    prev_signal = previous_signals.get(ticker, "HOLD")

                    # 當訊號從【觀望】轉變為【買入】或【賣出】時發送 Telegram 推播
                    if current_signal != prev_signal and current_signal != '持有/觀望 (HOLD)':
                        alert_icon = "🚨 買入警報" if current_signal == '買入 (BUY)' else "⚠️ 賣出/止損警報"
                        msg = (
                            f"*{alert_icon} - {ticker}*\n"
                            f"-----------------------------\n"
                            f"💰 *最新現價:* ${res['最新現價']}\n"
                            f"📈 *200天線:* ${res['200天線']}\n"
                            f"⚡ *RSI(14):* {res['RSI(14)']}\n"
                            f"📊 *MACD:* {res['MACD']}\n"
                            f"🔀 *交叉狀態:* {res['交叉狀態']}\n"
                            f"🎯 *訊號:* {current_signal}\n"
                            f"⏰ *時間:* {res['時間']}"
                        )
                        print(f"\n{alert_icon}: {ticker}")
                        if HAS_WINSOUND:
                            winsound.Beep(1000, 1000)
                        
                        # 發送 Telegram 訊息與互動圖表檔案
                        send_telegram_message(msg)
                        if chart_filename and os.path.exists(chart_filename):
                            send_telegram_document(chart_filename, caption=f"{ticker} 互動式圖表")

                    previous_signals[ticker] = current_signal

            if current_results:
                res_df = pd.DataFrame(current_results)
                cols_to_show = ['股票代碼', '最新現價', '200天線', 'RSI(14)', 'K值', 'D值', 'MACD', '交叉狀態', '訊號']
                print(res_df[cols_to_show].to_string(index=False))

                file_exists = os.path.exists(CSV_LOG_FILE)
                res_df.to_csv(CSV_LOG_FILE, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')

            print(f"倒數 {REFRESH_INTERVAL} 秒後進行下次掃描...\n" + "-" * 60)
            time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            print("\n👋 監控程式已手動停止。")
            send_telegram_message("🛑 *股票監控系統已手動停止*")
            break
        except Exception as e:
            print(f"⚠️ 執行過程發生異常: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()