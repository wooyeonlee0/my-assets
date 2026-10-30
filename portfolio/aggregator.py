import logging
from typing import List, Dict, Optional
from portfolio.models import AccountBalance, Position, UnifiedPortfolio
from portfolio.broker_adapters import (
    BaseBrokerAdapter,
    NHBrokerAdapter,
    SamsungBrokerAdapter,
    TossBrokerAdapter,
    KISBrokerAdapter,
)

logger = logging.getLogger(__name__)


class PortfolioAggregator:
    """여러 증권사 어댑터로부터 계좌 잔고를 수집하여 하나의 통합 포트폴리오로 표준화하는 집계기"""

    def __init__(self, adapters: Optional[List[BaseBrokerAdapter]] = None):
        if adapters is None:
            # 기본 지원 브로커 세트 (연동된 것과 지원 가능한 것을 모두 포함)
            self.adapters: List[BaseBrokerAdapter] = [
                TossBrokerAdapter(),
                NHBrokerAdapter(),
                SamsungBrokerAdapter(),
                KISBrokerAdapter(),
            ]
            self._explicit = False
        else:
            self.adapters = adapters
            self._explicit = True

    @property
    def connected_adapters(self) -> List[BaseBrokerAdapter]:
        """사용자가 실제 연동을 완료한 어댑터 목록"""
        if self._explicit:
            return self.adapters
        return [ad for ad in self.adapters if ad.is_connected]

    @property
    def supported_adapters(self) -> List[BaseBrokerAdapter]:
        """시스템이 지원 가능한 전체 어댑터 목록"""
        return self.adapters

    def add_adapter(self, adapter: BaseBrokerAdapter) -> None:
        self.adapters.append(adapter)

    def fetch_all(self, only_connected: bool = True) -> UnifiedPortfolio:
        """등록된 어댑터 중 연동된 계좌(only_connected=True)의 잔고를 호출하여 UnifiedPortfolio 생성"""
        accounts: List[AccountBalance] = []
        target_adapters = self.connected_adapters if only_connected else self.adapters

        for ad in target_adapters:
            try:
                acc = ad.fetch_balance()
                accounts.append(acc)
                logger.info(
                    f"[PortfolioAggregator] {ad.broker_name}({acc.account_no}) 잔고 로드 완료: 총 {acc.total_eval_amount:,.0f}원"
                )
            except Exception as e:
                logger.error(f"[PortfolioAggregator] {ad.broker_name} 잔고 수집 실패: {e}")

        # 전체 자산 합산
        total_net_worth = sum(acc.total_eval_amount for acc in accounts)
        total_cash = sum(acc.deposit_cash for acc in accounts)
        cash_ratio = (total_cash / total_net_worth) if total_net_worth > 0 else 0.0

        # 종목별 합산
        code_to_pos: Dict[str, Position] = {}
        for acc in accounts:
            for p in acc.positions:
                if p.stock_code in code_to_pos:
                    exist = code_to_pos[p.stock_code]
                    tot_qty = exist.quantity + p.quantity
                    tot_eval = exist.eval_amount + p.eval_amount
                    avg_buy = (
                        (exist.avg_buy_price * exist.quantity + p.avg_buy_price * p.quantity) / tot_qty
                        if tot_qty > 0
                        else 0
                    )
                    pl = tot_eval - (avg_buy * tot_qty)
                    pl_rate = (pl / (avg_buy * tot_qty) * 100) if (avg_buy * tot_qty) > 0 else 0.0

                    code_to_pos[p.stock_code] = Position(
                        stock_code=p.stock_code,
                        stock_name=p.stock_name,
                        quantity=tot_qty,
                        avg_buy_price=avg_buy,
                        current_price=p.current_price,
                        eval_amount=tot_eval,
                        profit_loss=pl,
                        profit_rate=pl_rate,
                        account_no="CONSOLIDATED",
                        broker_name="MULTI",
                        account_type="CONSOLIDATED",
                        asset_class=p.asset_class,
                    )
                else:
                    code_to_pos[p.stock_code] = p.model_copy()

        consolidated_positions = list(code_to_pos.values())

        # 종목별 비중 계산
        stock_weights: Dict[str, float] = {}
        for p in consolidated_positions:
            w = (p.eval_amount / total_net_worth) if total_net_worth > 0 else 0.0
            stock_weights[p.stock_name] = round(w, 4)

        # 자산군별 비중 계산
        asset_class_weights: Dict[str, float] = {"CASH": round(cash_ratio, 4)}
        for p in consolidated_positions:
            ac = p.asset_class
            w = (p.eval_amount / total_net_worth) if total_net_worth > 0 else 0.0
            asset_class_weights[ac] = round(asset_class_weights.get(ac, 0.0) + w, 4)

        return UnifiedPortfolio(
            total_net_worth=total_net_worth,
            total_cash=total_cash,
            cash_ratio=round(cash_ratio, 4),
            accounts=accounts,
            consolidated_positions=consolidated_positions,
            asset_class_weights=asset_class_weights,
            stock_weights=stock_weights,
        )


# 기본 인스턴스
default_aggregator = PortfolioAggregator()
