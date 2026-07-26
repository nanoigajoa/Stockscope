"""
3축 독립 매매타이밍 스코어링.

진입 포지션(40%) + 모멘텀 강도(35%) + 구조 확인(25%) + 수급 보너스(+0.05)

설계 원칙:
  - 각 축은 서로 다른 정보 계층(가격위치 / 가격속도 / 가격구조)
  - 수급(CMF·OBV)은 독립 카테고리가 아닌 교차 검증 보너스
  - MA정배열·ADX 등 추세 컨텍스트는 사전 필터 또는 모멘텀 보조로 이동
  - 기존 S/A/B/SKIP 체크리스트와 완전 독립 — 기존 필드에 영향 없음
"""
import logging
import pandas as pd
import pandas_ta as ta  # noqa: F401 — registers df.ta accessor

from screener.indicators import (
    calc_atr_zones,
    calc_bb_advanced,
    calc_stoch_rsi,
    calc_obv_divergence,
    calc_ma_alignment,
    calc_cmf,
    calc_volume_profile,
)

logger = logging.getLogger(__name__)


def _detect_recent_bullish(df: pd.DataFrame, lookback: int = 3) -> list[str]:
    """최근 lookback봉 내 강세 캔들·구조 패턴 감지 (순수 pandas 구현)."""
    try:
        if len(df) < 4:
            return []

        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        c = df["Close"].values

        detected = []

        # 최근 lookback 봉 각각 검사
        for i in range(max(1, len(df) - lookback), len(df)):
            body     = abs(c[i] - o[i])
            rng      = h[i] - l[i]
            if rng == 0:
                continue
            upper_sh = h[i] - max(c[i], o[i])
            lower_sh = min(c[i], o[i]) - l[i]
            is_bull  = c[i] > o[i]

            # Hammer: 아래 꼬리 ≥ 2×몸통, 위 꼬리 ≤ 몸통, 몸통 < 전체 30%
            if body > 0 and lower_sh >= 2 * body and upper_sh <= body and body / rng < 0.30:
                detected.append("Hammer")

            # Bullish Engulfing: 이전 봉 음봉, 현봉 양봉이 이전 몸통 완전 포함
            if i >= 1:
                prev_bear = c[i-1] < o[i-1]
                curr_bull = c[i] > o[i]
                if prev_bear and curr_bull and o[i] <= c[i-1] and c[i] >= o[i-1]:
                    detected.append("BullishEngulfing")

            # Piercing Line: 이전 봉 음봉, 현봉 양봉, 이전 중간선 위로 마감
            if i >= 1:
                prev_mid = (o[i-1] + c[i-1]) / 2
                prev_bear = c[i-1] < o[i-1]
                if prev_bear and is_bull and c[i] > prev_mid and o[i] < c[i-1]:
                    detected.append("PiercingLine")

        # Morning Star (3봉): [-3] 음봉 | [-2] 소체 | [-1] 양봉이 [-3] 중간 이상
        if len(df) >= 3:
            i = len(df) - 1
            b1 = abs(c[i-2] - o[i-2])
            b2 = abs(c[i-1] - o[i-1])
            b3 = abs(c[i]   - o[i])
            mid_of_first = (o[i-2] + c[i-2]) / 2
            if (c[i-2] < o[i-2] and b2 < b1 * 0.5
                    and c[i] > o[i] and c[i] >= mid_of_first and b3 > b1 * 0.5):
                detected.append("MorningStar")

        # Three White Soldiers (3봉): 연속 3 양봉, 각 봉 전봉 몸통 내에서 시가
        if len(df) >= 3:
            i = len(df) - 1
            all_bull = all(c[i-k] > o[i-k] for k in range(3))
            rising   = c[i] > c[i-1] > c[i-2]
            open_in_body = (o[i-1] >= o[i-2] and o[i] >= o[i-1])
            if all_bull and rising and open_in_body:
                detected.append("ThreeWhiteSoldiers")

        # Liquidity Sweep: 20봉 저점을 장중 이탈 후 종가 회복 — 가장 강한 기관 매집 신호
        if len(df) >= 21:
            for ls_i in range(max(21, len(df) - lookback), len(df)):
                pool = min(l[ls_i - 20:ls_i])
                if l[ls_i] < pool and c[ls_i] > pool:
                    detected.append("LiquiditySweep")
                    break

        # Fair Value Gap (SMC): 강세 충격파가 남긴 가격 공백이 현재 지지구간
        if len(df) >= 5:
            price_now = float(c[-1])
            for j in range(max(2, len(df) - 21), len(df) - 1):
                if l[j] > h[j - 2]:
                    zone_bot = h[j - 2]
                    zone_top = l[j]
                    if zone_bot <= price_now <= zone_top * 1.02:
                        detected.append("FVG")
                        break

        # Volume Profile POC: 20일 거래량 최고 밀집 가격대 직상방 진입
        try:
            vp = calc_volume_profile(df)
            if vp:
                poc = vp["poc"]
                price_now = float(c[-1])
                if poc <= price_now <= poc * 1.02:
                    detected.append("POC")
        except Exception:
            pass

        result = list(dict.fromkeys(detected))
        if result:
            logger.info(f"[Signal] 패턴 발견: {result}")
        return result
    except Exception as e:
        logger.debug(f"[Signal] 패턴 감지 실패: {e}")
        return []


