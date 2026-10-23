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

# 跨平台音效處理
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# ==================== 設定區 ====================
TICKERS = ["0288.HK", "0303.HK", "0006.HK", "1211.HK", "3110.HK", "0700.HK"]
REFRESH_INTERVAL = 600  
CSV_LOG_FILE = "realtime_stock_cbbc_signals.csv"
SAVE_INTERACTIVE_CHARTS = True  

# Telegram Bot 設定 (請替換為你的 Token)
ENABLE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = "8680874924:AAGkX321FVoKiPgeqd79KWYRltEuwZkHMlM"
TELEGRAM_CHAT_ID = "7791139302"

# ================= 現倉設定區 ===================
# 輸入你目前持有的股票與買入價 (若無持倉請留空 {} 或不要填入該代碼)
# 系統將會以你的「買入價」來計算真實的未實現盈虧、動態止損 (Trailing SL) 與止盈 (TP)
CURRENT_POSITIONS = {
    "3110.HK": {"entry_price": 31.16, "shares": 1000},
    "0303.HK": {"entry_price": 50.38, "shares": 4000},
    "1211.HK": {"entry_price": 79.41, "shares":500},
    "0288.HK": {"entry_price": 7.25, "shares":4000},
}
# ================================================

previous_signals = {ticker: "HOLD" for ticker in TICKERS}

# 個股參數自適應設定
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

def save_interactive_chart(ticker, df):
    chart_df = df.copy()
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.48, 0.17, 0.17, 0.18],
        subplot_titles=(f"📈 {ticker} 狀態機與現倉分析圖", "RSI (14) 動能指標", "KD 隨機指標", "MACD (12, 26, 9)"),
    )

    fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df["Open"], high=chart_df["High"], low=chart_df["Low"], close=chart_df["Close"], name="陰陽燭", increasing_line_color="#00e676", decreasing_line_color="#ff334b"), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["SMA_20"], name="20日均線", line=dict(color="#00bcff", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["SMA_200"], name="200日均線", line=dict(color="#ffaa00", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Support_20L"], name="20日支撐位", line=dict(color="#ff00ff", width=1, dash="dash")), row=1, col=1)

    chart_df["Signal_Change"] = chart_df["Signal"] != chart_df["Signal"].shift(1)

    buy_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("BUY", na=False)]
    sell_all_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("SELL ALL", na=False)]
    take_profit_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("TAKE PROFIT", na=False)]
    setup_signals = chart_df[chart_df["Signal_Change"] & chart_df["Signal"].str.contains("SETUP", na=False)]

    if not buy_signals.empty:
        fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals["Low"] * 0.98, mode="markers", name="買入建倉", marker=dict(symbol="triangle-up", size=14, color="#00d2ff")), row=1, col=1)
    if not sell_all_signals.empty:
        fig.add_trace(go.Scatter(x=sell_all_signals.index, y=sell_all_signals["High"] * 1.02, mode="markers", name="強制平倉/止損", marker=dict(symbol="triangle-down", size=14, color="#ff334b")), row=1, col=1)
    if not take_profit_signals.empty:
        fig.add_trace(go.Scatter(x=take_profit_signals.index, y=take_profit_signals["High"] * 1.02, mode="markers", name="分批獲利了結", marker=dict(symbol="diamond", size=12, color="#b366ff")), row=1, col=1)
    if not setup_signals.empty:
        fig.add_trace(go.Scatter(x=setup_signals.index, y=setup_signals["Low"] * 0.98, mode="markers", name="準備觸發", marker=dict(symbol="circle-open", size=8, color="#ffff00")), row=1, col=1)

    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["RSI_14"], name="RSI(14)", line=dict(color="#b366ff", width=1.5)), row=2, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#00e676", row=2, col=1)

    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["K"], name="K線", line=dict(color="#00ffaa", width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["D"], name="D線", line=dict(color="#ffaa00", width=1.5)), row=3, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=3, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="#00e676", row=3, col=1)

    hist_colors = np.where(chart_df["MACD_Hist"] >= 0, "#00e676", "#ff334b")
    fig.add_trace(go.Bar(x=chart_df.index, y=chart_df["MACD_Hist"], name="MACD柱狀圖", marker_color=hist_colors, opacity=0.7), row=4, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MACD"], name="MACD快線", line=dict(color="#00d2ff", width=1.5)), row=4, col=1)
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["MACD_Signal"], name="Signal慢線", line=dict(color="#ffaa00", width=1.5)), row=4, col=1)

    fig.update_layout(template="plotly_dark", height=950, showlegend=True, xaxis_rangeslider_visible=False, hovermode="x unified")
    filename = f"{ticker}_interactive.html"
    fig.write_html(filename, include_plotlyjs="cdn")
    return filename

