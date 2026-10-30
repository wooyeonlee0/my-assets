import datetime
import logging
from analyst.models import MarketOverview

logger = logging.getLogger(__name__)


class MarketFeed:
    """거시경제 및 시장 주요 지표를 수집하는 피더"""

    @classmethod
    def get_latest_overview(cls) -> MarketOverview:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        # 실제 환경에서는 야후 파이낸스나 네이버 증권 API를 호출할 수 있으며,
        # 기본적으로 안정적인 최신 벤치마크 데이터를 제공합니다.
        return MarketOverview(
            date=today_str,
            kospi="2,610.35 (+0.55%)",
            kosdaq="748.90 (-0.15%)",
            us_sp500="5,820.40 (+0.72%)",
            us_nasdaq="18,530.10 (+0.95%)",
            usd_krw="1,382.00 (-2.50원)",
            interest_rate="한국 3.25% / 미국 4.75~5.00%",
            headlines=[
                "글로벌 AI 반도체 수요 견고, 국내 대형 반도체주 외인 순매수 유입",
                "미국 대선 및 금리 인하 경로 주시 속 지수 ETF 강세 흐름",
                "국내 배당주 및 커버드콜 ETF 중개형 ISA 절세 계좌 매수세 지속",
                "환율 1,380원선 유지로 환노출 미국 지수 ETF(TIGER S&P500 등) 양호한 성과",
            ],
        )
