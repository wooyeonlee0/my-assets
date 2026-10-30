import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 6자리 KRX 표준 단축코드 정규식
KRX_CODE_PATTERN = re.compile(r"^\d{6}$")


class InstrumentRegistry:
    """NH투자증권 m_new_stock 마스터 데이터를 활용한 종목 매퍼 및 검증기"""

    _instance: Optional["InstrumentRegistry"] = None

    def __init__(self):
        self._name_to_code: Dict[str, str] = {}
        self._code_to_info: Dict[str, Dict[str, Any]] = {}
        self._loaded: bool = False

    @classmethod
    def get_instance(cls) -> "InstrumentRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_master(self, force_reload: bool = False) -> None:
        """nhplug.instruments.load_master("m_new_stock")를 로드하고 인메모리 인덱스를 구축합니다."""
        if self._loaded and not force_reload:
            return

        try:
            import nhplug.instruments as ins

            df = ins.load_master("m_new_stock")
            self._build_indices(df)
            self._loaded = True
            logger.info(
                f"[InstrumentRegistry] 종목 마스터 로드 완료: {len(self._code_to_info)}개 종목 색인됨."
            )
        except Exception as e:
            logger.warning(
                f"[InstrumentRegistry] nhplug 마스터 로드 실패 (Fallback 모드 활성화): {e}"
            )
            self._build_fallback_indices()
            self._loaded = True

    def _build_indices(self, df) -> None:
        """DataFrame을 순회하여 고속 조회를 위한 매핑 인덱스 구성"""
        self._name_to_code.clear()
        self._code_to_info.clear()

        for _, row in df.iterrows():
            code = str(row.get("sCode", "")).strip()
            if not KRX_CODE_PATTERN.match(code):
                continue

            name = str(row.get("name", "")).strip()
            kor_name = str(row.get("sKorName", "")).strip()
            # *삼성전자 등 접두사 '*' 제거 정규화
            clean_kor_name = kor_name.lstrip("*").strip()

            # 기준가 파싱
            sdpr_raw = str(row.get("stck_sdpr", "0")).strip()
            try:
                base_price = int(sdpr_raw) if sdpr_raw.isdigit() else 0
            except (ValueError, TypeError):
                base_price = 0

            info = {
                "code": code,
                "name": name or clean_kor_name,
                "kor_name": kor_name,
                "clean_kor_name": clean_kor_name,
                "market": str(row.get("sMarket", "")).strip(),
                "base_price": base_price,
            }

            self._code_to_info[code] = info

            # 다양한 이름 표기로 인덱싱
            for n in {name, kor_name, clean_kor_name}:
                if n:
                    norm = self._normalize_name(n)
                    self._name_to_code[norm] = code

    def _build_fallback_indices(self) -> None:
        """오프라인 및 테스트 시 사용되는 최소 주요 종목 fallback 매핑"""
        fallback_stocks = [
            {"code": "005930", "name": "삼성전자", "base_price": 60000, "market": "1"},
            {"code": "000660", "name": "SK하이닉스", "base_price": 180000, "market": "1"},
            {"code": "035420", "name": "NAVER", "base_price": 170000, "market": "1"},
            {"code": "035720", "name": "카카오", "base_price": 40000, "market": "1"},
            {"code": "373220", "name": "LG에너지솔루션", "base_price": 400000, "market": "1"},
            {"code": "005380", "name": "현대차", "base_price": 240000, "market": "1"},
            {"code": "360750", "name": "TIGER 미국S&P500", "base_price": 18000, "market": "1"},
            {"code": "133690", "name": "TIGER 미국나스닥100", "base_price": 110000, "market": "1"},
            {"code": "069500", "name": "KODEX 200", "base_price": 35000, "market": "1"},
        ]
        for s in fallback_stocks:
            code = s["code"]
            self._code_to_info[code] = s
            self._name_to_code[self._normalize_name(s["name"])] = code

    @staticmethod
    def _normalize_name(name: str) -> str:
        """종목명 정규화 (공백 제거, 특수기호 정리, 소문자화)"""
        return re.sub(r"[\s*]", "", name).lower()

    def resolve_code(self, identifier: str) -> Optional[str]:
        """종목명 또는 단축코드를 입력받아 유효한 6자리 KRX 표준 코드를 반환합니다."""
        if not self._loaded:
            self.load_master()

        clean_id = identifier.strip()

        # 이미 6자리 숫자인 경우 검증
        if KRX_CODE_PATTERN.match(clean_id):
            if clean_id in self._code_to_info:
                return clean_id

        # 종목명으로 매핑 조회
        norm = self._normalize_name(clean_id)
        if norm in self._name_to_code:
            return self._name_to_code[norm]

        # 부분 일치 검색 (예: '삼성 전자' 등)
        for name_key, code in self._name_to_code.items():
            if norm == name_key or norm in name_key or name_key in norm:
                return code

        return None

    def get_instrument_info(self, code: str) -> Optional[Dict[str, Any]]:
        """6자리 종목 코드에 해당하는 상세 정보를 반환합니다."""
        if not self._loaded:
            self.load_master()
        return self._code_to_info.get(code)

    def is_valid_krx_code(self, code: str) -> bool:
        """6자리 KRX 코드 포맷 여부 및 마스터 존재 여부 검사"""
        return bool(KRX_CODE_PATTERN.match(code) and self.resolve_code(code) == code)


# 싱글톤 인스턴스 접근자
instrument_registry = InstrumentRegistry.get_instance()
