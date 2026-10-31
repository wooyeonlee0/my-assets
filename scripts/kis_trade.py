"""한국투자증권(KIS) Open API 주식 주문 실행 엔진 (GitHub Actions Runner 전용)

- 미국 해외주식 (NVDA, TSLA, AAPL, GOOGL 등) 및 국내주식 (삼성전자 등) 매수/매도 주문 처리
- 환경변수(GitHub Secrets) 기반 인증 (App Key, App Secret, 계좌번호)
"""
import os
import sys
import json
import urllib.request
import urllib.error

def get_env_or_fail(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        print(f"❌ [KIS Engine Error] 필수 환경변수 '{key}' 가 설정되지 않았습니다.")
        sys.exit(1)
    return val

def validate_risk_guard(ticker: str, qty: any, max_qty_limit: int = 100) -> tuple[bool, str, int]:
    """
    🛡️ Risk Guard: 시스템 레벨 강제 안전 검증 (에이전트 실수 및 오발주 원천 차단)
    - 0 이하, 음수, 비숫자 수량 차단
    - 1회 최대 주문 한도(기본 100주) 초과 차단
    - 티커 유효성 확인
    반환: (is_valid, error_msg, qty_int)
    """
    if not ticker or not str(ticker).strip():
        return False, "종목 티커가 비어있습니다.", 0

    try:
        qty_int = int(qty)
    except (ValueError, TypeError):
        return False, f"수량 파라미터가 유효한 정수가 아닙니다: {qty}", 0

    if qty_int <= 0:
        return False, f"비정상적인 주문 수량입니다: {qty_int}주 (0보다 커야 함)", 0

    if qty_int > max_qty_limit:
        return False, f"1회 최대 허용 수량({max_qty_limit}주)을 초과했습니다: {qty_int}주 요청됨", qty_int

    return True, "", qty_int


def send_telegram_alert(text: str):
    """텔레그램 봇으로 주문 체결 실시간 푸시 알림 전송"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        print("ℹ️ [Telegram Alert] 텔레그램 환경변수(TELEGRAM_BOT_TOKEN, CHAT_ID)가 등록되지 않아 푸시 알림을 건너뜁니다.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print("   -> 📱 텔레그램 모바일 푸시 알림 발송 완료!")
    except Exception as e:
        print(f"⚠️ 텔레그램 알림 발송 실패: {e}")

def main():
    print("=" * 60)
    print(" 🚀 KIS Open API Serverless Trade Order Executor")
    print("=" * 60)

    # 1. 환경변수 로드
    app_key = get_env_or_fail("KIS_APP_KEY")
    app_secret = get_env_or_fail("KIS_APP_SECRET")
    cano = get_env_or_fail("KIS_CANO")
    acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD", "01").strip()
    is_mock = os.getenv("KIS_IS_MOCK", "false").lower() == "true"

    # 주문 파라미터 (workflow inputs)
    ticker = os.getenv("ORDER_TICKER", "").strip().upper()
    qty = os.getenv("ORDER_QTY", "1").strip()
    order_type = os.getenv("ORDER_TYPE", "BUY").strip().upper() # BUY or SELL
    market = os.getenv("ORDER_MARKET", "AUTO").strip().upper() # US_NASD, US_NYSE, KR_STOCK, AUTO
    price = os.getenv("ORDER_PRICE", "0").strip() # 0 = 시장가

    if not ticker:
        print("❌ [KIS Engine Error] 종목 티커(ORDER_TICKER)가 누락되었습니다.")
        sys.exit(1)

    # 시장 자동 판별 (6자리 숫자면 국내주식, 알파벳이면 미국주식)
    if market == "AUTO":
        if ticker.isdigit() and len(ticker) == 6:
            market = "KR_STOCK"
        else:
            market = "US_NASD" # 기본 미국 나스닥/뉴욕

    # -------------------------------------------------------------
    # 🛡️ Risk Guard: 시스템 레벨 강제 안전 검증 (에이전트 실수 원천 차단)
    # -------------------------------------------------------------
    max_qty_limit = int(os.getenv("MAX_ORDER_QTY", "100")) # 1회 최대 100주 하드 리밋
    is_valid, err_msg, qty_int = validate_risk_guard(ticker, qty, max_qty_limit)
    if not is_valid:
        err_text = f"❌ [Risk Guard 차단] {err_msg}"
        print(err_text)
        send_telegram_alert(
            f"⚠️ <b>[Risk Guard 주문 차단 알림]</b>\n\n"
            f"• <b>종목</b>: <code>{ticker}</code>\n"
            f"• <b>사유</b>: {err_msg}\n"
        )
        sys.exit(1)

    base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
    print(f"📍 모드: {'[모의투자]' if is_mock else '[실전투자]'}")
    print(f"📍 엔드포인트: {base_url}")
    print(f"📍 대상 종목: {ticker} | 시장: {market} | 주문: {order_type} | 수량: {qty}주 | 가격: {'시장가' if price == '0' else price + '원/달러'}")

    # 2. OAuth 2.0 토큰 발급
    print("\n🔑 1단계: OAuth 2.0 접근 토큰 발급 요청 중...")
    token_url = f"{base_url}/oauth2/tokenP"
    token_payload = json.dumps({
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }).encode("utf-8")

    token_req = urllib.request.Request(
        token_url,
        data=token_payload,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(token_req) as resp:
            token_res = json.loads(resp.read().decode("utf-8"))
            access_token = token_res["access_token"]
            print("   -> ✅ OAuth 2.0 접근 토큰 발급 성공!")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"❌ OAuth 토큰 발급 실패 (HTTP {e.code}): {err_msg}")
        sys.exit(1)

    # 3. 주문 규격 및 바디 구성
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "custtype": "P"
    }

    if market == "KR_STOCK":
        # 국내주식 주문
        order_url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "VTTC0802U" if (is_mock and order_type == "BUY") else \
                "VTTC0801U" if (is_mock and order_type == "SELL") else \
                "TTTC0802U" if order_type == "BUY" else "TTTC0801U"
        headers["tr_id"] = tr_id

        # ORD_DVSN: 01=시장가, 00=지정가
        ord_dvsn = "01" if price == "0" else "00"
        order_body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": ticker,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0" if ord_dvsn == "01" else str(price)
        }
    else:
        # 미국 해외주식 주문
        order_url = f"{base_url}/uapi/overseas-stock/v1/trading/order"
        tr_id = "VTTT1002U" if (is_mock and order_type == "BUY") else \
                "VTTT1001U" if (is_mock and order_type == "SELL") else \
                "TTTT1002U" if order_type == "BUY" else "TTTT1006U"
        headers["tr_id"] = tr_id

        # OVRS_EXCG_CD: NASD(나스닥), NYSE(뉴욕), AMEX(아멕스)
        excg_cd = "NYSE" if market == "US_NYSE" else "NASD"
        # ORD_DVSN: 00=지정가
        order_body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "OVRS_EXCG_CD": excg_cd,
            "PDNO": ticker,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price) if price != "0" else "0",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

    # 4. Hashkey 서명 생성
    print("🔐 2단계: KIS 보안 서명(Hashkey) 생성 중...")
    hash_url = f"{base_url}/uapi/hashkey"
    hash_payload = json.dumps(order_body).encode("utf-8")
    hash_req = urllib.request.Request(
        hash_url,
        data=hash_payload,
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "appkey": app_key,
            "appsecret": app_secret
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(hash_req) as resp:
            hash_res = json.loads(resp.read().decode("utf-8"))
            headers["hashkey"] = hash_res["HASH"]
            print("   -> ✅ 보안 Hashkey 생성 완료!")
    except Exception as e:
        print(f"⚠️ Hashkey 생성 건너뜀 (서버 정책에 따라 계속 진행): {e}")

    # 5. 주문 전송 및 체결 접수
    print(f"\n📡 3단계: 한투 거래소로 주문 전송 중... (TR_ID: {headers['tr_id']})")
    order_req = urllib.request.Request(
        order_url,
        data=json.dumps(order_body).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(order_req) as resp:
            order_res = json.loads(resp.read().decode("utf-8"))
            rt_cd = order_res.get("rt_cd")
            msg_cd = order_res.get("msg_cd")
            msg1 = order_res.get("msg1", "")

            print("-" * 60)
            if rt_cd == "0":
                output_data = order_res.get("output", {})
                odno = output_data.get("ODNO", output_data.get("KRX_FWDG_ORD_ORGNO", "체결완료"))
                print(f"🎉 [주문 성공] {ticker} {qty}주 {order_type} 주문이 정상 접수되었습니다!")
                print(f"   주문번호: {odno}")
                print(f"   응답메시지: {msg1} ({msg_cd})")

                # 텔레그램 체결 성공 푸시 알림
                price_str = "시장가" if price == "0" else f"{price}원/달러"
                type_badge = "🔴 매수 (BUY)" if order_type == "BUY" else "🔵 매도 (SELL)"
                mode_str = "[모의투자]" if is_mock else "[실전투자]"
                
                tg_msg = (
                    f"<b>🎉 한투 KIS 주문 접수 완료 {mode_str}</b>\n\n"
                    f"• <b>종목</b>: <code>{ticker}</code> ({market})\n"
                    f"• <b>구분</b>: <b>{type_badge}</b>\n"
                    f"• <b>수량</b>: <b>{qty}주</b> ({price_str})\n"
                    f"• <b>주문번호</b>: <code>{odno}</code>\n"
                    f"• <b>결과</b>: {msg1}\n\n"
                    f"<i>VALIANT ASSET VAULT · Serverless Trading Engine</i>"
                )
                send_telegram_alert(tg_msg)

            else:
                print(f"⚠️ [주문 반려/거절] {msg1} (코드: {msg_cd})")
                tg_fail_msg = (
                    f"<b>⚠️ 한투 KIS 주문 반려/거절 알림</b>\n\n"
                    f"• <b>종목</b>: <code>{ticker}</code> ({order_type} {qty}주)\n"
                    f"• <b>사유</b>: {msg1} (코드: {msg_cd})\n"
                )
                send_telegram_alert(tg_fail_msg)
            print("-" * 60)

            # GitHub Actions Step Summary 기록
            summary_file = os.getenv("GITHUB_STEP_SUMMARY")
            if summary_file:
                with open(summary_file, "a", encoding="utf-8") as sf:
                    status_icon = "✅" if rt_cd == "0" else "❌"
                    sf.write(f"### {status_icon} KIS 주문 체결 결과\n")
                    sf.write(f"- **종목/티커**: `{ticker}` ({market})\n")
                    sf.write(f"- **구분**: `{order_type}` {qty}주\n")
                    sf.write(f"- **결과**: {msg1} (`{msg_cd}`)\n")

    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"❌ 주문 전송 실패 (HTTP {e.code}): {err_msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()
