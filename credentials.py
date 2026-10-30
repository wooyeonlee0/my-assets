"""Windows Credential Manager (자격 증명 관리자) 연동 보안 자격 증명 헬퍼

금융 API Key, Secret 등 민감 정보를 하드디스크(.env 파일)에 평문으로 남기지 않고,
Windows OS의 DPAPI(Data Protection API) 기반 보안 금고에 안전하게 암호화 보관/조회합니다.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SERVICE_NAME = "NH_PLUG_TRADING_AGENT"


def get_credential(key_name: str, fallback_env: Optional[str] = None) -> str:
    """Windows Credential Manager에서 안전하게 자격 증명을 조회하고,
    없을 경우 지정된 환경변수 또는 .env를 fallback으로 확인합니다.
    """
    # 1. Windows Credential Manager 우선 조회
    try:
        import keyring

        val = keyring.get_password(SERVICE_NAME, key_name)
        if val:
            return val.strip()
    except Exception as e:
        logger.debug(f"[Credentials] Keyring 조회 실패 ({key_name}): {e}")

    # 2. Fallback: OS 환경변수 또는 .env 조회
    env_var_name = fallback_env or key_name
    return os.getenv(env_var_name, "").strip()


def set_credential(key_name: str, value: str) -> bool:
    """Windows Credential Manager에 안전하게 자격 증명을 저장합니다."""
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, key_name, value.strip())
        logger.info(f"[Credentials] Windows 자격 증명 관리자에 '{key_name}' 등록 완료.")
        return True
    except Exception as e:
        logger.error(f"[Credentials] Windows 자격 증명 관리자 저장 실패 ({key_name}): {e}")
        return False


def delete_credential(key_name: str) -> bool:
    """Windows Credential Manager에서 자격 증명을 삭제합니다."""
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, key_name)
        return True
    except Exception:
        return False