def check_exit_conditions(
    price: float,
    rsi_val: float | None,
    atr: dict | None,
    ma: dict,
) -> dict:
    """
    포지션 청산 조건 확인 (entry_price 없이 기술적 조건만).

    Returns: {"exit": bool, "reasons": list[str]}
    """
    reasons = []

    if atr and price <= atr["signal_stop"]:
        reasons.append(f"손절선 이탈 (${atr['signal_stop']:.2f})")

    if rsi_val is not None and rsi_val > 78:
        reasons.append(f"RSI 과매수 ({rsi_val:.0f})")

    if ma.get("daily") == "bearish":
        reasons.append("MA 역배열 시작")

    if atr:
        overbought_ceiling = atr["entry_high"] + atr["atr"]
        if price > overbought_ceiling:
            reasons.append("진입존 극단 이탈 (단기 과열)")

    return {"exit": len(reasons) > 0, "reasons": reasons}


def score_signals(
    df_daily: pd.DataFrame,
    df_hourly: pd.DataFrame | None = None,
) -> dict:
    """
    3축 독립 가중 매매타이밍 스코어링.

    Returns:
        signal_grade:      "STRONG BUY" | "BUY" | "HOLD" | "NO SIGNAL"
        signal_score:      float 0.0~1.0
        signal_breakdown:  {"entry", "momentum", "structure", "volume"}
        detected_patterns: list[str]
        entry_low, entry_high, signal_stop
        exit_signal:       {"exit": bool, "reasons": list[str]}
    """
    try:
        atr      = calc_atr_zones(df_daily)
        stoch    = calc_stoch_rsi(df_daily)
        obv      = calc_obv_divergence(df_daily)
        ma       = calc_ma_alignment(df_daily, df_hourly)
        cmf_data = calc_cmf(df_daily)
        patterns = _detect_recent_bullish(df_daily)

        price   = float(df_daily["Close"].iloc[-1])
        cmf_val = cmf_data["cmf"] if cmf_data else 0.0

        # ── 1. 진입 포지션 (40%) ────────────────────────────
        # "지금 가격이 얼마나 좋은 위치인가"
        # ATR 진입존 (70%): MA60~MA20+0.5ATR 내 위치
        if atr:
            if atr["entry_low"] <= price <= atr["entry_high"]:
                zone_score = 1.0
            elif price > atr["entry_high"]:
                excess = (price - atr["entry_high"]) / max(atr["atr"], 0.01)
                zone_score = max(0.5 - excess * 0.1, 0.0)
            else:
                zone_score = 0.0
        else:
            zone_score = 0.0

        # BB %B (30%): 볼린저밴드 하단 근접 — 통계적 과매도 위치
        bb_score = 0.0
        try:
            bb = calc_bb_advanced(df_daily)
            if bb and bb.get("pct_b") is not None:
                pct_b = bb["pct_b"]
                if pct_b <= 0.20:
                    bb_score = 1.0 - pct_b / 0.20   # 0→1.0, 0.20→0.0
        except Exception:
            pass

        entry_score = zone_score * 0.70 + bb_score * 0.30

        # ── 2. 모멘텀 강도 (35%) ────────────────────────────
        # "가격 회복 속도가 얼마나 강한가"
        # RSI 구간별 점수
        _rsi_val = stoch.get("rsi") if stoch else None
        rsi_score = 0.0
        if _rsi_val is not None:
            rsi = _rsi_val
            if 45 <= rsi <= 65:
                rsi_score = 1.0 - abs(rsi - 55) / 10   # 55→1.0, 45/65→0.0
            elif 35 <= rsi < 45:
                rsi_score = (rsi - 35) / 10 * 0.6       # 35→0.0, 45→0.6
            elif 65 < rsi <= 75:
                rsi_score = (75 - rsi) / 10 * 0.4       # 65→0.4, 75→0.0

        # RSI 히스테리시스: 30 이하 방문 후 35 미회복 시 억제 (데드캣 바운스 필터)
        try:
            rsi_series = df_daily.ta.rsi(length=14)
            if rsi_series is not None:
                recent_rsi = rsi_series.dropna().tail(10).tolist()
                if len(recent_rsi) >= 3 and any(r < 30 for r in recent_rsi[:-1]):
                    if recent_rsi[-1] < 35:
                        rsi_score *= 0.5
        except Exception:
            pass

        # StochRSI 보너스: 과매도권 탈출 중
        stoch_bonus = 0.0
        if stoch:
            k   = stoch["k"]
            k_p = stoch.get("k_prev", k)
            if k > k_p and k_p < 0.35:
                stoch_bonus = min((k - k_p) / 0.05, 0.3)

        # Z-Score 보너스: 통계적 과매도 확인
        z_bonus = 0.0
        close_tail = df_daily["Close"].tail(20).values
        if len(close_tail) >= 20:
            _std = close_tail.std(ddof=1)
            if _std > 0:
                z = (float(close_tail[-1]) - close_tail.mean()) / _std
                z_bonus = 0.30 if z < -2.0 else (0.15 if z < -1.0 else 0.0)

        rsi_base = min(rsi_score + max(stoch_bonus, z_bonus), 1.0)

        # ADX(10): 단기 추세 강도 — 노이즈(ADX<15) vs 강한 추세(ADX>35)
        # ADX(30)은 6~8주 추세를 측정해 2~3일 예측에 후행. ADX(10)으로 교체.
        adx_intensity = 0.5  # 계산 불가 시 중립
        try:
            adx_df = df_daily.ta.adx(length=10)
            if adx_df is not None and not adx_df.empty:
                adx_col = [c for c in adx_df.columns if c.startswith("ADX_")]
                if adx_col:
                    adx_val = float(adx_df[adx_col[0]].iloc[-1])
                    if not pd.isna(adx_val):
                        adx_intensity = min(max((adx_val - 15) / 20, 0.0), 1.0)
        except Exception:
            pass

        momentum_score = rsi_base * 0.65 + adx_intensity * 0.35

        # ── 3. 구조 확인 (25%) ──────────────────────────────
        # "기관 흔적이 이 가격대를 지지하는가"
        # 기관 구조 신호(FVG·POC·LiquiditySweep) — 강한 기반 신호
        # 캔들 패턴 — 소프트 확인 신호 (기반 신호 없을 시 최대 0.5)
        _STRONG = {"LiquiditySweep": 1.0, "FVG": 0.9, "POC": 0.8}
        _SOFT   = {
            "MorningStar": 0.5, "ThreeWhiteSoldiers": 0.5,
            "BullishEngulfing": 0.3, "Hammer": 0.3, "PiercingLine": 0.3,
        }
        strong_score    = max((_STRONG.get(p, 0.0) for p in patterns), default=0.0)
        soft_total      = min(sum(_SOFT.get(p, 0.0) for p in patterns), 0.50)
        structure_score = min(strong_score + soft_total * (1.0 - strong_score), 1.0)

        # ── 4. 수급 보너스 (가산, 최대 +0.05) ──────────────
        # CMF + OBV 교차 검증 — 독립 카테고리가 아닌 이중 확인 보너스
        obv_bullish = obv and obv.get("divergence") == "bullish"
        if cmf_val > 0.15 and obv_bullish:
            volume_bonus = 0.05
        elif cmf_val > 0.0 and obv_bullish:
            volume_bonus = 0.02
        else:
            volume_bonus = 0.0

        # 수급 표시용 0~1 (UI 바 전용, 점수 계산에 미사용)
        cmf_display    = min(cmf_val / 0.15, 1.0) if cmf_val > 0 else 0.0
        obv_display    = 1.0 if obv_bullish else 0.0
        volume_display = (cmf_display + obv_display) / 2

        # ── 가중 합산 ─────────────────────────────────────────
        total = min(
            entry_score     * 0.40 +
            momentum_score  * 0.35 +
            structure_score * 0.25 +
            volume_bonus,
            1.0,
        )

        # ── 등급 판정 ─────────────────────────────────────────
        # 진입 포지션 또는 모멘텀이 0이면 신호 없음 (한 축도 충족 못한 것)
        # MA 하락배열(MA20<MA60) 시 STRONG BUY 차단 — 하락 추세 편승 방지
        ma_bullish = ma.get("daily") == "bullish"

        if entry_score <= 0.0 or momentum_score <= 0.0:
            grade = "NO SIGNAL"
        elif total >= 0.60:
            grade = "STRONG BUY" if ma_bullish else "BUY"
        elif total >= 0.40:
            grade = "BUY"
        elif total >= 0.20:
            grade = "HOLD"
        else:
            grade = "NO SIGNAL"

        # ── 청산 조건 체크 ───────────────────────────────────
        exit_sig = check_exit_conditions(price, _rsi_val, atr, ma)

        # ── Confluence Check ──────────────────────────────────
        # 3개 독립 정보 계층(가격구조·가격속도·자금방향)이 동시에 충족 → 고신뢰도
        rsi_val_cf = stoch.get("rsi") if stoch else None
        struct_pat = next((p for p in patterns if p in ("FVG", "POC", "LiquiditySweep")), None)

        structure_ok = struct_pat is not None
        momentum_ok  = rsi_val_cf is not None and 35 <= rsi_val_cf <= 60
        flow_ok      = cmf_val > 0

        confluence_layers = (
            (["structure"] if structure_ok else []) +
            (["momentum"]  if momentum_ok  else []) +
            (["flow"]      if flow_ok      else [])
        )
        confluence_detail = {
            "structure": {
                "ok":     structure_ok,
                "reason": struct_pat if struct_pat else "구조 신호 없음",
            },
            "momentum": {
                "ok":     momentum_ok,
                "reason": f"RSI {rsi_val_cf:.0f}" if rsi_val_cf is not None else "RSI 없음",
            },
            "flow": {
                "ok":     flow_ok,
                "reason": f"CMF {cmf_val:+.2f}" if cmf_data else "CMF 없음",
            },
        }

        return {
            "signal_grade":    grade,
            "signal_score":    round(total, 3),
            "signal_breakdown": {
                "entry":     round(entry_score,     3),
                "momentum":  round(momentum_score,  3),
                "structure": round(structure_score, 3),
                "volume":    round(volume_display,  3),
            },
            "detected_patterns": patterns,
            "entry_low":   atr["entry_low"]   if atr else None,
            "entry_high":  atr["entry_high"]  if atr else None,
            "signal_stop": atr["signal_stop"] if atr else None,
            "confluence_count":  len(confluence_layers),
            "confluence_layers": confluence_layers,
            "confluence_detail": confluence_detail,
            "exit_signal":       exit_sig,
        }

    except Exception as e:
        logger.debug(f"[Signal] 채점 실패: {e}")
        return {
            "signal_grade":    "NO SIGNAL",
            "signal_score":    0.0,
            "signal_breakdown": {
                "entry": 0.0, "momentum": 0.0,
                "structure": 0.0, "volume": 0.0,
            },
            "entry_low":   None,
            "entry_high":  None,
            "signal_stop": None,
            "confluence_count":  0,
            "confluence_layers": [],
            "confluence_detail": {},
            "exit_signal":       {"exit": False, "reasons": []},
        }
