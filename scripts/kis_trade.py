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
            else:
                print(f"⚠️ [주문 반려/거절] {msg1} (코드: {msg_cd})")
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
