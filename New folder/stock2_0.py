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

# 跨平台音效處理 (Windows 使用 winsound，其餘系統退回蜂鳴提示)
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# ==================== 設定區 ====================
TICKERS = ["0288.HK", "0303.HK", "0006.HK", "1211.HK", "3110.HK", "2388.HK"]
REFRESH_INTERVAL = 60  # 檢查頻率（秒）
CSV_LOG_FILE = "realtime_stock_signals.csv"
SAVE_INTERACTIVE_CHARTS = True  # 是否自動生成 Plotly HTML 互動圖表

# Telegram Bot 設定
ENABLE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = "8680874924:AAGkX321FVoKiPgeqd79KWYRltEuwZkHMlM"
TELEGRAM_CHAT_ID = "7791139302"
# ================================================

previous_signals = {ticker: "HOLD" for ticker in TICKERS}

# 個股參數自適應設定
STOCK_CONFIGS = {
    "0288.HK": {  # 萬洲國際: 區間震盪 / 週期消費[cite: 3]
        "atr_mult": 1.5,
        "rsi_oversold": 35,
        "rsi_overbought": 75,
        "kd_oversold": 25,
        "weight_kd_support": 1.2,
    },
    "0303.HK": {  # 偉易達: 高股息 / 均值回歸[cite: 4]
        "atr_mult": 1.5,
        "rsi_oversold": 35,
        "rsi_overbought": 75,
        "kd_oversold": 20,
        "weight_kd_support": 1.0,
    },
    "0006.HK": {  # 電能實業: 低波動 / 公用事業
        "atr_mult": 1.0,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "kd_oversold": 20,
        "weight_kd_support": 1.0,
    },
    "1211.HK": {  # 比亞迪股份: 高 Beta / 動能成長
        "atr_mult": 2.0,
        "rsi_oversold": 40,
        "rsi_overbought": 80,
        "kd_oversold": 30,
        "weight_kd_support": 0.8,
    },
    "3110.HK": {  # 盈富基金: 大盤指數 ETF[cite: 3]
        "atr_mult": 1.5,
        "rsi_oversold": 35,
        "rsi_overbought": 75,
        "kd_oversold": 20,
        "weight_kd_support": 1.0,
    }
}
DEFAULT_CONFIG = {
    "atr_mult": 1.5,
    "rsi_oversold": 35,
    "rsi_overbought": 75,
    "kd_oversold": 20,
    "weight_kd_support": 1.0,
}


def send_telegram_message(message):
    """發送 Telegram Markdown 格式文字訊息"""
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram 訊息發送失敗: {e}")


def send_telegram_document(file_path, caption=""):
    """發送輕量化 HTML 互動圖表檔案至 Telegram (採用 30 秒逾時保護)"""
    if not ENABLE_TELEGRAM or "你的_" in TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as doc:
            files = {"document": doc}
            data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
            requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print(f"⚠️ Telegram 檔案發送逾時或失敗: {e}")


