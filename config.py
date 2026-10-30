import os
from typing import Optional
from dotenv import load_dotenv

# .env 로드
load_dotenv()


class Config:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    NHPLUG_APP_KEY: str = os.getenv("NHPLUG_APP_KEY", "")
    NHPLUG_APP_SECRET: str = os.getenv("NHPLUG_APP_SECRET", "")
    NHPLUG_BASE_URL: str = os.getenv(
        "NHPLUG_BASE_URL", "https://moapi.nhplug.com:8443"
    )
    NH_ISA_ACCOUNT_NO: str = os.getenv("NH_ISA_ACCOUNT_NO", "")
    ORDER_AMOUNT_LIMIT: int = int(os.getenv("ORDER_AMOUNT_LIMIT", "3000000"))
    ORDER_API_ENDPOINT_STYLE: str = os.getenv("ORDER_API_ENDPOINT_STYLE", "cash")
    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

    @classmethod
    def apply_to_env(cls):
        """nhplug 라이브러리가 참조할 수 있도록 os.environ을 동기화합니다."""
        if cls.NHPLUG_APP_KEY:
            os.environ["NHPLUG_APP_KEY"] = cls.NHPLUG_APP_KEY
        if cls.NHPLUG_APP_SECRET:
            os.environ["NHPLUG_APP_SECRET"] = cls.NHPLUG_APP_SECRET
        if cls.NHPLUG_BASE_URL:
            os.environ["NHPLUG_BASE_URL"] = cls.NHPLUG_BASE_URL


# 시스템 초기화 시 환경변수 동기화
Config.apply_to_env()
