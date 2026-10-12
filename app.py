from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st
from streamlit_js_eval import get_geolocation
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 頁面基本配置與樣式 ---
st.set_page_config(
    page_title="乘潮進港與 UKC 決策支援系統 (現在與未來預報版)",
    page_icon="🚢",
    layout="wide",
)

# 取得台灣時區時間
tw_tz = pytz.timezone("Asia/Taipei")
now = datetime.now(tw_tz)

# --- 2. 臺灣港務股份有限公司各港口與航道細部水深資料庫與潮差振幅參數 ---
TAIWAN_PORTS = {
    "高雄港第二航道": {
        "depth": 17.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetKHStationXML.aspx"
        ),
        "amplitude": 0.55,
        "lat": 22.56,
        "lon": 120.30,
        "type": "商港 (貨櫃主力)",
    },
    "高雄港第一航道": {
        "depth": 15.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetKHStationXML.aspx"
        ),
        "amplitude": 0.55,
        "lat": 22.61,
        "lon": 120.27,
        "type": "商港 (傳統/客輪)",
    },
    "基隆港主航道": {
        "depth": 15.5,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetKLStationXML.aspx"
        ),
        "amplitude": 0.40,
        "lat": 25.15,
        "lon": 121.75,
        "type": "商港",
    },
    "蘇澳港進港航道": {
        "depth": 15.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetSAStationXML.aspx"
        ),
        "amplitude": 0.38,
        "lat": 24.60,
        "lon": 121.87,
        "type": "商港",
    },
    "花蓮港進港航道": {
        "depth": 14.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetHLStationXML.aspx"
        ),
        "amplitude": 0.35,
        "lat": 23.98,
        "lon": 121.63,
        "type": "商港",
    },
    "臺中港外航道": {
        "depth": 16.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetTCStationXML.aspx"
        ),
        "amplitude": 1.80,
        "lat": 24.26,
        "lon": 120.51,
        "type": "商港",
    },
    "臺北港進港航道": {
        "depth": 16.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetTPstationXML.aspx"
        ),
        "amplitude": 0.90,
        "lat": 25.16,
        "lon": 121.37,
        "type": "商港",
    },
    "安平港進港航道": {
        "depth": 12.0,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetAPStationXML.aspx"
        ),
        "amplitude": 0.50,
        "lat": 22.98,
        "lon": 120.15,
        "type": "商港",
    },
    "布袋港進港航道": {
        "depth": 7.5,
        "xml_url": (
            "https://isohe.ihmt.gov.tw/station/OpenData/XML/GetBDStationXML.aspx"
        ),
        "amplitude": 0.85,
        "lat": 23.37,
        "lon": 120.14,
        "type": "商港",
    },
}

# --- 3. 標題與簡介 ---
st.title("🚢 乘潮進港與 UKC 決策支援系統")
st.caption(
    f"📅 當前時間：{now.strftime('%Y-%m-%d %H:%M:%S')} (CST) ｜ 聚焦：現在與未來 24 小時乘潮預報"
)
st.markdown("---")

# --- 4. 主畫面控制區：港口/航道選擇與吃水輸入 ---
col_ctrl1, col_ctrl2 = st.columns(2)

# GPS 自動定位最近港口
geo_data = get_geolocation()
auto_detected_port = "高雄港第二航道"

if geo_data and "coords" in geo_data:
    user_lat = geo_data["coords"]["latitude"]
    user_lon = geo_data["coords"]["longitude"]
    min_dist = float("inf")
    for p_name, info in TAIWAN_PORTS.items():
        dist = (user_lat - info["lat"]) ** 2 + (user_lon - info["lon"]) ** 2
        if dist < min_dist:
            min_dist = dist
            auto_detected_port = p_name

port_options = list(TAIWAN_PORTS.keys())
default_idx = (
    port_options.index(auto_detected_port)
    if auto_detected_port in port_options
    else 0
)

with col_ctrl1:
    st.markdown("### 📍 選擇目標港口與航道")
    selected_port = st.selectbox(
        "選擇航道",
        port_options,
        index=default_idx,
        label_visibility="collapsed",
    )

with col_ctrl2:
    st.markdown("### 🚢 輸入船舶靜態吃水 (m)")
    static_draft = st.number_input(
        "輸入船舶吃水",
        min_value=3.0,
        max_value=25.0,
        value=14.5,
        step=0.1,
        label_visibility="collapsed",
    )

port_info = TAIWAN_PORTS[selected_port]
channel_depth = port_info["depth"]
xml_url = port_info["xml_url"]
amplitude = port_info["amplitude"]

st.markdown("---")


