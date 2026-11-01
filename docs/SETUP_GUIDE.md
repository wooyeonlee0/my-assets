# 🚀 VALIANT CARSON 종합 설정 가이드 (KIS API & 텔레그램)

본 문서는 **한국투자증권(KIS) Open API**와 **텔레그램 알림 봇**을 설정하여, Google One AI Premium(Gemini Pro, Argon) 기반의 Web-Direct Closed-Loop 트레이딩 시스템을 완벽하게 가동하는 전체 세팅 매뉴얼입니다.

---

## 📌 전체 시스템 동작 개요

```
[ 내 자산 웹앱 (Chrome/PWA) ]  👉👉👉  [ Google Gemini (@valiant-pb) ]
  • 실시간 자산 비중 복사                    • 포트폴리오 심층 분석
  • 원터치 [🧠 Gemini] 호출                  • 신규 유망주/리밸런싱 제안
             ▲                                            │
             │ (주문 코드 복사 & [📥 불러오기])             ▼
[ 리밸런싱 바스켓 (모달) ]     ◀◀◀◀  [ 제안: TICKER.수량.S/B ]
  • Sell-First 순차 정렬
  • 6자리 보안 PIN 입력
             │
             ▼
[ KIS 증권사 주문 집행 ] ──── 체결 영수증 ────▶ [ 텔레그램 모바일 알림 ]
  • 모의/실전 API 호출                            • 1줄 결과 푸시 수신
```

---

## 1. 한국투자증권(KIS) Open API 발급 및 세팅

### 1단계: KIS Developers 포털 접속 및 로그인
1. [한국투자증권 KIS Developers](https://apiportal.koreainvestment.com/)에 접속하여 로그인합니다.
2. (계좌가 없는 경우 한국투자증권 스마트폰 앱에서 비대면 계좌 개설 필요)

### 2단계: KIS Open API 서비스 신청
1. 상단 메뉴 **[고객지원] ➔ [Kopen API 서비스 신청]** 클릭
2. **신청 구분 선택**:
   - 처음 검증 시: **모의투자 Open API** 신청 권장 (가상 자금으로 안전 테스트)
   - 실전 매매 시: **실전투자 Open API** 신청
3. 본인 인증 후 **AppKey** 및 **AppSecret**이 화면에 발급됩니다.
   > ⚠️ **주의**: `AppSecret`은 발급 시 단 1회만 노출되므로 반드시 메모장에 안전하게 복사해 두세요!

### 3단계: 내 계좌번호 확인
- 한국투자증권 종합계좌번호는 총 10자리입니다:
  - **계좌번호 앞 8자리** (`CANO`): 예) `12345678`
  - **계좌 상품코드 2자리** (`ACNT_PRDT_CD`): 보통 종합위탁계좌는 `01`입니다.

---

## 2. 텔레그램 체결 영수증 알림 세팅 (옵션 2)

체결 결과를 스마트폰 텔레그램으로 1줄 영수증 푸시를 받기 위한 세팅입니다. (3분 소요)

### 1단계: 텔레그램 봇 생성 (@BotFather)
1. 스마트폰 텔레그램 검색창에 `@BotFather` 검색 (파란색 인증 체크마크 확인)
2. 대화방 진입 후 `/newbot` 입력
3. 봇의 표시 이름 입력 (예: `My Valiant Asset Bot`)
4. 봇의 유저네임 입력 (반드시 `bot`으로 끝나야 함, 예: `wooyeon_valiant_bot`)
5. 생성이 완료되면 아래와 같은 **HTTP API Token**이 발급됩니다:
   ```
   7123456789:ABCdefGhIJKlmNoPQRstuVWXyz123456789
   ```
   *(이 값이 `TELEGRAM_BOT_TOKEN` 입니다)*

