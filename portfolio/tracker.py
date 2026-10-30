import json
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_FILE = DATA_DIR / "portfolio_history.json"


def record_portfolio_snapshot(
    total_net_worth: float,
    total_cash: float,
    cash_ratio: float,
    stock_weights: Dict[str, float],
    note: str = "정기 스냅샷 기록",
    custom_date: Optional[str] = None,
) -> None:
    """포트폴리오의 시점별 총자산 및 종목 비중을 히스토리에 누적 저장"""
    now_str = custom_date or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    history = load_portfolio_history()
    
    snapshot = {
        "timestamp": now_str,
        "total_net_worth": round(total_net_worth, 0),
        "total_cash": round(total_cash, 0),
        "cash_ratio": round(cash_ratio, 4),
        "stock_weights": stock_weights,
        "note": note,
    }
    
    history.append(snapshot)
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_portfolio_history() -> List[Dict[str, Any]]:
    """누적된 포트폴리오 변동 히스토리 목록 반환"""
    if not HISTORY_FILE.exists():
        # 과거 3개월 트렌드 시뮬레이션 초기 데이터 생성
        initial_history = [
            {
                "timestamp": "2026-08-01",
                "total_net_worth": 625000000.0,
                "total_cash": 15000000.0,
                "cash_ratio": 0.024,
                "stock_weights": {"NVDA": 0.15, "TSLA": 0.11, "GOOGL": 0.12, "AAPL": 0.10},
                "note": "8월 초 자산 기준",
            },
            {
                "timestamp": "2026-09-01",
                "total_net_worth": 658000000.0,
                "total_cash": 12000000.0,
                "cash_ratio": 0.0182,
                "stock_weights": {"NVDA": 0.17, "TSLA": 0.115, "GOOGL": 0.125, "AAPL": 0.095},
                "note": "9월 기술주 랠리 반영",
            },
            {
                "timestamp": "2026-10-01",
                "total_net_worth": 678000000.0,
                "total_cash": 10500000.0,
                "cash_ratio": 0.0155,
                "stock_weights": {"NVDA": 0.18, "TSLA": 0.12, "GOOGL": 0.128, "AAPL": 0.093},
                "note": "10월 초 리밸런싱 전",
            },
            {
                "timestamp": "2026-10-30",
                "total_net_worth": 712714593.0,
                "total_cash": 11324084.0,
                "cash_ratio": 0.0159,
                "stock_weights": {
                    "엔비디아 (NVDA)": 0.183,
                    "알파벳 A (GOOGL)": 0.129,
                    "테슬라 (TSLA)": 0.122,
                    "애플 (AAPL)": 0.092,
                    "카니발 (CCL)": 0.060,
                    "삼성전자": 0.058,
                },
                "note": "더리치(The Rich) 앱 자산 연동",
            },
        ]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_history, f, ensure_ascii=False, indent=2)
        return initial_history

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []
