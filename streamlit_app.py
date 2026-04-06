import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ====================== 【全局頁面配置】 ======================
st.set_page_config(
    page_title="港美股終極底部監測系統",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ====================== 【核心配置：兩層結構】 ======================
# 第一層：三大指數（恆定）
CORE_INDEXES = {
    "恒生指數": {
        "ticker": "^HSI",
        "vix_ticker": "VHSI",
        "bond_ticker": "CN10Y.BY",
        "gdp": 28270,
        "total_market_cap": 300000
    },
    "標普500": {
        "ticker": "^GSPC",
        "vix_ticker": "^VIX",
        "bond_ticker": "^TNX",
        "gdp": 273600,
        "total_market_cap": 500000
    },
    "納斯達克100": {
        "ticker": "^NDX",
        "vix_ticker": "^VIX",
        "bond_ticker": "^TNX",
        "gdp": 273600,
        "total_market_cap": 500000
    }
}

# 第二層：你自選股（隨時改）
MY_STOCKS = {
    "港股自選": ["00700.HK", "09988.HK", "03690.HK"],
    "美股自選": ["AAPL", "MSFT", "MSTR", "TSLA"]
}

# ====================== 【6大估值指標：白話解釋（你要嘅功能）】 ======================
VALUATION_DOCS = {
    "PE歷史分位": {
        "解釋": "**解釋**：近10年入面，而家股價比盈利（PE）嘅水平，係歷史第幾便宜。\n**邏輯**：分位越低($<20\%$)，代表買得越平，歷史大底通常喺$<10\%$出現。",
        "閾值": "<20% = 低估，<10% = 大底"
    },
    "席勒CAPE比率": {
        "解釋": "**解釋**：用過去10年平均盈利計嘅PE，過濾短期盈利波動。\n**邏輯**：長期平均約17.35，低於呢個數代表長線便宜，$<15$係歷史大底級數。",
        "閾值": "<17.35 = 低估，<15 = 大底"
    },
    "巴菲特指標(總市值/GDP)": {
        "解釋": "**解釋**：全市場總市值除以GDP。\n**邏輯**：衡量股市比經濟體系大定細。$<70\%$嚴重低估，$<50\%$泡沫後反彈機會極高。",
        "閾值": "<70% = 低估，<50% = 大底"
    },
    "破淨股比例": {
        "解釋": "**解釋**：股價低於每股資產（PB<1）嘅股票占比。\n**邏輯**：市場極度悲觀時才會出現。$>10\%$底部區，$>15\%$必見大底。",
        "閾值": ">10% = 底部，>15% = 大底"
    },
    "股債性價比(盈利收益率-國債)": {
        "解釋": "**解釋**：買股票嘅潛在回報減去無風險債券回報。\n**邏輯**：差值越大，股票越抵買。$>4\%$值得買，$>6\%$超級抵買。",
        "閾值": ">4% = 值得，>6% = 大底"
    },
    "市場整體PB": {
        "解釋": "**解釋**：全市場股價除以淨資產。\n**邏輯**：$PB<1$代表你買公司資產係「平過資產價」，係極度便宜信號。",
        "閾值": "<1.0 = 極度低估"
    }
}

# ====================== 【評分系統：100分制】 ======================
def calculate_combined_score(valuation, sentiment, capital, tech):
    score = 0
    # 估值(40分)
    score += 10 if valuation["pe_percentile"] < 10 else 7 if valuation["pe_percentile"] < 20 else 0
    score += 10 if valuation["cape"] < 15 else 7 if valuation["cape"] < 17.35 else 0
    score += 10 if valuation["buffett_index"] < 50 else 7 if valuation["buffett_index"] < 70 else 0
    score += 5 if valuation["net_break_ratio"] > 15 else 3 if valuation["net_break_ratio"] > 10 else 0
    score += 5 if valuation["equity_bond_spread"] > 6 else 3 if valuation["equity_bond_spread"] > 4 else 0
    
    # 情緒(20分)
    score += 8 if sentiment["vix"] > 40 else 5 if sentiment["vix"] > 30 else 0
    score += 4 if sentiment["ipo_fail_rate"] > 50 else 2 if sentiment["ipo_fail_rate"] > 30 else 0
    score += 3 if sentiment["fund_cold"] else 0
    score += 5 if sentiment["investor_sentiment"] < 30 else 2 if sentiment["investor_sentiment"] < 50 else 0
    
    # 資金(20分)
    score += SCORING_RULES["資金維度"][capital["capital_inflow"]]
    score += SCORING_RULES["資金維度"][capital["buyback"]]
    score += SCORING_RULES["資金維度"][capital["profit_rebound"]]
    score += SCORING_RULES["資金維度"][capital["policy_ease"]]
    
    # 技術(20分)
    score += 5 if tech["volume_ratio"] < 50 else 3 if tech["volume_ratio"] < 70 else 0
    score += SCORING_RULES["技術維度"][tech["multi_divergence"]]
    score += SCORING_RULES["技術維度"][tech["monthly_ma"]]
    score += SCORING_RULES["技術維度"][tech["w_bottom"]]
    
    return min(score, 100)

# 預設評分規則
SCORING_RULES = {
    "資金維度": {
        "持續淨流入": 8, "震盪": 4, "淨流出": 0,
        "激增": 5, "一般": 2, "無": 0,
        "觸底回升": 4, "持平": 2, "下滑": 0,
        "寬鬆": 3, "中性": 1, "收緊": 0
    },
    "技術維度": {
        "3週期": 8, "2週期": 5, "1週期": 2, "0週期": 0,
        "站穩": 4, "接近": 2, "遠離": 0,
        "確認": 3, "雛形": 1, "無": 0
    }
}

# ====================== 【數據抓取函數】 ======================
@st.cache_data(ttl=86400)
def fetch_data(ticker, period="10y"):
    try:
        data = yf.Ticker(ticker).history(period=period, interval="1d")
        if data.empty: return None
        # 計技術指標
        data["rsi"] = ta.momentum.rsi(data["Close"], window=14, fillna=True)
        macd = ta.trend.MACD(data["Close"], fillna=True)
        data["macd"] = macd.macd()
        data["macd_signal"] = macd.macd_signal()
        data["ma200"] = data["Close"].rolling(window=200, min_periods=1).mean()
        return data
    except Exception as e:
        st.warning(f"抓取 {ticker} 數據失敗: {e}")
        return None

# ====================== 【繪圖函數：指標vs指數對比（你要嘅功能）】 ======================
def plot_valuation_vs_index(df, title):
    if df is None or len(df) < 252: return None
    rolling_mean = df["Close"].rolling(window=252, min_periods=60).mean()
    pe_series = df["Close"] / rolling_mean
    pe_series = pe_series.dropna()
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="指數走勢", line=dict(color="blue")))
    fig.add_trace(go.Scatter(x=pe_series.index, y=pe_series*100, name="PE分位(%)", line=dict(color="red", dash="dash"), yaxis="y2"))
    
    fig.update_layout(
        title=f"{title}：指標vs指數走勢對比",
        yaxis=dict(title="指數價格"),
        yaxis2=dict(title="PE分位(%)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.add_hline(y=20, line_dash="dash", line_color="darkred", annotation_text="低估線20%")
    return fig

# ====================== 【主界面】 ======================
def main():
    st.title("📊 港美股終極底部監測系統")
    st.subheader("分層監控：核心指數 ➔ 自選個股 | 估值解釋 + 圖表對比 + 100分評分")
    st.markdown("---")

    # 🌟 頂部：一頁看懂6大估值指標（你要求嘅解釋功能）
    with st.expander("📘 點樣讀：估值指標白話解釋（點解低代表便宜）", expanded=True):
        for name, info in VALUATION_DOCS.items():
            st.subheader(f"🔍 {name}")
            st.markdown(info["解釋"])
            st.caption(f"底部閾值參考：{info['閾值']}")
            st.divider()

    # 第一層：三大指數
    st.header("🔴 第一層：全球核心大盤指數")
    
    for idx_name, idx_info in CORE_INDEXES.items():
        st.subheader(f"📈 {idx_name}")
        col1, col2 = st.columns([1, 2])
        
        with col1:
            df_idx = fetch_data(idx_info["ticker"])
            if df_idx is None: continue
            
            # 估值計算
            rolling_mean = df_idx["Close"].rolling(window=252, min_periods=60).mean()
            pe_series = df_idx["Close"] / rolling_mean
            pe_percentile = (pe_series < pe_series.iloc[-1]).sum() / len(pe_series.dropna()) * 100 if len(pe_series.dropna())>0 else 50
            cape = pe_series.rolling(window=120, min_periods=60).mean().iloc[-1] if len(pe_series.dropna())>=120 else pe_series.mean()
            
            valuation_data = {
                "pe_percentile": round(pe_percentile, 1),
                "cape": round(cape, 2),
                "buffett_index": round((idx_info["total_market_cap"] / idx_info["gdp"]) * 100, 1),
                "net_break_ratio": st.session_state.get(f"{idx_name}_net_break", 10),
                "equity_bond_spread": st.session_state.get(f"{idx_name}_bond_spread", 3),
                "overall_pb": round(df_idx["Close"].iloc[-1]/rolling_mean.iloc[-1] if rolling_mean.iloc[-1]>0 else 1.2, 2)
            }

            # 手動輸入（Key唯一，唔會衝突）
            with st.expander("補充手動指標（影響評分）"):
                st.number_input(f"{idx_name} 破淨股比例(%)", value=10, key=f"{idx_name}_net_break")
                st.number_input(f"{idx_name} 新股破發率(%)", value=30, key=f"{idx_name}_ipo_fail")
                st.checkbox(f"{idx_name} 基金發行遇冷", value=True, key=f"{idx_name}_fund_cold")
                st.number_input(f"{idx_name} 情緒看多比例(%)", value=30, key=f"{idx_name}_sentiment")
                st.selectbox(f"{idx_name} 資金流向", ["持續淨流入", "震盪", "淨流出"], key=f"{idx_name}_capital_inflow")
                st.selectbox(f"{idx_name} 回購規模", ["激增", "一般", "無"], key=f"{idx_name}_buyback")
                st.selectbox(f"{idx_name} 盈利預期", ["觸底回升", "持平", "下滑"], key=f"{idx_name}_profit_rebound")
                st.selectbox(f"{idx_name} 政策方向", ["寬鬆", "中性", "收緊"], key=f"{idx_name}_policy_ease")
                st.number_input(f"{idx_name} 成交額萎縮比例(%)", value=60, key=f"{idx_name}_volume_ratio")
                st.selectbox(f"{idx_name} 多週期背離", ["3週期", "2週期", "1週期", "0週期"], key=f"{idx_name}_divergence")
                st.selectbox(f"{idx_name} 月線均線", ["站穩", "接近", "遠離"], key=f"{idx_name}_monthly_ma")
                st.selectbox(f"{idx_name} W底", ["確認", "雛形", "無"], key=f"{idx_name}_w_bottom")

            # 評分
            sentiment_data = {"vix": 25, "ipo_fail_rate": st.session_state.get
