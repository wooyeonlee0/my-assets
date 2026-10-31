# 복합 리밸런싱 배치(Rebalancing Basket) 주문 기술 명세서

본 문서는 7.1억 원 실자산 포트폴리오를 관리하기 위한 **단일 트레이딩 코어(`core/trading_core.py`)** 및 **Sell-First 복합 배치 주문 파이프라인**의 기술 명세 및 운영 가이드입니다.

---

## 1. 개요 및 설계 목적

단일 종목 매매 방식의 한계를 극복하고, 자산 비중 리밸런싱 시 발생하는 번거로움과 예수금 부족 문제를 원천 차단하기 위해 구축되었습니다.

- **Sell-First 파이프라인**: 매도(SELL) 주문을 항상 매수(BUY)보다 먼저 체결하여 예수금을 확보한 뒤 매수를 집행합니다.
- **1-PIN 일괄 인증**: 3~10개 종목을 묶은 배치 주문을 단 1회의 6자리 보안 PIN 입력으로 일괄 체결합니다.
- **단일화 아키텍처**: 웹(장바구니 바스켓)과 텔레그램(AI 카드 및 가상 키패드)이 동일한 표준 배치 데이터 규격을 공유하여 코드 중복을 0%로 줄였습니다.

---

## 2. 표준 데이터 규격 (JSON Schema)

### BatchOrder 모델
```json
{
  "batch_id": "b_a1b2c3d4",
  "batch_type": "REBALANCE",
  "created_at": 1730380000.0,
  "orders": [
    {
      "ticker": "NVDA",
      "qty": 3,
      "side": "SELL",
      "price": "0",
      "market": "US_NASD"
    },
    {
      "ticker": "GOOGL",
      "qty": 2,
      "side": "BUY",
      "price": "0",
      "market": "US_NASD"
    },
    {
      "ticker": "005930",
      "qty": 10,
      "side": "BUY",
      "price": "0",
      "market": "KR_STOCK"
    }
  ]
}
```

- `market`: `AUTO` 지정 시 6자리 숫자면 `KR_STOCK`(국내주식), 알파벳이면 `US_NASD`(미국주식)로 자동 판별됩니다.
- `price`: `"0"`은 시장가 주문입니다.

---

## 3. Gemini AI Pro(Argon) ➔ 텔레그램 딥링크 규격 (Flow 1: Closed-Loop)

구독 중인 **Google One AI Premium (Gemini Advanced/Pro, Argon 모델)**을 100% 무료(유료 API 0원)로 활용하기 위해 텔레그램의 64글자 딥링크 제한을 충족하는 초소형 콤팩트 인코딩/디코딩 규격을 제공합니다.

### 콤팩트 주문 포맷 (Compact Order Format)
`https://t.me/<BOT_USERNAME>?start=<COMPACT_PAYLOAD>`

- **구조**: `TICKER.QTY.SIDE_TICKER.QTY.SIDE`
  - `S`: SELL (매도)
  - `B`: BUY (매수)
  - `_`: 다중 종목 구분자
- **예시**:
  - `TSLA.3.S_NVDA.2.B` (테슬라 3주 매도 후 엔비디아 2주 매수, 19글자)
  - `NVDA.5.B` (엔비디아 5주 단건 매수, 8글자)
- **보안 및 규격 원칙**:
  1. **Sell-First 순서 보장**: 인코더(`encode_compact_order`)가 매도(S) 종목을 무조건 앞단에 정렬하여 출력.
  2. **64자 제한 엄수**: 5~6개 종목을 묶어도 45자 이내로 전송되어 텔레그램 파라미터 규격을 완벽 준수.
  3. **가상 키패드 즉시 호출**: 수신된 `/start <payload>`는 텔레그램 봇에서 파싱 즉시 리밸런싱 요약 카드와 6자리 PIN 가상 키패드로 렌더링.

---

## 4. 5중 보안 가드레일 (Total 5-Layer Defense)

1. **화이트리스트**: 등록된 단 1명의 Telegram User ID 외 모든 제3자 접근 원천 차단.
2. **Human-in-the-Loop**: AI에게 주문 API 권한 0% 부여 (사용자 직접 터치 필수).
3. **2차 보안 PIN 가상 키패드**: 6자리 PIN 모르면 0원도 주문 불가 (3회 오입력 시 주문 영구 파기).
4. **멱등성 & 5분 TTL**: 버튼 터치 즉시 잠금 상태로 전환되어 더블 클릭 방어, 300초 경과 시 자동 만료.
5. **시스템 레벨 Risk Guard**:
   - 1회 배치 최대 종목 수: **10개 종목** 이하 강제
   - 종목당 1회 최대 주문 수량: **100주** 이하 강제
   - 0 이하 / 음수 / 비정상 수량 차단
   - 종목 간 **0.5초 딜레이**를 강제하여 증권사 초당 호출 제한(Rate Limit) 방어.

---

## 5. 자동화 테스트 무결성 검증

- **테스트 스위트 파일**:
  - `tests/test_trading_core.py` (코어 및 콤팩트 딥링크 14개 테스트)
  - `tests/test_telegram_trading.py` (텔레그램, 딥링크 E2E 및 보안 26개 테스트)
- **실행 명령**:
  ```bash
  python -m unittest tests/test_trading_core.py tests/test_telegram_trading.py -v
  ```
- **검증 결과**: **총 40개 테스트 ALL PASSED (0.003초 소요)**
