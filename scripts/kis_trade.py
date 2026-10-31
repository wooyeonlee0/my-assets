#!/usr/bin/env python3
"""
Serverless Trade Order Executor via Korea Investment & Securities (KIS) Open API
----------------------------------------------------------------------------------
- 단일 종목 및 다중 종목 배치(Batch / Basket) 지원 단일화 엔진
- 1회 토큰 발급 후 전체 배치 공유
- Sell-First 파이프라인 (매도 우선 ➔ 예수금 확보 ➔ 매수 집행)
- Rate Limit (0.5초) 방어 & 시스템 레벨 Risk Guard
- 텔레그램 체결/차단 실시간 푸시
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import Tuple, Dict, Any, List

# core 모듈 임포트
try:
    from core.trading_core import (
        OrderItem,
        BatchOrder,
        validate_batch_risk_guard,
        parse_order_payload,
        format_batch_summary_html
    )
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from core.trading_core import (
        OrderItem,
        BatchOrder,
        validate_batch_risk_guard,
        parse_order_payload,
        format_batch_summary_html
    )


def get_env_or_fail(var_name: str) -> str:
    val = os.getenv(var_name)
    if not val or not val.strip():
        print(f"❌ [Config Error] 필수 환경변수 '{var_name}'가 누락되었습니다.")
        sys.exit(1)
    return val.strip()


def validate_risk_guard(ticker: str, qty: any, max_qty_limit: int = 100) -> tuple[bool, str, int]:
    """단건 하위 호환 래퍼"""
    if not ticker or not str(ticker).strip():
        return False, "종목 티커가 비어있습니다.", 0

    try:
        qty_str = str(qty).strip()
        if not qty_str.isdigit() and not (qty_str.startswith('-') and qty_str[1:].isdigit()):
            return False, f"수량 파라미터가 유효한 정수가 아닙니다: {qty}", 0
        qty_int = int(qty_str)
    except (ValueError, TypeError):
        return False, f"수량 파라미터가 유효한 정수가 아닙니다: {qty}", 0

    if qty_int <= 0:
        return False, f"비정상적인 주문 수량입니다: {qty_int}주", 0

    if qty_int > max_qty_limit:
        return False, f"1회 최대 허용 수량({max_qty_limit}주)을 초과했습니다: {qty_int}주 요청됨", qty_int

    return True, "", qty_int


def send_telegram_alert(text: str):
    """체결 및 경고 텔레그램 푸시 알림 전송"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
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