### 2단계: 내 텔레그램 Chat ID 확인 (@userinfobot)
1. 텔레그램 검색창에 `@userinfobot` 검색
2. 대화방 진입 후 `/start` 전송
3. 봇이 답장으로 내 정보를 알려줍니다:
   ```
   Id: 123456789
   First: Wooyeon
   ...
   ```
   *(여기서 숫자 `123456789`가 본인의 `TELEGRAM_CHAT_ID` 입니다)*

### 3단계: 내 봇 활성화 (중요!)
- 방금 1단계에서 만든 본인의 봇(`@wooyeon_valiant_bot`)을 검색하여 들어간 뒤,
- 하단의 **`[시작(Start)]`** 버튼을 누르거나 `/start` 메시지를 1회 전송합니다.
  *(이 작업을 해야 봇이 나에게 먼저 메시지를 보낼 수 있는 권한이 생깁니다)*

---

## 3. 웹앱 및 GitHub에 키 등록하는 방법

보안을 위해 API 키와 비밀번호는 소스코드에 절대 저장하지 않으며, 아래 2곳에 안전하게 등록합니다:

### 방법 A: 웹앱 화면에서 등록 (브라우저 로컬 암호화)
1. 내 자산 웹앱 접속 (`https://wooyeonlee0.github.io/my-assets/`)
2. 우측 상단 **`⚙️ (설정)`** 아이콘 터치
3. 설정 모달에서:
   - **GitHub 저장소 경로**: `wooyeonlee0/my-assets`
   - **GitHub PAT**: 발급받은 Personal Access Token 입력
   - **Google Gemini API Key**: 무료 API 키 입력 (Vision 이미지 분석용)
4. 저장 터치 ➔ 폰 브라우저 로컬 스토리지에만 보관됩니다.

### 방법 B: GitHub Secrets 등록 (클라우드 러너 체결용)
웹앱에서 6자리 PIN을 누르면 백그라운드 GitHub Actions 러너가 한투 API를 호출하므로, 본인의 GitHub 저장소에 시크릿을 등록합니다:

1. 본인의 GitHub 저장소(`https://github.com/wooyeonlee0/my-assets`) 접속
2. **Settings ➔ Secrets and variables ➔ Actions** 이동
3. **[New repository secret]** 버튼을 눌러 아래 6개 항목을 등록합니다:

| Secret 이름 | 설명 | 예시 값 |
| :--- | :--- | :--- |
| `KIS_APP_KEY` | 한투 Developers 발급 AppKey | `PSxxxxxxxxxxxxxxxxxxxx` |
| `KIS_APP_SECRET` | 한투 Developers 발급 AppSecret | `abcdefghijklmnopqrstuvwxyz...` |
| `KIS_CANO` | 계좌번호 앞 8자리 | `12345678` |
| `KIS_ACNT_PRDT_CD` | 계좌 상품코드 2자리 | `01` |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 BotFather 발급 토큰 | `7123456789:ABCdef...` |
| `TELEGRAM_CHAT_ID` | 내 텔레그램 유저 ID 번호 | `123456789` |
| `TRADING_PIN_HASH` | 2차 보안 PIN의 SHA-256 해시값 (옵션/추천) | `8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92` |

> [!TIP]
> 모의투자로 먼저 테스트하고 싶으시다면, 한투 Developers에서 **모의투자용 AppKey/AppSecret**을 발급받아 위 Secrets에 등록하시면 실제 돈이 나가지 않고 가상 체결로 완벽하게 안전 검증을 마칠 수 있습니다!

---

## 4. 최종 연결 테스트 및 검증

모든 키 등록을 마친 후 로컬에서 아래 명령어로 1초 만에 전체 파이프라인 무결성을 검증할 수 있습니다:

```bash
python -m unittest tests/test_trading_core.py tests/test_telegram_trading.py -v
```
*출력 결과: `Ran 40 tests in 0.003s ... OK` ➔ 40개 가드레일 및 통신 테스트 100% 통과 확인!*
