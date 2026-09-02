"""
A股量化交易系统 - 真实数据后端代理
使用腾讯财经API (qt.gtimg.cn) 通过系统代理获取实时数据
"""
import re
import json
import time
import subprocess
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
from io import StringIO

app = Flask(__name__)
CORS(app)

PROXY = 'http://127.0.0.1:18080'
CURL_BASE = ['curl', '-x', PROXY, '-s', '--max-time', '8']

def curl_get(url, encoding='utf-8'):
    """通过系统代理执行curl请求"""
    try:
        result = subprocess.run(CURL_BASE + [url], capture_output=True, timeout=15)
        if result.returncode == 0 and result.stdout:
            decoded = result.stdout.decode(encoding, errors='replace')
            return decoded
        if result.stderr:
            print(f"[CURL_ERR] stderr: {result.stderr.decode('utf-8','replace')[:200]}", flush=True)
        print(f"[CURL_ERR] returncode={result.returncode}, stdout_len={len(result.stdout) if result.stdout else 0}", flush=True)
        return None
    except Exception as e:
        print(f"[CURL_EXC] {e}", flush=True)
        return None

# ====== 腾讯行情API解析（88字段版）======
# 0:market, 1:name, 2:code, 3:price, 4:prev_close, 5:open,
# 6:volume(手), 31:change_amount, 32:change_pct, 33:high, 34:low,
# 37:amount(万元), 38:turnover_rate, 39:pe, 43:amplitude,
# 44:total_mv(亿), 45:float_mv(亿), 46:pb, 47:high_52w, 48:low_52w

def parse_tx_stock(line):
    """解析腾讯API返回的单只股票数据（88字段版）"""
    parts = line.split('~')
    if len(parts) < 49:
        print(f"[PARSE_FAIL] fields={len(parts)}, line_preview={line[:100]}", flush=True)
        return None
    try:
        def f(idx, default=0):
            v = parts[idx] if idx < len(parts) else ''
            return float(v) if v and v.strip() else default
        return {
            'code': parts[2],
            'name': parts[1],
            'price': f(3),
            'prev_close': f(4),
            'open': f(5),
            'high': f(33),
            'low': f(34),
            'volume': f(6),
            'volume_main': f(36),
            'amount': f(37),
            'change_pct': f(32),
            'change_amount': f(31),
            'turnover_rate': f(38),
            'pe': f(39),
            'pb': f(46),
            'amplitude': f(43),
            'total_mv': f(44),
            'float_mv': f(45),
            'high_52w': f(47),
            'low_52w': f(48),
            'time': parts[30] if len(parts) > 30 else '',
            'market': parts[0],
        }
    except Exception as e:
        print(f"[PARSE_EXC] {e}", flush=True)
        return None

def to_tx_code(code):
    code = code.strip()
    if code.startswith('6'):
        return f"sh{code}"
    return f"sz{code}"

# ====== 预定义热门股票列表 ======
HOT_STOCKS = [
    'sh600519', 'sz000001', 'sh600036', 'sh601318', 'sz300750',
    'sh600900', 'sh601012', 'sz002415', 'sh600887', 'sh600276',
    'sz000858', 'sh601166', 'sh600030', 'sz002594', 'sh600104',
    'sh600585', 'sz000651', 'sh600690', 'sz300059', 'sh600809',
    'sh600028', 'sh601857', 'sh600016', 'sz002142', 'sh601398',
    'sh601939', 'sh601288', 'sh601328', 'sh600000', 'sh600036',
    'sz000333', 'sz002304', 'sh600438', 'sh601899', 'sh600309',
    'sz300124', 'sz002460', 'sh600703', 'sh600745', 'sz000725',
    'sh601012', 'sz300274', 'sh600089', 'sz002129', 'sh600111',
    'sh600010', 'sh600019', 'sh600031', 'sh600050', 'sh600795',
]

# ====== API路由 ======
@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

@app.route('/api/market-scan')
def api_market_scan():
    codes = ','.join(HOT_STOCKS)
    raw = curl_get(f'https://qt.gtimg.cn/q={codes}', 'gbk')
    if not raw or 'sh600519' not in raw:
        return jsonify({'total_count': 0, 'top_gainers': [], 'top_losers': [], 'limit_up': [], 'avg_change': 0, 'error': 'data_fetch_failed'})
    stocks = []
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line or not line.startswith('v_'):
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start < 0 or end <= start:
            continue
        content = line[start+1:end]
        s = parse_tx_stock(content)
        if s:
            stocks.append(s)
    stocks.sort(key=lambda x: x['change_pct'], reverse=True)
    limit_up = [s for s in stocks if s['change_pct'] >= 9.8]
    avg_change = round(sum(s['change_pct'] for s in stocks) / len(stocks), 2) if stocks else 0
    return jsonify({
        'total_count': len(stocks),
        'top_gainers': stocks[:15],
        'top_losers': sorted(stocks, key=lambda x: x['change_pct'])[:15],
        'limit_up': limit_up[:10],
        'avg_change': avg_change,
    })