def analyze_stock(ticker):
    symbol_upper = ticker.upper()
    cfg = STOCK_CONFIGS.get(symbol_upper, DEFAULT_CONFIG)

    df = yf.download(ticker, period="2y", interval="1d", progress=False)
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
    df = df.tail(252)
    if len(df) < 2: return None, None

    df["MA_Death_Cross"] = (df["SMA_20"] < df["SMA_200"]) & (df["SMA_20"].shift(1) >= df["SMA_200"].shift(1))
    df["MACD_Death_Cross"] = (df["MACD"] < df["MACD_Signal"]) & (df["MACD"].shift(1) >= df["MACD_Signal"].shift(1))
    df["MACD_Golden_Cross"] = (df["MACD"] > df["MACD_Signal"]) & (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
    df["KD_Golden_Cross"] = (df["K"] > df["D"]) & (df["K"].shift(1) <= df["D"].shift(1))

    scores, signals = [], []

    # 技術面狀態機初始化
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

    # 當前最新統計
    latest = df.iloc[-1]
    current_price = float(latest["Close"])
    atr_val = float(latest["ATR_14"])
    support_20l = float(latest["Support_20L"])
    ta_signal = latest["Signal"]

    # ================= 現倉盈虧與動態 SL/TP 覆蓋邏輯 =================
    pos = CURRENT_POSITIONS.get(symbol_upper)
    if pos:
        entry_p = pos["entry_price"]
        pnl_pct = ((current_price - entry_p) / entry_p) * 100
        pnl_str = f"{pnl_pct:+.2f}%"
        
        # 結合買入價的固定止損與現價的移動止損，取較高者保護利潤
        fixed_sl = entry_p - (cfg["atr_mult"] * atr_val)
        trailing_sl = current_price - (cfg["atr_mult"] * atr_val)
        est_sl = round(max(fixed_sl, trailing_sl), 2)
        est_tp = round(entry_p + (3.0 * atr_val), 2)  # 基於成本價推算 3R 止盈
        
        # 若現倉跌破/突破風控線，覆蓋技術面訊號
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

    # ================= 牛熊證 (CBBC) 風控計算 =================
    estimated_bull_call = round(support_20l * 0.99, 2)
    distance_to_call_pct = round(((current_price - estimated_bull_call) / current_price) * 100, 2)

    if distance_to_call_pct < 2.0:
        cbbc_risk = "🔥 極高風險"
    elif distance_to_call_pct <= 5.0:
        cbbc_risk = "⚠️ 中等風險"
    else:
        cbbc_risk = "🛡️ 低風險"

    # 交叉狀態
    cross_status = "無"
    if latest["MA_Death_Cross"]: cross_status = "💀 MA死叉"
    elif latest["MACD_Death_Cross"]: cross_status = "📉 MACD死叉"
    elif latest["MACD_Golden_Cross"]: cross_status = "📊 MACD金叉"
    elif latest["KD_Golden_Cross"]: cross_status = "✨ KD金叉"

    res_dict = {
        "時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "股票代碼": symbol_upper,
        "最新現價": round(current_price, 2),
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
    print("=" * 110)
    print("🚀 整合現倉盈虧、分批獲利狀態機與 CBBC 風控監控系統 啟動中...")
    print(f"📌 監控目標: {', '.join(TICKERS)}")
    print("=" * 110 + "\n")

    # ====== 啟動時發送 Telegram 通知 ======
    send_telegram_message(f"🚀 *整合現倉與 CBBC 風控監控系統已成功啟動*\n監控目標: {', '.join(TICKERS)}")

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

                # Telegram 警報：訊號改變、現倉觸發止損/止盈、或牛證極高風險時觸發
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
                        f"*{alert_icon} - {ticker}*\n"
                        f"現價: ${res['最新現價']} | 持倉成本: ${res['持倉成本']} ({res['盈虧(%)']})\n"
                        f"評分: {res['評分(Score)']} | 交叉: {res['交叉狀態']}\n"
                        f"SL: ${res['估算止損(SL)']} | TP: ${res['估算止盈(TP)']}\n"
                        f"CBBC距收回價: {res['距收回價(%)']} ({res['CBBC風險']})\n"
                        f"訊號: {current_signal}"
                    )
                    print(f"\n{alert_icon}: {ticker}")
                    if HAS_WINSOUND: winsound.Beep(0, 0)
                    send_telegram_message(msg)
                    if chart_filename: send_telegram_document(chart_filename, f"{ticker} 分析圖表")

                previous_signals[ticker] = current_signal

            # 在終端機印出所有指定的欄位，包含現倉盈虧與 CBBC 資訊
            if current_results:
                res_df = pd.DataFrame(current_results)
                cols_to_show = [
                    "股票代碼", "最新現價", "持倉成本", "盈虧(%)", "評分(Score)", 
                    "估算止損(SL)", "估算止盈(TP)", "RSI(14)", "MACD", 
                    "交叉狀態", "訊號"
                ]
                print(res_df[cols_to_show].to_string(index=False))
                
                # 將完整結果寫入 CSV
                file_exists = os.path.exists(CSV_LOG_FILE)
                res_df.to_csv(
                    CSV_LOG_FILE,
                    mode="a",
                    header=not file_exists,
                    index=False,
                    encoding="utf-8-sig"
                )
                
            time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            print("\n👋 監控程式已手動停止。")
            # ====== 結束時發送 Telegram 通知 ======
            send_telegram_message("🛑 *監控系統已手動停止*")
            break
        except Exception as e:
            print(f"⚠️ 異常: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()