# --- 5. 抓取 XML 最新即時水位作為當下基準錨點 ---
@st.cache_data(ttl=300)
def fetch_latest_anchor(url):
    try:
        res = requests.get(url, timeout=5, verify=False)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            latest_val = None
            for node in root.iter():
                for child in node:
                    if "tide" in child.tag.lower() or "value" in child.tag.lower():
                        try:
                            val = float(child.text)
                            if val > -10:
                                latest_val = val
                        except:
                            pass
            if latest_val is not None:
                return latest_val
    except:
        pass
    return None


current_anchor = fetch_latest_anchor(xml_url)
if current_anchor is None:
    current_anchor = 0.75  # 保底基準

# --- 6. 建立從現在（$t=0$）開始往未來的 24 小時預報陣列 ---
tidal_data = {}
base_time = now.replace(minute=0, second=0, microsecond=0)

for i in range(24):
    t = base_time + timedelta(hours=i)
    k = t.strftime("%Y-%m-%d %H:00:00")
    # 以即時錨點為起點，推算未來 24 小時潮位趨勢
    tide_val = round(
        current_anchor + amplitude * np.sin(2 * np.pi * i / 12.4), 2
    )
    tidal_data[k] = tide_val

# --- 7. 計算核心：乘潮水位與 UKC 裕度百分比 ---
results = []
current_status_code = ""
current_ukc_pct = 0.0
safe_windows_count = 0

for i in range(24):
    t = base_time + timedelta(hours=i)
    k = t.strftime("%Y-%m-%d %H:00:00")
    tide_val = tidal_data.get(k, current_anchor)

    avail_depth = channel_depth + tide_val
    ukc_distance = avail_depth - static_draft
    ukc_pct = (ukc_distance / static_draft) * 100

    if ukc_pct >= 15.0:
        status_text, status_code = "🟢 安全通行", "GREEN"
        safe_windows_count += 1
    elif ukc_pct >= 10.0:
        status_text, status_code = "🟡 限制通行", "YELLOW"
    else:
        status_text, status_code = "🔴 禁止過灘", "RED"

    if i == 0:
        current_status_code = status_code
        current_ukc_pct = ukc_pct

    results.append(
        {
            "預報時間": t.strftime("%H:00") + (" (現在)" if i == 0 else ""),
            "預報潮位 (m)": tide_val,
            "可用總水深 (m)": round(avail_depth, 2),
            "船舶吃水 (m)": static_draft,
            "UKC 裕度 (%)": round(ukc_pct, 1),
            "乘潮狀態": status_text,
            "code": status_code,
        }
    )

# --- 8. 動態背景與警示橫幅 ---
if current_status_code == "GREEN":
    st.markdown(
        """
        <style>
        .stApp { background-color: #F0FDF4; }
        </style>
    """,
        unsafe_allow_html=True,
    )
    st.success(
        f"🟢 **【安全乘潮】當前時刻 ({now.strftime('%H:%M')}) 水深裕度充裕，可安全進港！**\n\n- 當前 UKC 裕度：**{current_ukc_pct:.1f}%** (標準 $\\ge 15.0\\%$)"
    )
elif current_status_code == "YELLOW":
    st.markdown(
        """
        <style>
        .stApp { background-color: #FEFCE8; }
        </style>
    """,
        unsafe_allow_html=True,
    )
    st.warning(
        f"🟡 **【限制通行】當前時刻 ({now.strftime('%H:%M')}) 水深較為吃緊！**\n\n- 當前 UKC 裕度：**{current_ukc_pct:.1f}%** ($10.0\\% \\le$ 裕度 $< 15.0\\%$，請謹慎評估)"
    )
else:
    st.markdown(
        """
        <style>
        .stApp { background-color: #FEF2F2; }
        </style>
    """,
        unsafe_allow_html=True,
    )
    st.error(
        f"🔴 **【禁止過灘】當前時刻 ({now.strftime('%H:%M')}) 龍骨下餘裕嚴重不足！**\n\n- 當前 UKC 裕度：**{current_ukc_pct:.1f}%** (裕度 $< 10.0\\$，存在觸礁擱淺風險)"
    )

# --- 9. 頂部關鍵指標儀表板 ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("目標航道", selected_port)
m2.metric("航道設計水深", f"{channel_depth:.1f} m")
m3.metric("目前 UKC 裕度", f"{current_ukc_pct:.1f}%")
m4.metric("未來 24h 安全視窗", f"{safe_windows_count} 小時")

st.markdown("---")

# --- 10. 逐時明細表格呈現 ---
df = pd.DataFrame(results)

st.subheader("📊 未來 24 小時乘潮進港逐時預報評估表")
st.dataframe(
    df[
        [
            "預報時間",
            "預報潮位 (m)",
            "可用總水深 (m)",
            "船舶吃水 (m)",
            "UKC 裕度 (%)",
            "乘潮狀態",
        ]
    ],
    use_container_width=True,
)