def execute_single_order(
    base_url: str,
    access_token: str,
    app_key: str,
    app_secret: str,
    cano: str,
    acnt_prdt_cd: str,
    is_mock: bool,
    item: OrderItem
) -> Tuple[bool, str, str]:
    """단일 종목 한투 API 주문 전송 (국내/미국 자동 분기 및 Hashkey 생성)"""
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "custtype": "P"
    }

    if item.market == "KR_STOCK":
        order_url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "VTTC0802U" if (is_mock and item.side == "BUY") else \
                "VTTC0801U" if (is_mock and item.side == "SELL") else \
                "TTTC0802U" if item.side == "BUY" else "TTTC0801U"
        headers["tr_id"] = tr_id
        ord_dvsn = "01" if item.price == "0" else "00"
        order_body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": item.ticker,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(item.qty),
            "ORD_UNPR": "0" if ord_dvsn == "01" else str(item.price)
        }
    else:
        order_url = f"{base_url}/uapi/overseas-stock/v1/trading/order"
        tr_id = "VTTT1002U" if (is_mock and item.side == "BUY") else \
                "VTTT1001U" if (is_mock and item.side == "SELL") else \
                "TTTT1002U" if item.side == "BUY" else "TTTT1006U"
        headers["tr_id"] = tr_id
        excg_cd = "NYSE" if item.market == "US_NYSE" else "NASD"
        order_body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "OVRS_EXCG_CD": excg_cd,
            "PDNO": item.ticker,
            "ORD_QTY": str(item.qty),
            "OVRS_ORD_UNPR": str(item.price) if item.price != "0" else "0",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

    # Hashkey 생성
    hash_url = f"{base_url}/uapi/hashkey"
    try:
        hash_req = urllib.request.Request(
            hash_url,
            data=json.dumps(order_body).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=UTF-8", "appkey": app_key, "appsecret": app_secret},
            method="POST"
        )
        with urllib.request.urlopen(hash_req, timeout=5) as resp:
            hash_res = json.loads(resp.read().decode("utf-8"))
            headers["hashkey"] = hash_res.get("HASH", "")
    except Exception:
        pass

    # 주문 전송
    try:
        order_req = urllib.request.Request(
            order_url,
            data=json.dumps(order_body).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(order_req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            rt_cd = res_data.get("rt_cd")
            msg1 = res_data.get("msg1", "")
            if rt_cd == "0":
                odno = res_data.get("output", {}).get("ODNO", "접수완료")
                return True, odno, msg1
            return False, "", f"[{res_data.get('msg_cd')}] {msg1}"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8") if e.fp else str(e)
        return False, "", f"HTTP {e.code}: {err_msg}"
    except Exception as e:
        return False, "", str(e)


def main():
    print("=" * 60)
    print(" 🚀 KIS Open API Serverless Trade Order Executor (Batch/Single)")
    print("=" * 60)

    # 1. 계좌 환경변수 로드
    app_key = get_env_or_fail("KIS_APP_KEY")
    app_secret = get_env_or_fail("KIS_APP_SECRET")
    cano = get_env_or_fail("KIS_CANO")
    acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD", "01").strip()
    is_mock = os.getenv("KIS_IS_MOCK", "false").lower() == "true"
    max_qty_limit = int(os.getenv("MAX_ORDER_QTY", "100"))

    # 2. 주문 페이로드 파싱 (배치 JSON 또는 단건 파라미터 자동 호환)
    batch_raw = os.getenv("ORDER_BATCH_JSON", "").strip()
    if batch_raw:
        success, err, batch = parse_order_payload(batch_raw)
        if not success:
            print(f"❌ [Payload Error] {err}")
            sys.exit(1)
    else:
        # 기존 단건 파라미터 호환
        ticker = os.getenv("ORDER_TICKER", "").strip().upper()
        if not ticker:
            print("❌ [KIS Engine Error] 주문 종목(ORDER_TICKER 또는 ORDER_BATCH_JSON)이 누락되었습니다.")
            sys.exit(1)
        qty = os.getenv("ORDER_QTY", "1").strip()
        side = os.getenv("ORDER_TYPE", "BUY").strip().upper()
        market = os.getenv("ORDER_MARKET", "AUTO").strip().upper()
        price = os.getenv("ORDER_PRICE", "0").strip()
        batch = BatchOrder(orders=[OrderItem(ticker=ticker, qty=qty, side=side, price=price, market=market)])

    # 3. 통합 Risk Guard & Sell-First 순서 정렬
    is_valid, err_msg, validated_batch = validate_batch_risk_guard(batch, max_single_qty=max_qty_limit)
    if not is_valid:
        err_text = f"❌ [Risk Guard 차단] {err_msg}"
        print(err_text)
        send_telegram_alert(f"⚠️ <b>[Risk Guard 주문 차단 알림]</b>\n\n• 사유: {err_msg}")
        sys.exit(1)

    base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
    print(f"📍 모드: {'[모의투자]' if is_mock else '[실전투자]'}")
    print(f"📍 총 실행할 주문 항목 수: {len(validated_batch.orders)}건 (타입: {validated_batch.batch_type})")

    # 4. OAuth 2.0 토큰 발급 (1회 발급 후 전체 배치 공유)
    print("\n🔑 OAuth 2.0 접근 토큰 발급 요청 중...")
    token_url = f"{base_url}/oauth2/tokenP"
    token_payload = json.dumps({"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}).encode("utf-8")
    token_req = urllib.request.Request(token_url, data=token_payload, headers={"Content-Type": "application/json; charset=UTF-8"}, method="POST")

    try:
        with urllib.request.urlopen(token_req) as resp:
            token_res = json.loads(resp.read().decode("utf-8"))
            access_token = token_res["access_token"]
            print("   -> ✅ OAuth 2.0 접근 토큰 발급 성공!")
    except Exception as e:
        print(f"❌ OAuth 토큰 발급 실패: {e}")
        send_telegram_alert(f"❌ [한투 인증 실패] OAuth 토큰 발급 오류: {e}")
        sys.exit(1)

    # 5. Sell-First 파이프라인 순차 집행 (Rate Limit 0.5초 방어)
    results = []
    print(f"\n📡 배치 주문 파이프라인 가동 시작...")

    for idx, item in enumerate(validated_batch.orders, 1):
        side_ko = "매도" if item.side == "SELL" else "매수"
        print(f"\n[{idx}/{len(validated_batch.orders)}] {item.ticker} {item.qty}주 {side_ko} 실행 중...")
        
        ok, odno, msg = execute_single_order(base_url, access_token, app_key, app_secret, cano, acnt_prdt_cd, is_mock, item)
        results.append({"item": item, "ok": ok, "odno": odno, "msg": msg})

        if ok:
            print(f"   -> 🎉 성공! 주문번호: {odno}")
        else:
            print(f"   -> ⚠️ 실패: {msg}")

        # 한투 TPS 제한 보호
        if idx < len(validated_batch.orders):
            time.sleep(0.5)

    # 6. 종합 결과 집계 및 텔레그램 푸시 발송
    success_count = sum(1 for r in results if r["ok"])
    total_count = len(results)

    status_badge = "✅ [배치 체결 완료]" if success_count == total_count else "⚠️ [배치 부분 체결]" if success_count > 0 else "❌ [배치 주문 실패]"
    alert_lines = [
        f"<b>{status_badge}</b>\n",
        f"• <b>결과 요약</b>: 총 {total_count}건 중 <b>{success_count}건 성공</b>",
        "───────────────────────"
    ]

    for r in results:
        it = r["item"]
        side_badge = "🔴 매수" if it.side == "BUY" else "🔵 매도"
        if r["ok"]:
            alert_lines.append(f"  • {side_badge} <code>{it.ticker}</code> {it.qty}주: <b>접수성공</b> (주문번호: <code>{r['odno']}</code>)")
        else:
            alert_lines.append(f"  • {side_badge} <code>{it.ticker}</code> {it.qty}주: ❌ 실패 ({r['msg']})")

    alert_lines.append("───────────────────────")
    alert_lines.append(f"모드: {'[모의투자]' if is_mock else '[실전투자]'}")

    send_telegram_alert("\n".join(alert_lines))
    print("\n" + "=" * 60)
    print(f"🏁 전체 파이프라인 종료: {success_count}/{total_count} 성공")
    print("=" * 60)


if __name__ == "__main__":
    main()
