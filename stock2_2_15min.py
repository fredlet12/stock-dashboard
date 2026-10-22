import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import yfinance as yf
import subprocess

# 跨平台音效處理
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# ==================== 設定區 ====================
TICKERS = ["0288.HK", "0303.HK", "0006.HK", "1211.HK", "3110.HK", "0700.HK"]
REFRESH_INTERVAL = 300  
CSV_LOG_FILE = "realtime_stock_cbbc_signals_15m.csv"
SAVE_INTERACTIVE_CHARTS = True  

# Telegram Bot 設定 (請替換為你的 Token)
ENABLE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = "8680874924:AAGkX321FVoKiPgeqd79KWYRltEuwZkHMlM"
TELEGRAM_CHAT_ID = "7791139302"

# ================= 現倉設定區 ===================
CURRENT_POSITIONS = {
    "3110.HK": {"entry_price": 31.16, "shares": 1000},
    "0303.HK": {"entry_price": 50.38, "shares": 4000},
    "1211.HK": {"entry_price": 79.41, "shares":500},
    "0288.HK": {"entry_price": 7.25, "shares":4000},
}
# ================================================

previous_signals = {ticker: "HOLD" for ticker in TICKERS}

STOCK_CONFIGS = {
    "0288.HK": {"atr_mult": 1.5, "rsi_oversold": 35, "rsi_overbought": 75, "kd_oversold": 25, "weight_kd_support": 1.2},
    "0303.HK": {"atr_mult": 1.5, "rsi_oversold": 35, "rsi_overbought": 75, "kd_oversold": 20, "weight_kd_support": 1.0},
    "0006.HK": {"atr_mult": 1.0, "rsi_oversold": 30, "rsi_overbought": 70, "kd_oversold": 20, "weight_kd_support": 1.0},
    "1211.HK": {"atr_mult": 2.0, "rsi_oversold": 40, "rsi_overbought": 80, "kd_oversold": 30, "weight_kd_support": 0.8},
    "3110.HK": {"atr_mult": 1.5, "rsi_oversold": 35, "rsi_overbought": 75, "kd_oversold": 20, "weight_kd_support": 1.0},
    "0700.HK": {"atr_mult": 2.0, "rsi_oversold": 35, "rsi_overbought": 80, "kd_oversold": 25, "weight_kd_support": 1.0},
    "03690.HK": {"atr_mult": 2.5, "rsi_oversold": 30, "rsi_overbought": 82, "kd_oversold": 20, "weight_kd_support": 0.8}
}
DEFAULT_CONFIG = {"atr_mult": 1.5, "rsi_oversold": 35, "rsi_overbought": 75, "kd_oversold": 20, "weight_kd_support": 1.0}

def send_telegram_message(message):
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, data=payload, timeout=10)
    except Exception as e: print(f"⚠️ Telegram 訊息發送失敗: {e}")

def send_telegram_document(file_path, caption=""):
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as doc:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"document": doc}, timeout=30)
    except Exception as e: print(f"⚠️ Telegram 檔案發送逾時或失敗: {e}")

