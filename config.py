import os
from dotenv import load_dotenv

load_dotenv()

# ================================
# Finviz 필터 설정
# ================================
FINVIZ_FILTERS = {
    "geo":       "usa",
    "sh_avgvol": "o2000",   # 평균 거래량 2M 이상
    "sh_price":  "o10",     # 주가 $10 이상
    "sh_relvol": "o1.5",    # 상대 거래량 1.5배 이상
    "ta_sma20":  "pa",      # 20MA 위
    "ta_sma50":  "pa",      # 50MA 위
    "ta_sma200": "pa",      # 200MA 위
    "fa_epsqoq": "pos",     # EPS QoQ 양수
}

# ================================
# RSI 기준값
# ================================
RSI_IDEAL_MIN = 45
RSI_IDEAL_MAX = 65
RSI_WARNING_MAX = 70
RSI_HARD_GATE = 80          # 이 이상은 무조건 SKIP

# ================================
# 목표가 / 손절 기준
# ================================
TARGET_1_PCT = 0.08         # +8% (1차 목표)
TARGET_2_PCT = 0.15         # +15% (2차 목표)
STOP_LOSS_PCT = 0.07        # -7% (손절)

# ================================
# 데이터 수집
# ================================
DATA_PERIOD = "1y"
DATA_INTERVAL = "1d"

# ================================
# 스케줄
# ================================
SCHEDULE_TIME = "08:00"

# ================================
# 알림 (Phase 2)
# ================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN", "")

# ================================
# 외부 데이터소스 API 키
# ================================
FRED_API_KEY        = os.getenv("FRED_API_KEY", "")         # fred.stlouisfed.org 무료
KAKAO_ALERT_GRADES = ["S"]

# ================================
# 당일 변동 필터 (Task 2)
# ================================
TODAY_CHANGE_MIN = -5.0     # -5% 이상 하락 시 SKIP
TODAY_CHANGE_MAX = 15.0     # +15% 이상 급등 시 SKIP (추격매수 위험)

# ================================
# 거래량 절대/상대 기준 (Task 3)
# ================================
MIN_VOLUME_ABSOLUTE = 2_000_000   # 절대 거래량 200만 이상
MIN_RELATIVE_VOLUME = 1.5         # 평균 대비 1.5배 이상

# ================================
# 뉴스 필터 (Task 4)
# ================================
NEWS_FILTER_ENABLED = True
NEWS_LOOKBACK_HOURS = 48          # 48시간 이내 뉴스만 체크

# ================================
# 출력
# ================================
OUTPUT_DIR = "output/results"
SHOW_GRADES = ["R", "S", "A", "B", "C"]
MAX_RESULTS = 20
