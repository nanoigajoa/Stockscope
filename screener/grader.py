from config import TARGET_1_PCT, TARGET_2_PCT, STOP_LOSS_PCT

# 비율 기반 임계값 — 7개 체크리스트 기준: R(6/7), S(5/7), A(4/7), B(3/7), C(2/7)
_GRADE_RATIOS = [("R", 0.85), ("S", 0.71), ("A", 0.57), ("B", 0.42), ("C", 0.28)]


def grade(
    score_result: dict,
    ticker: str,
    price: float,
    target_1_pct: float | None = None,
    target_2_pct: float | None = None,
    stop_loss_pct: float | None = None,
) -> dict:
    """채점 결과 → 등급 + 목표가/손절 계산."""
    t1 = target_1_pct if target_1_pct is not None else TARGET_1_PCT
    t2 = target_2_pct if target_2_pct is not None else TARGET_2_PCT
    sl = stop_loss_pct if stop_loss_pct is not None else STOP_LOSS_PCT

    if score_result["hard_skip"]:
        return {
            "ticker": ticker,
            "price": price,
            "grade": "SKIP",
            "score": 0,
            "max_score": score_result.get("max_score", 9),
            "reason": score_result["hard_skip_reason"],
            "checklist": {},
            "target_1": None,
            "target_2": None,
            "stop_loss": None,
        }

    score = score_result["total_score"]
    max_score = score_result.get("max_score", 7)
    ratio = score / max_score if max_score > 0 else 0
    assigned_grade = "SKIP"
    for g, threshold in _GRADE_RATIOS:
        if ratio >= threshold:
            assigned_grade = g
            break

    action_map = {
        "R": "전체 조건 충족 — 즉시 전량 진입",
        "S": "강한 진입 신호 — 분할 진입 권장",
        "A": "진입 검토 (1차 50% → 조건 확인 후 2차 50%)",
        "B": "일부 조건 미충족 — 추가 확인 필요",
        "C": "최소 조건 충족 — 대기 권장",
        "SKIP": "진입 금지",
    }

    return {
        "ticker": ticker,
        "price": price,
        "grade": assigned_grade,
        "score": score,
        "max_score": max_score,
        "action": action_map[assigned_grade],
        "checklist": score_result["items"],
        "target_1": round(price * (1 + t1), 2),
        "target_2": round(price * (1 + t2), 2),
        "stop_loss": round(price * (1 - sl), 2),
    }