def generate_dashboard(tickers):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-HK">
    <head>
        <meta charset="UTF-8">
        <title>量化監控儀表板 (15m)</title>
        <style>
            body {{ background-color: #111; color: #fff; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .header h1 {{ margin: 0 0 10px 0; color: #00e676; }}
            .header p {{ margin: 0; color: #aaa; font-size: 14px; }}
            .grid-container {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(700px, 1fr));
                gap: 20px;
            }}
            iframe {{
                width: 100%;
                height: 1050px;
                border: 1px solid #333;
                border-radius: 8px;
                background-color: #000;
            }}
        </style>
        <script>
            const refreshInterval = {REFRESH_INTERVAL * 1000}; 
            setInterval(function() {{
                const iframes = document.querySelectorAll('iframe');
                iframes.forEach(iframe => {{
                    const currentSrc = iframe.src.split('?')[0];
                    iframe.src = currentSrc + '?t=' + new Date().getTime();
                }});
                document.getElementById('last-update').innerText = '最後更新時間: ' + new Date().toLocaleTimeString();
            }}, refreshInterval);
        </script>
    </head>
    <body>
        <div class="header">
            <h1>📈 港股量化監控儀表板 (15m 線 + 成交量)</h1>
            <p id="last-update">等待首次更新...</p>
            <p style="margin-top:5px; font-size:12px; color:#666;">(系統將每 {REFRESH_INTERVAL} 秒自動在背景刷新圖表)</p>
        </div>
        <div class="grid-container">
    """
    
    for ticker in tickers:
        filename = f"{ticker}_interactive_15m.html"
        html_content += f'            <div><iframe src="{filename}"></iframe></div>\n'

    html_content += """
        </div>
        <script>
            document.getElementById('last-update').innerText = '最後更新時間: ' + new Date().toLocaleTimeString();
        </script>
    </body>
    </html>
    """
    
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ 已生成綜合儀表板: dashboard.html")

def save_interactive_chart(ticker, df):
    chart_df = df.copy()
    chart_df['Datetime_Str'] = chart_df.index.strftime('%Y-%m-%d %H:%M')
    
    # 擴增為 5 個副圖
    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.40, 0.15, 0.15, 0.15, 0.15],
        subplot_titles=(f"📈 {ticker} 15分鐘線圖 (Scale-out 現倉監控)", "成交量 (Volume)", "RSI (14) 動能指標", "KD 隨機指標", "MACD (12, 26, 9)"),
    )

    # Row 1: 陰陽燭與均線
    fig.add_trace(go.Candlestick(x=chart_df['Datetime_Str'], open=chart_df["Open"], high=chart_df["High"], low=chart_df["Low"], close=chart_df["Close"], name="15m K線", increasing_line_color="#00e676", decreasing_line_color="#ff334b"), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["SMA_20"], name="20T均線", line=dict(color="#00bcff", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["SMA_200"], name="200T均線", line=dict(color="#ffaa00", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["Support_20L"], name="20T支撐位", line=dict(color="#ff00ff", width=1, dash="dash")), row=1, col=1)

    chart_df["Signal_Change"] = chart_df["Signal"] != chart_df["Signal"].shift(1)
    buy_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("BUY", na=False)]
    sell_all_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("SELL ALL", na=False)]
    take_profit_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("TAKE PROFIT", na=False)]
    setup_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("SETUP", na=False)]

    if not buy_signals.empty: fig.add_trace(go.Scatter(x=buy_signals['Datetime_Str'], y=buy_signals["Low"] * 0.98, mode="markers", name="買入建倉", marker=dict(symbol="triangle-up", size=14, color="#00d2ff")), row=1, col=1)
    if not sell_all_signals.empty: fig.add_trace(go.Scatter(x=sell_all_signals['Datetime_Str'], y=sell_all_signals["High"] * 1.02, mode="markers", name="強制平倉/止損", marker=dict(symbol="triangle-down", size=14, color="#ff334b")), row=1, col=1)
    if not take_profit_signals.empty: fig.add_trace(go.Scatter(x=take_profit_signals['Datetime_Str'], y=take_profit_signals["High"] * 1.02, mode="markers", name="分批獲利了結", marker=dict(symbol="diamond", size=12, color="#b366ff")), row=1, col=1)
    if not setup_signals.empty: fig.add_trace(go.Scatter(x=setup_signals['Datetime_Str'], y=setup_signals["Low"] * 0.98, mode="markers", name="準備觸發", marker=dict(symbol="circle-open", size=8, color="#ffff00")), row=1, col=1)

    # Row 2: 成交量 (Volume)
    vol_colors = np.where(chart_df["Close"] >= chart_df["Open"], "#00e676", "#ff334b")
    fig.add_trace(go.Bar(x=chart_df['Datetime_Str'], y=chart_df["Volume"], name="成交量", marker_color=vol_colors, opacity=0.8), row=2, col=1)

    # Row 3: RSI
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["RSI_14"], name="RSI(14)", line=dict(color="#b366ff", width=1.5)), row=3, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#00e676", row=3, col=1)

    # Row 4: KD
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["K"], name="K線", line=dict(color="#00ffaa", width=1.5)), row=4, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["D"], name="D線", line=dict(color="#ffaa00", width=1.5)), row=4, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=4, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="#00e676", row=4, col=1)

    # Row 5: MACD
    hist_colors = np.where(chart_df["MACD_Hist"] >= 0, "#00e676", "#ff334b")
    fig.add_trace(go.Bar(x=chart_df['Datetime_Str'], y=chart_df["MACD_Hist"], name="MACD柱狀圖", marker_color=hist_colors, opacity=0.7), row=5, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["MACD"], name="MACD快線", line=dict(color="#00d2ff", width=1.5)), row=5, col=1)
    fig.add_trace(go.Scatter(x=chart_df['Datetime_Str'], y=chart_df["MACD_Signal"], name="Signal慢線", line=dict(color="#ffaa00", width=1.5)), row=5, col=1)

    fig.update_xaxes(type='category', showticklabels=False, row=1, col=1)
    fig.update_xaxes(type='category', showticklabels=False, row=2, col=1)
    fig.update_xaxes(type='category', showticklabels=False, row=3, col=1)
    fig.update_xaxes(type='category', showticklabels=False, row=4, col=1)
    fig.update_xaxes(type='category', showticklabels=True, row=5, col=1, nticks=10) 

    # 調整圖表高度至 1050 確保 5 行顯示舒適
    fig.update_layout(template="plotly_dark", height=1050, showlegend=True, xaxis_rangeslider_visible=False, hovermode="x unified")
    filename = f"{ticker}_interactive_15m.html"
    fig.write_html(filename, include_plotlyjs="cdn")
    return filename

def analyze_stock(ticker):
    symbol_upper = ticker.upper()
    cfg = STOCK_CONFIGS.get(symbol_upper, DEFAULT_CONFIG)

    df = yf.download(ticker, period="60d", interval="15m", progress=False)
    if df.empty: return None, None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

    df["SMA_20"] = ta.sma(df["Close"], length=20)
    df["SMA_200"] = ta.sma(df["Close"], length=200)
    df["SMA_20_Slope"] = df["SMA_20"].diff(3)
    df["RSI_14"] = ta.rsi(df["Close"], length=14)
    df["ATR_14"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["Support_20L"] = df["Low"].rolling(window=20).min()

    stoch = ta.stoch(df["High"], df["Low"], df["Close"], k=14, d=3, smooth_k=3)
    if stoch is not None:
        df["K"] = stoch["STOCHk_14_3_3"]
        df["D"] = stoch["STOCHd_14_3_3"]
    else: return None, None

    macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd is not None:
        df["MACD"] = macd["MACD_12_26_9"]
        df["MACD_Signal"] = macd["MACDs_12_26_9"]
        df["MACD_Hist"] = macd["MACDh_12_26_9"]
    else: return None, None

    df.dropna(inplace=True)
    df = df.tail(400)
    if len(df) < 2: return None, None

    df["MA_Death_Cross"] = (df["SMA_20"] < df["SMA_200"]) & (df["SMA_20"].shift(1) >= df["SMA_200"].shift(1))
    df["MACD_Death_Cross"] = (df["MACD"] < df["MACD_Signal"]) & (df["MACD"].shift(1) >= df["MACD_Signal"].shift(1))
    df["MACD_Golden_Cross"] = (df["MACD"] > df["MACD_Signal"]) & (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
    df["KD_Golden_Cross"] = (df["K"] > df["D"]) & (df["K"].shift(1) <= df["D"].shift(1))

    scores, signals = [], []

    STATE_IDLE = 0            
    STATE_SETUP_ACTIVE = 1    
    STATE_FULL_POS = 2        
    STATE_HALF_POS = 3        

    current_state = STATE_IDLE
    bars_since_setup = 0
    MAX_SETUP_WINDOW = 5

    for i in range(len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1] if i > 0 else row

        score = 0.0
        if row["Close"] > row["SMA_200"]: score += 20
        if row["SMA_20_Slope"] > 0: score += 10
        if row["RSI_14"] < cfg["rsi_oversold"]: score += 20
        if row["KD_Golden_Cross"] and row["K"] < cfg["kd_oversold"]: score += 20 * cfg["weight_kd_support"]
        if row["MACD_Golden_Cross"]: score += 20
        
        setup_condition = (row["RSI_14"] < cfg["rsi_oversold"]) or ((row["Close"] - row["Support_20L"]) / (row["Support_20L"] + 1e-9) <= 0.015)
        trigger_condition = row["MACD_Golden_Cross"] or row["KD_Golden_Cross"]
        break_support = row["Close"] < prev_row["Support_20L"]
        hard_exit_condition = break_support or row["MA_Death_Cross"] or row["MACD_Death_Cross"]
        rsi_exhaustion = (prev_row["RSI_14"] >= cfg["rsi_overbought"]) and (row["RSI_14"] < prev_row["RSI_14"])
        price_spike = ((row["Close"] - row["SMA_20"]) / row["SMA_20"]) >= 0.08 
        take_profit_condition = rsi_exhaustion or price_spike
        
        sig = "持有/觀望 (HOLD)"

        if current_state == STATE_IDLE:
            if setup_condition:
                current_state = STATE_SETUP_ACTIVE
                bars_since_setup = 0
                sig = "持有/準備 (SETUP)"
        elif current_state == STATE_SETUP_ACTIVE:
            if setup_condition:
                bars_since_setup = 0
                sig = "持有/準備 (SETUP)"
            else:
                bars_since_setup += 1
                sig = "持有/準備 (SETUP)"

            if trigger_condition:
                current_state = STATE_FULL_POS
                sig = "買入/建倉 (BUY)"
            elif bars_since_setup > MAX_SETUP_WINDOW:
                current_state = STATE_IDLE  
                sig = "持有/觀望 (HOLD)"
        elif current_state == STATE_FULL_POS:
            if hard_exit_condition:
                current_state = STATE_IDLE
                sig = "全數平倉/止損 (SELL ALL)"  
            elif take_profit_condition:
                current_state = STATE_HALF_POS
                sig = "獲利減倉 50% (TAKE PROFIT)" 
        elif current_state == STATE_HALF_POS:
            if hard_exit_condition:
                current_state = STATE_IDLE
                sig = "全數平倉 (SELL ALL)"      
            else:
                sig = "持有/半倉 (HOLD HALF)"

        scores.append(round(score, 1))
        signals.append(sig)

    df["Score"] = scores
    df["Signal"] = signals

    latest = df.iloc[-1]
    current_price = float(latest["Close"])
    current_volume = int(latest.get("Volume", 0))
    atr_val = float(latest["ATR_14"])
    support_20l = float(latest["Support_20L"])
    ta_signal = latest["Signal"]

    pos = CURRENT_POSITIONS.get(symbol_upper)
    if pos:
        entry_p = pos["entry_price"]
        pnl_pct = ((current_price - entry_p) / entry_p) * 100
        pnl_str = f"{pnl_pct:+.2f}%"
        
        fixed_sl = entry_p - (cfg["atr_mult"] * atr_val)
        trailing_sl = current_price - (cfg["atr_mult"] * atr_val)
        est_sl = round(max(fixed_sl, trailing_sl), 2)
        est_tp = round(entry_p + (3.0 * atr_val), 2)  
        
        if current_price <= est_sl:
            final_signal = "🛑 現倉觸發止損/移動止盈 (SELL ALL)"
        elif current_price >= est_tp:
            final_signal = "💰 現倉觸發目標止盈 (TAKE PROFIT)"
        else:
            final_signal = f"🛡️ 持有現倉 (TA: {ta_signal.split(' ')[0]})"
    else:
        entry_p = "-"
        pnl_str = "-"
        est_sl = round(current_price - (cfg["atr_mult"] * atr_val), 2)
        est_tp = round(current_price + (3.0 * atr_val), 2)
        final_signal = ta_signal

    estimated_bull_call = round(support_20l * 0.99, 2)
    distance_to_call_pct = round(((current_price - estimated_bull_call) / current_price) * 100, 2)

    if distance_to_call_pct < 2.0:
        cbbc_risk = "🔥 極高風險"
    elif distance_to_call_pct <= 5.0:
        cbbc_risk = "⚠️ 中等風險"
    else:
        cbbc_risk = "🛡️ 低風險"

    cross_status = "無"
    if latest["MA_Death_Cross"]: cross_status = "💀 MA死叉"
    elif latest["MACD_Death_Cross"]: cross_status = "📉 MACD死叉"
    elif latest["MACD_Golden_Cross"]: cross_status = "📊 MACD金叉"
    elif latest["KD_Golden_Cross"]: cross_status = "✨ KD金叉"

    res_dict = {
        "時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "股票代碼": symbol_upper,
        "最新現價": round(current_price, 2),
        "成交量": f"{current_volume:,}",
        "持倉成本": entry_p,
        "盈虧(%)": pnl_str,
        "評分(Score)": latest["Score"],
        "估算止損(SL)": est_sl,
        "估算止盈(TP)": est_tp,
        "RSI(14)": round(float(latest["RSI_14"]), 2),
        "MACD": round(float(latest["MACD"]), 2),
        "交叉狀態": cross_status,
        "訊號": final_signal,
        "距收回價(%)": f"{distance_to_call_pct}%",
        "CBBC風險": cbbc_risk
    }
    return res_dict, df

def main():
    print("=" * 120)
    print("🚀 15 分鐘線 (15m) 現倉盈虧、成交量與 CBBC 風控系統 啟動中...")
    print(f"📌 監控目標: {', '.join(TICKERS)}")
    print("=" * 120 + "\n")

    if SAVE_INTERACTIVE_CHARTS:
        generate_dashboard(TICKERS)

    send_telegram_message(f"🚀 *15m 監控系統 (含成交量) 已成功啟動*\n監控目標: {', '.join(TICKERS)}")

    while True:
        try:
            current_results = []
            for ticker in TICKERS:
                res, df_data = analyze_stock(ticker)
                if not res: continue
                current_results.append(res)
                
                chart_filename = save_interactive_chart(ticker, df_data) if SAVE_INTERACTIVE_CHARTS else None
                current_signal = res["訊號"]
                prev_signal = previous_signals.get(ticker, "HOLD")
                cbbc_alert = res["CBBC風險"]

                alert_triggered = False
                if current_signal != prev_signal and "HOLD" not in current_signal and "續抱" not in current_signal and "持有現倉" not in current_signal:
                    alert_triggered = True
                elif "極高風險" in cbbc_alert:
                    alert_triggered = True

                if alert_triggered:
                    if "BUY" in current_signal: alert_icon = "🚨 買入建倉"
                    elif "TAKE PROFIT" in current_signal or "觸發目標止盈" in current_signal: alert_icon = "💰 獲利了結"
                    elif "SELL ALL" in current_signal or "觸發止損" in current_signal: alert_icon = "🛑 強制平倉/止損"
                    elif "SETUP" in current_signal: alert_icon = "👀 準備觸發"
                    elif "極高風險" in cbbc_alert: alert_icon = "🔥 CBBC 收回高危"
                    else: alert_icon = "⚠️ 狀態更新"

                    msg = (
                        f"*{alert_icon} - {ticker} (15m)*\n"
                        f"現價: ${res['最新現價']} | 成交量: {res['成交量']}\n"
                        f"持倉成本: {res['持倉成本']} ({res['盈虧(%)']})\n"
                        f"評分: {res['評分(Score)']} | 交叉: {res['交叉狀態']}\n"
                        f"SL: ${res['估算止損(SL)']} | TP: ${res['估算止盈(TP)']}\n"
                        f"CBBC距收回價: {res['距收回價(%)']} ({res['CBBC風險']})\n"
                        f"訊號: {current_signal}"
                    )
                    print(f"\n{alert_icon}: {ticker}")
                    if HAS_WINSOUND: winsound.Beep(1000, 1000)
                    send_telegram_message(msg)
                    if chart_filename: send_telegram_document(chart_filename, f"{ticker} 15m 分析圖表")

                previous_signals[ticker] = current_signal

            if current_results:
                res_df = pd.DataFrame(current_results)
                cols_to_show = [
                    "股票代碼", "最新現價", "成交量", "持倉成本", "盈虧(%)", "評分(Score)", 
                    "估算止損(SL)", "估算止盈(TP)", "RSI(14)", "MACD", 
                    "交叉狀態", "訊號", "距收回價(%)", "CBBC風險"
                ]
                print(res_df[cols_to_show].to_string(index=False))
                
                file_exists = os.path.exists(CSV_LOG_FILE)
                res_df.to_csv(
                    CSV_LOG_FILE,
                    mode="a",
                    header=not file_exists,
                    index=False,
                    encoding="utf-8-sig"
                )
            
            # 自動推送到 GitHub Pages (供 Google Sites 抓取)
            try:
                print("🔄 正在將最新圖表同步至 GitHub Pages...")
                subprocess.run(["git", "add", "*.html", "*.csv"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                commit_msg = f"Auto update: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                subprocess.run(["git", "commit", "-m", commit_msg], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "push"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("✅ 成功同步至網頁伺服器！")
            except Exception as e:
                print(f"⚠️ Git 同步狀態 (可能無新變更或尚未綁定 Git): {e}")

            time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            print("\n👋 監控程式已手動停止。")
            send_telegram_message("🛑 *15m 監控系統已手動停止*")
            break
        except Exception as e:
            print(f"⚠️ 異常: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()