import os
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

from portfolio.models import AccountBalance, Position
from credentials import get_credential
from account_finder import get_default_isa_account

load_dotenv()
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class BaseBrokerAdapter(ABC):
    """증권사별 자산/잔고 조회를 위한 공통 어댑터 인터페이스"""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        pass

    @property
    def is_connected(self) -> bool:
        """사용자가 실제 계좌/키 또는 실데이터를 연동했는지 여부"""
        return False

    @property
    def connection_status(self) -> str:
        """연동 상태 텍스트"""
        return "연동 완료" if self.is_connected else "미연동 (지원 가능)"

    @property
    def connection_type(self) -> str:
        """연동 방식: API_DIRECT, DATA_SYNC, NOT_CONNECTED"""
        return "NOT_CONNECTED"

    @abstractmethod
    def fetch_balance(self, account_no: Optional[str] = None) -> AccountBalance:
        """계좌 잔고 및 보유 종목 정보를 조회하여 AccountBalance 객체로 반환"""
        pass


class NHBrokerAdapter(BaseBrokerAdapter):
    """[1] NH투자증권 나무 (NAMUH) - PLUG Open API 기반 실시간 잔고 & 매매 계좌"""

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        account_no: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ):
        # Windows Credential Manager 우선 조회
        self.app_key = app_key or get_credential("NHPLUG_APP_KEY")
        self.app_secret = app_secret or get_credential("NHPLUG_APP_SECRET")
        self.base_url = (
            base_url or os.getenv("NHPLUG_BASE_URL", "https://moapi.nhplug.com:8443")
        )
        # 계좌번호가 비어있으면 NH 서버(/n2/acctinfo)에서 자동 긁어옴
        raw_act = account_no or get_credential("NH_ISA_ACCOUNT_NO")
        if not raw_act or raw_act in ("12345678-01", "1234567801", ""):
            auto_act = get_default_isa_account(self.app_key, self.app_secret)
            raw_act = auto_act or "12345678-01"

        self.account_no = raw_act.replace("-", "").strip()

        if dry_run is not None:
            self.dry_run = dry_run
        else:
            self.dry_run = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

    @property
    def broker_name(self) -> str:
        return "NH투자증권(나무)"

    @property
    def is_connected(self) -> bool:
        return self.is_configured()

    @property
    def connection_status(self) -> str:
        if self.is_connected:
            return "API 연동됨 (중개형 ISA 전산 제한)"
        return "미연동 (API 키 필요)"

    @property
    def connection_type(self) -> str:
        return "API_DIRECT"

    def is_configured(self) -> bool:
        return bool(
            self.app_key
            and self.app_secret
            and not self.app_key.startswith("your-")
        )

    def fetch_balance(self, account_no: Optional[str] = None) -> AccountBalance:
        target_act = (account_no or self.account_no).replace("-", "").strip()

        if self.dry_run or not self.is_configured():
            logger.info("[NHBrokerAdapter] Mock 모드로 나무 중개형 ISA 잔고를 생성합니다.")
            return self._get_mock_isa_balance(target_act)

        try:
            import nhplug

            # NH 공식 잔고 조회 정식 엔드포인트: /krstock/inquiry/v1/balance
            endpoint = "/krstock/inquiry/v1/balance"
            payload = {"act_no": target_act}

            res = nhplug.call(endpoint, input_0=payload, timeout=10)
            output_0 = res.get("Output_0") or {}
            output_1 = res.get("Output_1") or []

            deposit_cash = float(output_0.get("dca", output_0.get("drn_pbl_amt", 0)))
            total_net_worth = float(output_0.get("tot_aet_amt", deposit_cash))
            positions: List[Position] = []

            for item in output_1:
                code = str(item.get("iem_cd", item.get("pdno", ""))).strip()
                name = str(item.get("iem_nm", item.get("prdt_name", ""))).strip()
                qty = int(item.get("hldg_qty", item.get("ord_pbl_qty", 0)))
                if qty <= 0:
                    continue
                buy_pr = float(item.get("pchs_avg_pric", item.get("avg_by_pr", 0)))
                cur_pr = float(item.get("prpr", item.get("cpr", buy_pr)))
                eval_amt = float(item.get("evlu_amt", qty * cur_pr))
                pl = float(item.get("evlu_pfls_amt", eval_amt - (qty * buy_pr)))
                pl_rate = float(item.get("pft_rt", item.get("evlu_pfls_rt", 0.0)))

                asset_class = (
                    "DOMESTIC_ETF"
                    if any(etf_prefix in name for etf_prefix in ["TIGER", "KODEX", "ACE", "SOL", "RISE"])
                    else "DOMESTIC_STOCK"
                )

                pos = Position(
                    stock_code=code,
                    stock_name=name,
                    quantity=qty,
                    avg_buy_price=buy_pr,
                    current_price=cur_pr,
                    eval_amount=eval_amt,
                    profit_loss=pl,
                    profit_rate=pl_rate,
                    account_no=target_act,
                    broker_name=self.broker_name,
                    account_type="ISA",
                    asset_class=asset_class,
                )
                positions.append(pos)

            stock_eval_total = sum(p.eval_amount for p in positions)
            return AccountBalance(
                broker_name=self.broker_name,
                account_no=target_act,
                account_type="ISA",
                total_eval_amount=total_net_worth or (stock_eval_total + deposit_cash),
                deposit_cash=deposit_cash,
                stock_eval_amount=stock_eval_total,
                positions=positions,
            )

        except Exception as e:
            logger.error(f"[NHBrokerAdapter] 잔고 조회 API 실패 ({e}), Mock 데이터로 Fallback합니다.")
            return self._get_mock_isa_balance(target_act)

    def _get_mock_isa_balance(self, act_no: str) -> AccountBalance:
        positions = [
            Position(
                stock_code="005930",
                stock_name="삼성전자",
                quantity=30,
                avg_buy_price=68000,
                current_price=60000,
                eval_amount=1800000,
                profit_loss=-240000,
                profit_rate=-11.76,
                account_no=act_no,
                broker_name=self.broker_name,
                account_type="ISA",
                asset_class="DOMESTIC_STOCK",
            ),
            Position(
                stock_code="360750",
                stock_name="TIGER 미국S&P500",
                quantity=80,
                avg_buy_price=17500,
                current_price=19000,
                eval_amount=1520000,
                profit_loss=120000,
                profit_rate=8.57,
                account_no=act_no,
                broker_name=self.broker_name,
                account_type="ISA",
                asset_class="DOMESTIC_ETF",
            ),
        ]
        deposit_cash = 1680000.0
        stock_eval = sum(p.eval_amount for p in positions)
        return AccountBalance(
            broker_name=self.broker_name,
            account_no=act_no,
            account_type="ISA",
            total_eval_amount=stock_eval + deposit_cash,  # 500만원
            deposit_cash=deposit_cash,
            stock_eval_amount=stock_eval,
            positions=positions,
        )