@app.route('/api/stock-quote')
def api_stock_quote():
    code = request.args.get('code', '600519')
    tx = to_tx_code(code)
    raw = curl_get(f'https://qt.gtimg.cn/q={tx}', 'gbk')
    if not raw:
        return jsonify({'error': 'no_data'})
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line.startswith('v_'):
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start < 0 or end <= start:
            continue
        s = parse_tx_stock(line[start+1:end])
        if s and s['code'] == code:
            return jsonify(s)
    return jsonify({'error': 'parse_failed'})

@app.route('/api/batch-quotes')
def api_batch_quotes():
    codes = request.args.get('codes', '600519,000001')
    tx_codes = ','.join(to_tx_code(c.strip()) for c in codes.split(','))
    raw = curl_get(f'https://qt.gtimg.cn/q={tx_codes}', 'gbk')
    if not raw:
        return jsonify({'error': 'no_data', 'stocks': []})
    stocks = []
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line.startswith('v_'):
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start < 0 or end <= start:
            continue
        s = parse_tx_stock(line[start+1:end])
        if s:
            stocks.append(s)
    return jsonify({'stocks': stocks})

@app.route('/api/kline')
def api_kline():
    code = request.args.get('code', '600519')
    count = int(request.args.get('count', 60))
    period = request.args.get('period', '1d')
    period_map = {'1d': 'qfqday', '1w': 'week', '1m': 'month'}
    api_period = period_map.get(period, 'qfqday')
    url_period = {'1d': 'day', '1w': 'week', '1m': 'month'}.get(period, 'day')
    tx_code = to_tx_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx_code},{url_period},,,{count},qfq&_var=kline_data"
    raw = curl_get(url)
    if not raw:
        return jsonify({'error': 'no_data', 'klines': [], 'count': 0})
    try:
        json_str = re.sub(r'^kline_data\s*=\s*', '', raw).strip().rstrip(';')
        data = json.loads(json_str)
        klines_raw = data.get('data', {}).get(tx_code, {}).get(api_period, [])
        if not klines_raw:
            klines_raw = data.get('data', {}).get(tx_code, {}).get('day', [])
        if not klines_raw:
            klines_raw = data.get('data', {}).get(tx_code, {}).get('qfqday', [])
        return jsonify({'count': len(klines_raw), 'klines': klines_raw})
    except Exception as e:
        return jsonify({'error': str(e), 'klines': [], 'count': 0})

