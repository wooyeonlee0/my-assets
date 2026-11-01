# 텔레그램 체결 영수증 알림 봇 가이드 (옵션 2: Notification Channel)

본 가이드는 웹앱(`index.html`)에서 6자리 PIN으로 실행된 **한국투자증권(KIS) 주문 체결 결과 영수증**을 모바일 텔레그램으로 안전하게 실시간 수신하기 위한 설정 및 운영 매뉴얼입니다.

---

## 1. 역할 및 아키텍처 (Web-Direct Closed-Loop)

- **주문 실행 (Web)**: 모바일/PC 웹앱(`https://wooyeonlee0.github.io/my-assets/`)의 리밸런싱 바스켓에서 6자리 PIN을 입력하여 KIS 증권사 주문을 즉시 실행합니다.
- **결과 수신 (Telegram)**: 주문이 체결되면 백엔드/GitHub Actions 러너가 체결 결과 요약 영수증 1줄을 본인의 텔레그램으로 즉시 푸시합니다.
  ```
  🧾 [KIS 체결 영수증]
  • NVDA 3주 매도 완료 (체결가: $138.20)
  • GOOGL 2주 매수 완료 (체결가: $165.40)
  • 주문 일시: 2026-11-01 14:30:15
  ```

---

## 2. 필수 환경변수 설정

체결 알림 푸시를 위해 시스템 환경변수 또는 GitHub Secrets에 아래 값을 설정합니다:

| 환경변수 | 필수 여부 | 설명 |
| :--- | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | **필수** | BotFather에서 발급받은 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | **필수** | 본인의 고유 Telegram Chat ID (알림 수신함) |
| `KIS_APP_KEY` | **필수** | 한국투자증권 Open API AppKey |
| `KIS_APP_SECRET` | **필수** | 한국투자증권 Open API AppSecret |
| `KIS_CANO` | **필수** | 종합계좌번호 앞 8자리 |
| `KIS_ACNT_PRDT_CD` | **필수** | 계좌상품코드 2자리 (보통 `01`) |

---

## 3. 텔레그램 세팅 3단계

1. **봇 생성 (@BotFather)**:
   - 텔레그램에서 `@BotFather` 검색 ➔ `/newbot` 입력
   - 봇 이름 및 유저네임 지정 (예: `my_valiant_bot`)
   - 발급된 **HTTP API Token** 복사 (`TELEGRAM_BOT_TOKEN`)
2. **내 Chat ID 확인 (@userinfobot)**:
   - 텔레그램 검색창에 `@userinfobot` 검색 ➔ `/start` 전송
   - 반환되는 숫자 형태의 `Id` 확인 (`TELEGRAM_CHAT_ID`)
3. **내 봇 활성화**:
   - 내가 만든 봇 대화방으로 들어가서 **`시작(Start)`** 버튼 또는 `/start`를 한 번 전송해야 봇이 나에게 메시지를 보낼 수 있습니다.

---

## 4. 단위 테스트 무결성 검증

```bash
python -m unittest tests/test_telegram_trading.py -v
```
*(40개 테스트 100% 무결성 통과)*
