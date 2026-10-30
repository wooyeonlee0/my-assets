import urllib.request
import json
import datetime
from pathlib import Path

dates = ['2026-06-23', '2026-07-31', '2026-08-31', '2026-09-30', '2026-10-30']
notes = {
    '2026-06-23': '6월 23일 기준 포트폴리오 세팅 (보유 종목 확정)',
    '2026-07-31': '7월 말 월간 결산 (환율 및 기술주 시세 반영)',
    '2026-08-31': '8월 말 월간 결산 (장기 보유 유지)',
    '2026-09-30': '9월 말 월간 결산 (장기 보유 유지)',
    '2026-10-30': '더리치 실데이터 동기화 및 3사 통합 결산'
}

ticker_map = {
    'NVDA': 'NVDA',
    'GOOGL': 'GOOGL',
    'TSLA': 'TSLA',
    'AAPL': 'AAPL',
    'CCL': 'CCL',
    '005930': '005930.KS',
    'QQQ': 'QQQ',
    'SSO': 'SSO',
    '133690': '133690.KS',
    'DAL': 'DAL',
    'BA': 'BA',
    '360750': '360750.KS',
    'SPY': 'SPY',
    'MAR': 'MAR',
    'META': 'META',
    'FIDELITY': 'SPY',
    'SAMSUNG_KOR': '005930.KS',
    'US_AI_BIG': 'QQQ',
    'OTHERS': 'SPY'
}

def get_prices(symbol):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())['chart']['result'][0]
        timestamps = data['timestamp']
        closes = data['indicators']['quote'][0]['close']
        date_map = {}
        for t, c in zip(timestamps, closes):
            if c is not None:
                d_str = datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d')
                date_map[d_str] = c
        all_dates = sorted(date_map.keys())
        res = {}
        for td in dates:
            cand = [d for d in all_dates if d <= td]
            res[td] = date_map[cand[-1]] if cand else date_map[all_dates[0]]
        return res
    except Exception as e:
        print(f'Err {symbol}: {e}')
        return {td: 1.0 for td in dates}

price_history = {}
for code, yticker in ticker_map.items():
    price_history[code] = get_prices(yticker)
price_history['USD_KRW'] = get_prices('KRW=X')

with open('data/toss_account.json', 'r', encoding='utf-8') as f:
    toss = json.load(f)

# External fixed cash (NH 나무 예수금 1,680,000)
other_cash = 1680000.0

history_records = []
rate_now = price_history['USD_KRW']['2026-10-30']

for td in dates:
    rate_d = price_history['USD_KRW'][td]
    total_cash = toss['deposit_cash'] + other_cash
    pos_values = {}
    
    for pos in toss['positions']:
        code = pos['stock_code']
        name = pos['stock_name']
        eval_now = pos['eval_amount']
        
        if code == 'USD_CURRENCY':
            val_d = (eval_now / rate_now) * rate_d
            total_cash += val_d # Count dollar cash in cash
        elif pos['asset_class'] == 'FOREIGN_STOCK':
            p_now = price_history[code]['2026-10-30']
            p_d = price_history[code][td]
            shares = (eval_now / rate_now) / p_now
            val_d = shares * p_d * rate_d
            pos_values[name] = val_d
        elif pos['asset_class'] in ('DOMESTIC_STOCK', 'DOMESTIC_ETF'):
            p_now = price_history[code]['2026-10-30']
            p_d = price_history[code][td]
            shares = eval_now / p_now
            val_d = shares * p_d
            pos_values[name] = val_d
        else:
            pos_values[name] = eval_now

    total_net_worth = total_cash + sum(pos_values.values())
    cash_ratio = round(total_cash / total_net_worth, 4)
    
    # Calculate top stock weights
    sorted_stocks = sorted(pos_values.items(), key=lambda x: x[1], reverse=True)
    stock_weights = {k: round(v / total_net_worth, 3) for k, v in sorted_stocks[:12]}
    
    record = {
        'timestamp': td,
        'total_net_worth': round(total_net_worth, 0),
        'total_cash': round(total_cash, 0),
        'cash_ratio': cash_ratio,
        'stock_weights': stock_weights,
        'note': notes[td]
    }
    history_records.append(record)

with open('data/portfolio_history.json', 'w', encoding='utf-8') as f:
    json.dump(history_records, f, indent=2, ensure_ascii=False)

print('Updated portfolio_history.json successfully!')
for r in history_records:
    print(r['timestamp'], f"{r['total_net_worth']:,.0f} KRW", f"Cash: {r['cash_ratio']*100:.1f}%")