@app.route('/api/technical')
def api_technical():
    code = request.args.get('code', '600519')
    kline_resp = api_kline()
    kline_data = kline_resp.get_json()
    if not kline_data or kline_data.get('count', 0) < 20:
        return jsonify({'error': '数据不足', 'latest_price': 0, 'latest_date': '', 'ma5': 0, 'ma10': 0, 'ma20': 0, 'ma60': 0, 'macd': {}, 'rsi': 0, 'kdj': {}, 'signals': []})
    klines = kline_data['klines']
    closes = [float(k[2]) for k in klines if len(k) >= 5]
    highs = [float(k[1]) for k in klines if len(k) >= 5]
    lows = [float(k[3]) for k in klines if len(k) >= 5]
    dates = [str(k[0]) for k in klines if len(k) >= 5]
    if not closes:
        return jsonify({'error': 'no_close_data'})
    latest_price = closes[-1]
    latest_date = dates[-1] if dates else ''

    def ma(data, n):
        if len(data) < n:
            return sum(data) / len(data)
        return round(sum(data[-n:]) / n, 2)

    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if len(closes) >= 60 else 0

    # MACD
    def ema(data, n):
        k = 2 / (n + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = ema12[-1] - ema26[-1]
    dea = sum(ema12[i] - ema26[i] for i in range(-9, 0)) / 9 if len(closes) >= 26 else dif
    bar = 2 * (dif - dea)

    # RSI(14)
    def rsi(data, n=14):
        if len(data) < n + 1:
            return 50
        gains, losses = 0, 0
        for i in range(-n, 0):
            diff = data[i] - data[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        if losses == 0:
            return 100
        rs = gains / losses
        return round(100 - 100 / (1 + rs), 2)

    rsi_val = rsi(closes)

    # KDJ(9,3,3)
    def kdj(data, high, low, n=9, k1=3, d1=3):
        if len(data) < n:
            return {'k': 50, 'd': 50, 'j': 50}
        recent_h = max(high[-n:])
        recent_l = min(low[-n:])
        if recent_h == recent_l:
            return {'k': 50, 'd': 50, 'j': 50}
        rsv = (data[-1] - recent_l) / (recent_h - recent_l) * 100
        k = round(2/3 * 50 + 1/3 * rsv, 2)
        d = round(2/3 * 50 + 1/3 * k, 2)
        j = round(3 * k - 2 * d, 2)
        return {'k': k, 'd': d, 'j': j}

    kdj_val = kdj(closes, highs, lows)

    # 信号
    signals = []
    if len(closes) >= 10:
        if ma5 > ma10:
            signals.append(f'MA5({ma5})上穿MA10({ma10}) ↑ 金叉')
        else:
            signals.append(f'MA5({ma5})下穿MA10({ma10}) ↓ 死叉')
        if closes[-1] > ma20:
            signals.append('股价在MA20之上 多头趋势')
        else:
            signals.append('股价在MA20之下 空头趋势')
    if kdj_val['k'] > kdj_val['d']:
        signals.append(f'KDJ金叉(K={kdj_val["k"]},D={kdj_val["d"]})')
    else:
        signals.append(f'KDJ死叉(K={kdj_val["k"]},D={kdj_val["d"]})')
    if rsi_val > 70:
        signals.append(f'RSI({rsi_val})超买区 ⚠️')
    elif rsi_val < 30:
        signals.append(f'RSI({rsi_val})超卖区 💡')
    else:
        signals.append(f'RSI({rsi_val})中性区')

    return jsonify({
        'latest_price': latest_price,
        'latest_date': latest_date,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'macd': {'dif': round(dif, 2), 'dea': round(dea, 2), 'bar': round(bar, 2)},
        'rsi': rsi_val,
        'kdj': kdj_val,
        'signals': signals,
    })

@app.route('/api/stock-screener')
def api_stock_screener():
    min_change = request.args.get('min_change', type=float)
    max_change = request.args.get('max_change', type=float)
    min_turnover = request.args.get('min_turnover', type=float)
    max_pe = request.args.get('max_pe', type=float)
    max_pb = request.args.get('max_pb', type=float)
    min_pe = request.args.get('min_pe', type=float)

    codes = ','.join(HOT_STOCKS)
    raw = curl_get(f'https://qt.gtimg.cn/q={codes}', 'gbk')
    if not raw:
        return jsonify({'total': 0, 'stocks': []})
    stocks = []
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line.startswith('v_'):
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start < 0 or end <= start:
            continue
        s = parse_tx_stock(line[start+1:end])
        if not s:
            continue
        if min_change is not None and s['change_pct'] < min_change:
            continue
        if max_change is not None and s['change_pct'] > max_change:
            continue
        if min_turnover is not None and s['turnover_rate'] < min_turnover:
            continue
        if max_pe is not None and (s['pe'] <= 0 or s['pe'] > max_pe):
            continue
        if max_pb is not None and (s['pb'] <= 0 or s['pb'] > max_pb):
            continue
        if min_pe is not None and s['pe'] < min_pe:
            continue
        stocks.append(s)
    stocks.sort(key=lambda x: x['change_pct'], reverse=True)
    return jsonify({'total': len(stocks), 'stocks': stocks[:20]})

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify({'stocks': []})
    codes = ','.join(HOT_STOCKS)
    raw = curl_get(f'https://qt.gtimg.cn/q={codes}', 'gbk')
    if not raw:
        return jsonify({'stocks': []})
    results = []
    for line in raw.strip().split(';'):
        line = line.strip()
        if not line.startswith('v_'):
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start < 0 or end <= start:
            continue
        s = parse_tx_stock(line[start+1:end])
        if s and (q in s['name'].lower() or q in s['code']):
            results.append(s)
    return jsonify({'stocks': results})

# ====== 前端页面托管 ======
@app.route('/')
def index():
    return app.send_static_file('quant-quest-19.html')

if __name__ == '__main__':
    import os
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    os.makedirs(static_dir, exist_ok=True)
    src = os.path.join(os.path.dirname(__file__), 'quant-quest-19.html')
    dst = os.path.join(static_dir, 'quant-quest-19.html')
    if os.path.exists(src) and not os.path.exists(dst):
        import shutil
        shutil.copy2(src, dst)

    print("=" * 50)
    print("A股量化交易系统 - 数据后端(腾讯财经)")
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"监听端口: 5888")
    print(f"热门股票数: {len(HOT_STOCKS)}")
    print(f"前端地址: http://localhost:5888/")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5888, debug=False)