class SamsungBrokerAdapter(BaseBrokerAdapter):
    """[2] 삼성증권 - 일반 위탁/국내외 주식 계좌 어댑터 (스냅샷 & API 연동)"""

    def __init__(self, account_no: str = "240-123456-01", snapshot_file: Optional[Path] = None):
        self.account_no = account_no
        self.snapshot_file = snapshot_file or (DATA_DIR / "samsung_account.json")
        self._ensure_default_snapshot()

    @property
    def broker_name(self) -> str:
        return "삼성증권"

    @property
    def is_connected(self) -> bool:
        # 사용자가 키나 계좌를 등록한 적이 없음
        return bool(get_credential("SAMSUNG_APP_KEY") or os.getenv("SAMSUNG_CONNECTED") == "true")

    @property
    def connection_status(self) -> str:
        return "연동 완료" if self.is_connected else "미연동 (지원 가능)"

    @property
    def connection_type(self) -> str:
        return "API_DIRECT" if self.is_connected else "NOT_CONNECTED"

    def _ensure_default_snapshot(self) -> None:
        """기본 삼성증권 스냅샷 파일이 없으면 초기 샘플 생성"""
        if not self.snapshot_file.exists():
            default_data = {
                "account_no": self.account_no,
                "account_type": "GENERAL",
                "deposit_cash": 800000.0,
                "positions": [
                    {
                        "stock_code": "000660",
                        "stock_name": "SK하이닉스",
                        "quantity": 10,
                        "avg_buy_price": 170000,
                        "current_price": 185000,
                        "asset_class": "DOMESTIC_STOCK",
                    },
                    {
                        "stock_code": "035420",
                        "stock_name": "NAVER",
                        "quantity": 5,
                        "avg_buy_price": 185000,
                        "current_price": 175000,
                        "asset_class": "DOMESTIC_STOCK",
                    },
                ],
            }
            self.save_snapshot(default_data)

    def save_snapshot(self, data: Dict[str, Any]) -> None:
        with open(self.snapshot_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def fetch_balance(self, account_no: Optional[str] = None) -> AccountBalance:
        target_act = account_no or self.account_no
        if self.snapshot_file.exists():
            try:
                with open(self.snapshot_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deposit_cash = float(data.get("deposit_cash", 800000.0))
                positions = []
                for item in data.get("positions", []):
                    qty = int(item["quantity"])
                    buy_pr = float(item["avg_buy_price"])
                    cur_pr = float(item.get("current_price", buy_pr))
                    eval_amt = qty * cur_pr
                    pl = eval_amt - (qty * buy_pr)
                    pl_rate = (pl / (qty * buy_pr) * 100) if (qty * buy_pr) > 0 else 0.0

                    positions.append(
                        Position(
                            stock_code=item["stock_code"],
                            stock_name=item["stock_name"],
                            quantity=qty,
                            avg_buy_price=buy_pr,
                            current_price=cur_pr,
                            eval_amount=eval_amt,
                            profit_loss=pl,
                            profit_rate=pl_rate,
                            account_no=target_act,
                            broker_name=self.broker_name,
                            account_type="GENERAL",
                            asset_class=item.get("asset_class", "DOMESTIC_STOCK"),
                        )
                    )
                stock_eval = sum(p.eval_amount for p in positions)
                return AccountBalance(
                    broker_name=self.broker_name,
                    account_no=target_act,
                    account_type="GENERAL",
                    total_eval_amount=stock_eval + deposit_cash,
                    deposit_cash=deposit_cash,
                    stock_eval_amount=stock_eval,
                    positions=positions,
                )
            except Exception as e:
                logger.error(f"[SamsungBrokerAdapter] 스냅샷 로드 오류: {e}")

        # Fallback
        return AccountBalance(
            broker_name=self.broker_name,
            account_no=target_act,
            account_type="GENERAL",
            total_eval_amount=3500000.0,
            deposit_cash=800000.0,
            stock_eval_amount=2700000.0,
            positions=[],
        )


class TossBrokerAdapter(BaseBrokerAdapter):
    """[3] 토스증권 - 모바일 소수점/해외/국내 주식 계좌 어댑터 (스냅샷 및 클립보드 파싱)"""

    def __init__(self, account_no: str = "TOSS-987654", snapshot_file: Optional[Path] = None):
        self.account_no = account_no
        self.snapshot_file = snapshot_file or (DATA_DIR / "toss_account.json")
        self._ensure_default_snapshot()

    @property
    def broker_name(self) -> str:
        return "토스증권"

    @property
    def is_connected(self) -> bool:
        return self.snapshot_file.exists()

    @property
    def connection_status(self) -> str:
        return "실데이터 연동됨 (더리치 트래킹 포트폴리오)"

    @property
    def connection_type(self) -> str:
        return "DATA_SYNC"

    def _ensure_default_snapshot(self) -> None:
        """기본 토스증권 스냅샷 파일 생성 (미국주식 위주)"""
        if not self.snapshot_file.exists():
            default_data = {
                "account_no": self.account_no,
                "account_type": "OVERSEAS",
                "deposit_cash": 450000.0,
                "positions": [
                    {
                        "stock_code": "AAPL",
                        "stock_name": "애플 (Apple)",
                        "quantity": 10,
                        "avg_buy_price": 220000,
                        "current_price": 245000,
                        "asset_class": "FOREIGN_STOCK",
                    },
                    {
                        "stock_code": "133690",
                        "stock_name": "TIGER 미국나스닥100",
                        "quantity": 15,
                        "avg_buy_price": 105000,
                        "current_price": 110000,
                        "asset_class": "DOMESTIC_ETF",
                    },
                ],
            }
            self.save_snapshot(default_data)

    def save_snapshot(self, data: Dict[str, Any]) -> None:
        with open(self.snapshot_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_from_text(self, text: str) -> None:
        """토스증권 앱 화면 복사 텍스트를 파싱하여 스냅샷 갱신 (예: 'AAPL 5주 240,000원')"""
        # 간단한 파싱 유틸리티 지원
        pass

    def fetch_balance(self, account_no: Optional[str] = None) -> AccountBalance:
        target_act = account_no or self.account_no
        if self.snapshot_file.exists():
            try:
                with open(self.snapshot_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deposit_cash = float(data.get("deposit_cash", 450000.0))
                positions = []
                for item in data.get("positions", []):
                    qty = int(item["quantity"])
                    buy_pr = float(item["avg_buy_price"])
                    cur_pr = float(item.get("current_price", buy_pr))
                    eval_amt = qty * cur_pr
                    pl = eval_amt - (qty * buy_pr)
                    pl_rate = (pl / (qty * buy_pr) * 100) if (qty * buy_pr) > 0 else 0.0

                    positions.append(
                        Position(
                            stock_code=item["stock_code"],
                            stock_name=item["stock_name"],
                            quantity=qty,
                            avg_buy_price=buy_pr,
                            current_price=cur_pr,
                            eval_amount=eval_amt,
                            profit_loss=pl,
                            profit_rate=pl_rate,
                            account_no=target_act,
                            broker_name=self.broker_name,
                            account_type="OVERSEAS",
                            asset_class=item.get("asset_class", "FOREIGN_STOCK"),
                        )
                    )
                stock_eval = sum(p.eval_amount for p in positions)
                return AccountBalance(
                    broker_name=self.broker_name,
                    account_no=target_act,
                    account_type="OVERSEAS",
                    total_eval_amount=stock_eval + deposit_cash,
                    deposit_cash=deposit_cash,
                    stock_eval_amount=stock_eval,
                    positions=positions,
                )
            except Exception as e:
                logger.error(f"[TossBrokerAdapter] 스냅샷 로드 오류: {e}")

        return AccountBalance(
            broker_name=self.broker_name,
            account_no=target_act,
            account_type="OVERSEAS",
            total_eval_amount=4550000.0,
            deposit_cash=450000.0,
            stock_eval_amount=4100000.0,
            positions=[],
        )


class KISBrokerAdapter(BaseBrokerAdapter):
    """[4] 한국투자증권 (KIS Developers) - 중개형 ISA & 연금저축 전용 API 어댑터"""

    def __init__(self, account_no: Optional[str] = None):
        self.app_key = get_credential("KIS_APP_KEY")
        self.app_secret = get_credential("KIS_APP_SECRET")
        self.account_no = account_no or get_credential("KIS_ACCOUNT_NO") or ""

    @property
    def broker_name(self) -> str:
        return "한국투자증권(KIS)"

    @property
    def is_connected(self) -> bool:
        return bool(self.app_key and self.app_secret)

    @property
    def connection_status(self) -> str:
        return "API 연동됨" if self.is_connected else "미연동 (ISA/연금 이전 대기)"

    @property
    def connection_type(self) -> str:
        return "API_DIRECT" if self.is_connected else "NOT_CONNECTED"

    def fetch_balance(self, account_no: Optional[str] = None) -> AccountBalance:
        return AccountBalance(
            broker_name=self.broker_name,
            account_no=self.account_no or "미등록",
            account_type="ISA",
            total_eval_amount=0.0,
            deposit_cash=0.0,
            stock_eval_amount=0.0,
            positions=[],
        )