def save_interactive_chart(ticker, df):
    """繪製包含 4 面板 (陰陽燭, RSI, KD, MACD) 的 Plotly 一年期輕量化 HTML 圖表"""
    chart_df = df.copy()

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.48, 0.17, 0.17, 0.18],
        subplot_titles=(
            f"📈 {ticker} 多因子技術分析圖表 (一年期)",
            "RSI (14) 動能指標",
            "KD 隨機指標",
            "MACD (12, 26, 9)",
        ),
    )

    # 1. 陰陽燭
    fig.add_trace(
        go.Candlestick(
            x=chart_df.index,
            open=chart_df["Open"],
            high=chart_df["High"],
            low=chart_df["Low"],
            close=chart_df["Close"],
            name="陰陽燭",
            increasing_line_color="#00e676",
            decreasing_line_color="#ff334b",
        ),
        row=1,
        col=1,
    )

    # 疊加 20MA, 200MA 及 20日低點支撐位[cite: 3, 4]
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["SMA_20"],
            name="20日均線",
            line=dict(color="#00bcff", width=1.5),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["SMA_200"],
            name="200日均線",
            line=dict(color="#ffaa00", width=1.5),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["Support_20L"],
            name="20日支撐位",
            line=dict(color="#ff00ff", width=1, dash="dash"),
        ),
        row=1,
        col=1,
    )

    # 標記買賣訊號點
    chart_df["Signal_Change"] = chart_df["Signal"] != chart_df["Signal"].shift(1)

    buy_signals = chart_df[
        chart_df["Signal_Change"]
        & chart_df["Signal"].str.contains("買入|STRONG BUY|BUY", na=False)
    ]
    sell_signals = chart_df[
        chart_df["Signal_Change"]
        & chart_df["Signal"].str.contains("賣出|SELL|EXIT|TAKE PROFIT", na=False)
    ]

    if not buy_signals.empty:
        fig.add_trace(
            go.Scatter(
                x=buy_signals.index,
                y=buy_signals["Close"],
                mode="markers",
                name="買入訊號",
                marker=dict(symbol="triangle-up", size=13, color="#00d2ff"),
            ),
            row=1,
            col=1,
        )

    if not sell_signals.empty:
        fig.add_trace(
            go.Scatter(
                x=sell_signals.index,
                y=sell_signals["Close"],
                mode="markers",
                name="賣出/獲利訊號",
                marker=dict(symbol="triangle-down", size=13, color="#ff9900"),
            ),
            row=1,
            col=1,
        )

    # 2. RSI 指標
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["RSI_14"],
            name="RSI(14)",
            line=dict(color="#b366ff", width=1.5),
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=2, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="gray", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#00e676", row=2, col=1)

    # 3. KD 指標
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["K"],
            name="K線",
            line=dict(color="#00ffaa", width=1.5),
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["D"],
            name="D線",
            line=dict(color="#ffaa00", width=1.5),
        ),
        row=3,
        col=1,
    )
    fig.add_hline(y=80, line_dash="dash", line_color="#ff334b", row=3, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="#00e676", row=3, col=1)

    # 4. MACD 指標
    hist_colors = np.where(chart_df["MACD_Hist"] >= 0, "#00e676", "#ff334b")
    fig.add_trace(
        go.Bar(
            x=chart_df.index,
            y=chart_df["MACD_Hist"],
            name="MACD柱狀圖",
            marker_color=hist_colors,
            opacity=0.7,
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["MACD"],
            name="MACD快線",
            line=dict(color="#00d2ff", width=1.5),
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df["MACD_Signal"],
            name="Signal慢線",
            line=dict(color="#ffaa00", width=1.5),
        ),
        row=4,
        col=1,
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=4, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=950,
        showlegend=True,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    filename = f"{ticker}_interactive.html"
    fig.write_html(filename, include_plotlyjs="cdn")
    return filename


def analyze_stock(ticker):
    """自適應多因子量化分析模型：結合 ADX 市場狀態過濾、多因子綜合評分與個股動態風控"""
    symbol_upper = ticker.upper()
    cfg = STOCK_CONFIGS.get(symbol_upper, DEFAULT_CONFIG)

    df = yf.download(ticker, period="2y", interval="1d", progress=False)
    if df.empty:
        return None, None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 1. 基礎與進階技術指標計算
    df["SMA_20"] = ta.sma(df["Close"], length=20)
    df["SMA_200"] = ta.sma(df["Close"], length=200)
    df["SMA_20_Slope"] = df["SMA_20"].diff(3)
    df["RSI_14"] = ta.rsi(df["Close"], length=14)
    df["ATR_14"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["VOL_SMA_20"] = ta.sma(df["Volume"], length=20)
    df["Vol_Ratio"] = df["Volume"] / (df["VOL_SMA_20"] + 1e-9)
    df["Support_20L"] = df["Low"].rolling(window=20).min()
    df["Resistance_20H"] = df["High"].rolling(window=20).max()

    # KD 指標
    stoch = ta.stoch(df["High"], df["Low"], df["Close"], k=14, d=3, smooth_k=3)
    if stoch is not None and not stoch.empty:
        df["K"] = stoch["STOCHk_14_3_3"]
        df["D"] = stoch["STOCHd_14_3_3"]
    else:
        return None, None

    # MACD 指標
    macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd is not None and not macd.empty:
        df["MACD"] = macd["MACD_12_26_9"]
        df["MACD_Signal"] = macd["MACDs_12_26_9"]
        df["MACD_Hist"] = macd["MACDh_12_26_9"]
    else:
        return None, None

    # ADX 指標 (市場狀態判斷)
    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if adx_df is not None and not adx_df.empty:
        adx_col = [c for c in adx_df.columns if c.startswith("ADX")][0]
        df["ADX_14"] = adx_df[adx_col]
    else:
        df["ADX_14"] = 20.0

    df.dropna(inplace=True)
    df = df.tail(252)

    if len(df) < 2:
        return None, None

    # 2. 交叉狀態計算[cite: 3, 4]
    df["MA_Golden_Cross"] = (df["SMA_20"] > df["SMA_200"]) & (df["SMA_20"].shift(1) <= df["SMA_200"].shift(1))
    df["MA_Death_Cross"] = (df["SMA_20"] < df["SMA_200"]) & (df["SMA_20"].shift(1) >= df["SMA_200"].shift(1))

    df["KD_Golden_Cross"] = (df["K"] > df["D"]) & (df["K"].shift(1) <= df["D"].shift(1))
    df["KD_Death_Cross"] = (df["K"] < df["D"]) & (df["K"].shift(1) >= df["D"].shift(1))

    df["MACD_Golden_Cross"] = (df["MACD"] > df["MACD_Signal"]) & (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
    df["MACD_Death_Cross"] = (df["MACD"] < df["MACD_Signal"]) & (df["MACD"].shift(1) >= df["MACD_Signal"].shift(1))

    # 3. 逐日多因子加權評分與訊號生成
    scores = []
    signals = []

    for i in range(len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1] if i > 0 else row

        is_trending = (row["ADX_14"] > 22) or (row["Close"] > row["SMA_200"])
        score = 0.0

        # 趨勢因子 (最高 30 分)[cite: 3, 4]
        if row["Close"] > row["SMA_200"]:
            score += 20
        if row["SMA_20_Slope"] > 0:
            score += 10

        # RSI 動能因子 (最高 20 分)
        if row["RSI_14"] < cfg["rsi_oversold"]:
            score += 20
        elif 40 <= row["RSI_14"] <= 50 and row["RSI_14"] > prev_row["RSI_14"]:
            score += 10

        # Stochastic KD 因子 (最高 20 分)[cite: 3, 4]
        kd_gc = (row["K"] > row["D"]) and (prev_row["K"] <= prev_row["D"])
        if kd_gc and row["K"] < cfg["kd_oversold"]:
            score += 20 * cfg["weight_kd_support"]
        elif kd_gc and row["K"] < 50:
            score += 10 * cfg["weight_kd_support"]

        # MACD 因子 (最高 20 分)[cite: 3, 4]
        macd_gc = (row["MACD"] > row["MACD_Signal"]) and (prev_row["MACD"] <= prev_row["MACD_Signal"])
        if macd_gc or (row["MACD_Hist"] > 0 and row["MACD_Hist"] > prev_row["MACD_Hist"]):
            score += 20

        # 20日支撐位距離因子 (最高 10 分)[cite: 3, 4]
        dist_to_support = (row["Close"] - row["Support_20L"]) / (row["Support_20L"] + 1e-9)
        if dist_to_support <= 0.015:
            score += 10 * cfg["weight_kd_support"]

        score = round(score, 1)

        # 訊號條件判斷
        has_vol = row["Vol_Ratio"] >= 1.2
        break_support = row["Close"] < prev_row["Support_20L"]
        macd_breakdown = (row["Close"] < row["SMA_20"]) and (row["MACD_Hist"] < 0) and (prev_row["MACD_Hist"] >= 0)
        overbought_exit = (prev_row["RSI_14"] >= cfg["rsi_overbought"]) and (row["K"] < row["D"]) and (prev_row["K"] >= prev_row["D"])

        if score <= -50 or break_support or macd_breakdown or row["MA_Death_Cross"]:
            sig = "賣出/止損 (SELL/EXIT)"
        elif overbought_exit:
            sig = "獲利減倉 (TAKE PROFIT)"
        elif score >= 65 and (has_vol or is_trending):
            sig = "高勝率買入 (STRONG BUY)" if score >= 75 else "買入/建倉 (BUY)"
        else:
            sig = "持有/觀望 (HOLD)"

        scores.append(score)
        signals.append(sig)

    df["Score"] = scores
    df["Signal"] = signals

    # 4. 當前最新統計數據與動態 SL/TP
    latest = df.iloc[-1]
    entry_price = float(latest["Close"])
    atr_val = float(latest["ATR_14"])

    est_sl = round(entry_price - (cfg["atr_mult"] * atr_val), 2)
    est_tp = round(entry_price + (3.0 * atr_val), 2)
    risk = entry_price - est_sl
    reward = est_tp - entry_price
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    cross_status = "無"
    if latest["MA_Golden_Cross"]:
        cross_status = "🌟 MA黃金交叉"
    elif latest["MA_Death_Cross"]:
        cross_status = "💀 MA死亡交叉"
    elif latest["MACD_Golden_Cross"]:
        cross_status = "📊 MACD黃金交叉"
    elif latest["MACD_Death_Cross"]:
        cross_status = "📉 MACD死亡交叉"
    elif latest["KD_Golden_Cross"]:
        cross_status = "✨ KD黃金交叉"
    elif latest["KD_Death_Cross"]:
        cross_status = "☠️ KD死亡交叉"

    res_dict = {
        "時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "股票代碼": symbol_upper,
        "最新現價": round(entry_price, 2),
        "評分(Score)": latest["Score"],
        "估算止損(SL)": est_sl,
        "估算止盈(TP)": est_tp,
        "盈虧比(R/R)": rr_ratio,
        "200天線": round(float(latest["SMA_200"]), 2),
        "RSI(14)": round(float(latest["RSI_14"]), 2),
        "K值": round(float(latest["K"]), 1),
        "D值": round(float(latest["D"]), 1),
        "MACD": round(float(latest["MACD"]), 2),
        "交叉狀態": cross_status,
        "訊號": latest["Signal"],
    }

    return res_dict, df


def main():
    print("=" * 80)
    print("🚀 自適應多因子股票即時監控系統 (一年期歷史量化版) 啟動中...")
    print(f"📌 監控目標: {', '.join(TICKERS)}")
    print(f"⏱️ 刷新頻率: 每 {REFRESH_INTERVAL} 秒")
    print(f"💾 歷史日誌: {CSV_LOG_FILE}")
    print("按下 Ctrl + C 可終止程式")
    print("=" * 80 + "\n")

    send_telegram_message(
        "🚀 *自適應多因子股票監控系統已成功啟動*\n監控目標: " + ", ".join(TICKERS)
    )

    while True:
        try:
            current_results = []
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] 正在進行行情掃描與自適應多因子評分估算...")

            for ticker in TICKERS:
                res, df_data = analyze_stock(ticker)
                if res and df_data is not None:
                    current_results.append(res)

                    chart_filename = None
                    if SAVE_INTERACTIVE_CHARTS:
                        chart_filename = save_interactive_chart(ticker, df_data)

                    current_signal = res["訊號"]
                    prev_signal = previous_signals.get(ticker, "HOLD")

                    # 當訊號類型改變且不為普通觀望時發送警報
                    if current_signal != prev_signal and "HOLD" not in current_signal:
                        is_buy = "BUY" in current_signal or "買入" in current_signal
                        alert_icon = "🚨 買入警報" if is_buy else "⚠️ 賣出/止損警報"

                        msg = (
                            f"*{alert_icon} - {ticker}*\n"
                            f"-----------------------------\n"
                            f"💰 *最新現價:* ${res['最新現價']}\n"
                            f"🎯 *綜合評分:* {res['評分(Score)']} 分 | {current_signal}\n"
                            f"🛡️ *動態止損 (SL):* ${res['估算止損(SL)']}\n"
                            f"🎯 *目標止盈 (TP):* ${res['估算止盈(TP)']}\n"
                            f"⚖️ *預期盈虧比:* 1 : {res['盈虧比(R/R)']}\n"
                            f"-----------------------------\n"
                            f"📈 *200天線:* ${res['200天線']} | *RSI:* {res['RSI(14)']}\n"
                            f"📊 *MACD:* {res['MACD']} | *交叉:* {res['交叉狀態']}\n"
                            f"⏰ *時間:* {res['時間']}"
                        )

                        print(f"\n{alert_icon}: {ticker}")
                        if HAS_WINSOUND:
                            winsound.Beep(1000, 1000)
                        else:
                            print("\a")

                        send_telegram_message(msg)
                        if chart_filename and os.path.exists(chart_filename):
                            send_telegram_document(
                                chart_filename, caption=f"{ticker} 互動式技術圖表 (一年期)"
                            )

                    previous_signals[ticker] = current_signal

            if current_results:
                res_df = pd.DataFrame(current_results)
                cols_to_show = [
                    "股票代碼",
                    "最新現價",
                    "評分(Score)",
                    "估算止損(SL)",
                    "估算止盈(TP)",
                    "RSI(14)",
                    "MACD",
                    "交叉狀態",
                    "訊號",
                ]
                print(res_df[cols_to_show].to_string(index=False))

                file_exists = os.path.exists(CSV_LOG_FILE)
                res_df.to_csv(
                    CSV_LOG_FILE,
                    mode="a",
                    header=not file_exists,
                    index=False,
                    encoding="utf-8-sig",
                )

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