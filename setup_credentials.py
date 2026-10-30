"""안전한 자격 증명 등록 대화형 CLI 도구

터미널에서 이 스크립트를 실행하여 Windows 자격 증명 관리자에
NH투자증권 나무 API 키를 암호화하여 저장할 수 있습니다.
화면에 입력된 키는 콘솔에 다시 노출되지 않으며 파일로 저장되지 않습니다.
"""
import sys
import getpass
from credentials import set_credential, get_credential, SERVICE_NAME


def main():
    print("=" * 65)
    print(" 🔒 Windows 자격 증명 관리자(Credential Manager) 보안 키 등록 도구")
    print("=" * 65)
    print("키를 입력하면 Windows OS 보안 금고(DPAPI)에 암호화되어 보관됩니다.")
    print("하드디스크의 텍스트 파일(.env)에 키가 평문으로 남지 않습니다.\n")

    # 1. NHPLUG_APP_KEY
    app_key = input("1. NH투자증권 나무 App Key 입력: ").strip()
    if app_key:
        set_credential("NHPLUG_APP_KEY", app_key)

    # 2. NHPLUG_APP_SECRET (비밀번호처럼 가림 입력)
    try:
        app_secret = getpass.getpass("2. NH투자증권 나무 App Secret 입력 (화면에 안 보임): ").strip()
    except Exception:
        app_secret = input("2. NH투자증권 나무 App Secret 입력: ").strip()

    if app_secret:
        set_credential("NHPLUG_APP_SECRET", app_secret)

    # 3. NH_ISA_ACCOUNT_NO (선택사항으로 변경)
    account_no = input("3. NH투자증권 중개형 ISA 계좌번호 (선택사항, 모르면 엔터 치면 서버에서 자동 조회): ").strip().replace("-", "")
    if account_no:
        set_credential("NH_ISA_ACCOUNT_NO", account_no)
    else:
        print("   -> 계좌번호를 생략하셨습니다. App Key로 NH 서버에 접속하여 자동으로 계좌를 찾습니다.")

    # 4. OPENAI_API_KEY (선택 사항)
    try:
        openai_key = getpass.getpass("4. OpenAI API Key 입력 (선택사항, 화면에 안 보임, 엔터로 스킵): ").strip()
    except Exception:
        openai_key = input("4. OpenAI API Key 입력 (선택사항, 엔터로 스킵): ").strip()

    if openai_key:
        set_credential("OPENAI_API_KEY", openai_key)

    print("\n" + "=" * 65)
    print("✅ 모든 자격 증명이 Windows 자격 증명 관리자에 안전하게 저장되었습니다!")
    print(f"   (서비스 명칭: {SERVICE_NAME})")
    print("   확인: Windows 제어판 ➔ 자격 증명 관리자 ➔ Windows 자격 증명 목록")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
