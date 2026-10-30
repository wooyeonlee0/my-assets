import os
import logging
from typing import List, Dict, Any, Optional

from credentials import get_credential

logger = logging.getLogger(__name__)


def fetch_nh_account_list(app_key: Optional[str] = None, app_secret: Optional[str] = None) -> List[Dict[str, Any]]:
    """NH투자증권 PLUG Open API (/n2/acctinfo)를 호출하여 
    사용자가 보유한 계좌 목록을 자동으로 조회합니다.
    (입력값 불필요, App Key/Secret 인증 토큰으로 자동 긁어옴)
    """
    key = app_key or get_credential("NHPLUG_APP_KEY")
    secret = app_secret or get_credential("NHPLUG_APP_SECRET")

    if not key or not secret or key.startswith("your-"):
        logger.warning("[AccountFinder] App Key/Secret이 설정되지 않아 계좌 조회를 건너뜁니다.")
        return []

    try:
        import nhplug

        os.environ["NHPLUG_APP_KEY"] = key
        os.environ["NHPLUG_APP_SECRET"] = secret

        # NH 공식 계좌 목록 조회 엔드포인트
        endpoint = "/n2/acctinfo"
        res = nhplug.call(endpoint, input_0={}, timeout=10)

        # Output_0 또는 리스트 구조 파싱
        output_0 = res.get("Output_0") or []
        accounts = []

        for item in output_0:
            act_no = str(item.get("acct_no", "")).strip()
            act_type = str(item.get("acct_type", "")).strip()
            act_name = str(item.get("acct_name", item.get("prdt_name", ""))).strip()

            if act_no:
                accounts.append({
                    "account_no": act_no,
                    "account_type": act_type,  # 01: 종합위탁, 02: 수익증권/ISA, 03: 모의투자
                    "account_name": act_name,
                    "raw": item,
                })

        logger.info(f"[AccountFinder] 총 {len(accounts)}개의 NH 계좌를 자동 발견했습니다.")
        return accounts

    except Exception as e:
        logger.error(f"[AccountFinder] 계좌 목록 자동 조회 실패: {e}")
        return []


def get_default_isa_account(app_key: Optional[str] = None, app_secret: Optional[str] = None) -> Optional[str]:
    """보유 계좌 중 환경(모의/실전)에 맞춰 최적의 계좌번호를 자동 판별하여 반환합니다."""
    # 1. Credential Manager에 이미 명시된 계좌번호가 있으면 최우선 반환
    manual_act = get_credential("NH_ISA_ACCOUNT_NO")
    if manual_act and manual_act not in ("12345678-01", "1234567801"):
        return manual_act.replace("-", "").strip()

    # 2. 없으면 NH 서버(/n2/acctinfo)에서 직접 자동 조회
    accounts = fetch_nh_account_list(app_key, app_secret)
    if not accounts:
        return None

    base_url = os.getenv("NHPLUG_BASE_URL", "https://moapi.nhplug.com:8443")
    is_mock = "moapi" in base_url.lower()

    if is_mock:
        # 모의투자 환경에서는 acct_type == '03' 계좌만 유효함
        mock_accounts = [a for a in accounts if a["account_type"] == "03"]
        if mock_accounts:
            return mock_accounts[0]["account_no"]

    # 실전 환경에서는 ISA 또는 종합위탁 계좌 우선
    for acc in accounts:
        if "ISA" in acc["account_name"].upper():
            return acc["account_no"]

    for acc in accounts:
        if acc["account_type"] in ("01", "02"):
            return acc["account_no"]

    return accounts[0]["account_no"]
