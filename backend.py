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

# ====== 模拟数据生成（API不可用时兜底）======
MOCK_STOCKS = [
    ('600519', '贵州茅台', 1299.56, 0.04), ('000001', '平安银行', 11.92, 1.71),
    ('600036', '招商银行', 36.88, 2.15), ('601318', '中国平安', 52.34, 1.56),
    ('300750', '宁德时代', 358.10, -1.50), ('600900', '长江电力', 28.56, 0.32),
    ('601012', '隆基绿能', 22.45, 3.21), ('002415', '海康威视', 32.18, 0.87),
    ('600887', '伊利股份', 28.90, 1.23), ('600276', '恒瑞医药', 45.67, 2.34),
    ('000858', '五粮液', 142.30, -0.56), ('601166', '兴业银行', 18.45, 1.89),
    ('600030', '中信证券', 22.56, 2.78), ('002594', '比亚迪', 268.90, 3.45),
    ('600104', '上汽集团', 15.23, 0.45), ('600585', '海螺水泥', 25.67, -1.23),
    ('000651', '格力电器', 42.10, 1.67), ('600690', '海尔智家', 28.34, 0.89),
    ('300059', '东方财富', 15.89, 4.56), ('600809', '山西汾酒', 120.67, 3.35),
    ('600028', '中国石化', 6.78, 0.15), ('601857', '中国石油', 8.23, -0.24),
    ('600016', '民生银行', 3.64, 3.12), ('002142', '宁波银行', 24.56, 1.45),
    ('601398', '工商银行', 5.89, 0.17), ('601939', '建设银行', 7.12, 0.28),
    ('601288', '农业银行', 4.56, 0.22), ('601328', '交通银行', 6.34, 0.35),
    ('600000', '浦发银行', 8.90, 0.67), ('000333', '美的集团', 62.34, 1.89),
    ('002304', '洋河股份', 98.56, -0.78), ('600438', '通威股份', 28.90, 5.67),
    ('601899', '紫金矿业', 15.67, 2.34), ('600309', '万华化学', 78.90, 1.56),
    ('300124', '汇川技术', 58.23, 0.45), ('002460', '赣锋锂业', 36.78, 2.89),
    ('600703', '三安光电', 15.45, 3.12), ('600745', '闻泰科技', 38.90, -1.45),
    ('000725', '京东方A', 4.56, 0.88), ('300274', '阳光电源', 68.90, 4.32),
    ('600089', '特变电工', 16.78, 1.23), ('002129', '中环股份', 22.34, 2.56),
    ('600111', '北方稀土', 22.56, 3.78), ('600010', '包钢股份', 1.89, 1.07),
    ('600019', '宝钢股份', 6.45, 0.78), ('600031', '三一重工', 18.90, 1.34),
    ('600050', '中国联通', 5.12, 0.39), ('600795', '国电电力', 4.78, 2.15),
]

def generate_mock_stocks():
    """生成逼真的模拟行情数据，价格在真实值附近随机波动"""
    import random
    now = datetime.now()
    stocks = []
    # 各股票锚定特征 [pe, pb, 换手率倾向], 确保筛选总有结果
    profiles = [
        (35, 8, 0.5), (5, 0.8, 2.5), (7, 1.0, 1.8), (10, 1.5, 1.2), (55, 6, 1.5),
        (18, 2.5, 0.3), (25, 4, 3.5), (22, 5, 1.0), (20, 5, 0.8), (45, 7, 1.2),
        (12, 3, 0.6), (6, 0.9, 2.0), (18, 2, 3.8), (40, 5, 2.5), (12, 1.2, 0.4),
        (8, 1.1, 1.5), (10, 2.5, 1.8), (14, 3, 0.7), (30, 4, 4.5), (15, 5, 0.9),
        (9, 0.8, 0.3), (8, 0.9, 0.2), (6, 0.7, 0.1), (5, 0.8, 0.2), (5, 0.7, 0.1),
        (14, 3, 1.0), (12, 3.5, 0.5), (20, 4, 3.2), (17, 3, 2.0), (22, 4, 1.5),
        (25, 2, 1.8), (35, 5, 4.0), (15, 2.5, 1.2), (15, 1.5, 0.6),
    ]
    for i, (code, name, base_price, _) in enumerate(MOCK_STOCKS):
        mp = random.uniform(-0.03, 0.04)  # 市场波动
        change_pct = round(mp * 100 + random.gauss(0, 1.5), 2)
        price = round(base_price * (1 + change_pct / 100), 2)
        prev_close = round(base_price * (1 + random.uniform(-0.01, 0.01)), 2)
        high = round(price * (1 + abs(random.gauss(0, 0.01))), 2)
        low = round(price * (1 - abs(random.gauss(0, 0.01))), 2)
        open_p = round(prev_close * (1 + random.uniform(-0.005, 0.005)), 2)
        amount = round(random.uniform(0.5, 50) * price, 2)
        volume = int(amount / price * 100) if price > 0 else 0
        # 使用锚定特征，确保筛选总有结果
        prof = profiles[i % len(profiles)]
        turnover = round(max(0.1, prof[2] + random.uniform(-0.25, 0.25)), 2)
        pe = round(max(1, prof[0] + random.uniform(-2, 2)), 2)
        pb = round(max(0.1, prof[1] + random.uniform(-0.25, 0.25)), 2)
        amplitude = round(abs(high - low) / prev_close * 100, 2)
        total_mv = round(random.uniform(100, 20000), 2)
        float_mv = round(total_mv * random.uniform(0.3, 1.0), 2)
        h52w = round(price * (1 + random.uniform(0.05, 0.3)), 2)
        l52w = round(price * (1 - random.uniform(0.05, 0.3)), 2)

        stocks.append({
            'code': code, 'name': name, 'price': price, 'prev_close': prev_close,
            'open': open_p, 'high': high, 'low': low,
            'volume': volume, 'amount': amount,
            'change_pct': change_pct, 'change_amount': round(price - prev_close, 2),
            'turnover_rate': turnover, 'pe': pe, 'pb': pb,
            'amplitude': amplitude, 'total_mv': total_mv, 'float_mv': float_mv,
            'high_52w': h52w, 'low_52w': l52w,
            'time': now.strftime('%Y%m%d%H%M%S'),
            'market': '51' if code.startswith('0') or code.startswith('3') else '1',
        })
    return stocks

def get_mock_klines(count=60):
    """生成模拟K线数据"""
    import random
    base = 1300.0
    klines = []
    for i in range(count):
        date = (datetime.now() - timedelta(days=count-i)).strftime('%Y%m%d')
        change = random.gauss(0, 0.02)
        close = round(base * (1 + change), 2)
        open_p = round(base * (1 + random.gauss(0, 0.01)), 2)
        high = round(max(open_p, close) * (1 + abs(random.gauss(0, 0.005))), 2)
        low = round(min(open_p, close) * (1 - abs(random.gauss(0, 0.005))), 2)
        vol = int(random.uniform(1000, 50000))
        klines.append([date, str(open_p), str(close), str(high), str(low), str(vol)])
        base = close  # 下一根基于当前收盘
    return klines

# ====== API路由 ======
@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

@app.route('/api/market-scan')
def api_market_scan():
    codes = ','.join(HOT_STOCKS)
    raw = curl_get(f'https://qt.gtimg.cn/q={codes}', 'gbk')
    if not raw or 'sh600519' not in raw:
        # 兜底：返回模拟数据
        mock = generate_mock_stocks()
        mock.sort(key=lambda x: x['change_pct'], reverse=True)
        limit_up = [s for s in mock if s['change_pct'] >= 9.8]
        avg_change = round(sum(s['change_pct'] for s in mock) / len(mock), 2)
        return jsonify({
            'total_count': len(mock),
            'top_gainers': mock[:15],
            'top_losers': sorted(mock, key=lambda x: x['change_pct'])[:15],
            'limit_up': limit_up[:10],
            'avg_change': avg_change,
            'mock': True,
        })
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
        # 兜底：返回模拟数据
        mock = generate_mock_stocks()
        for s in mock:
            if s['code'] == code:
                return jsonify({**s, 'mock': True})
        return jsonify({'error': 'no_data', 'mock': True})
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
    return jsonify({'error': 'parse_failed', 'mock': True})

@app.route('/api/batch-quotes')
def api_batch_quotes():
    codes = request.args.get('codes', '600519,000001')
    code_list = [c.strip() for c in codes.split(',')]
    tx_codes = ','.join(to_tx_code(c) for c in code_list)
    raw = curl_get(f'https://qt.gtimg.cn/q={tx_codes}', 'gbk')
    if not raw:
        # 兜底：返回模拟数据
        mock_all = generate_mock_stocks()
        mock_filtered = [s for s in mock_all if s['code'] in code_list]
        return jsonify({'stocks': mock_filtered, 'mock': True})
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
        # 兜底：返回模拟K线数据
        mock_klines = get_mock_klines(count)
        return jsonify({'count': len(mock_klines), 'klines': mock_klines, 'mock': True})
    try:
        json_str = re.sub(r'^kline_data\s*=\s*', '', raw).strip().rstrip(';')
        data = json.loads(json_str)
        klines_raw = data.get('data', {}).get(tx_code, {}).get(api_period, [])
        if not klines_raw:
            klines_raw = data.get('data', {}).get(tx_code, {}).get('day', [])
        if not klines_raw:
            klines_raw = data.get('data', {}).get(tx_code, {}).get('qfqday', [])
        if not klines_raw:
            # 解析到数据但为空，也返回模拟数据
            mock_klines = get_mock_klines(count)
            return jsonify({'count': len(mock_klines), 'klines': mock_klines, 'mock': True})
        return jsonify({'count': len(klines_raw), 'klines': klines_raw})
    except Exception as e:
        mock_klines = get_mock_klines(count)
        return jsonify({'error': str(e), 'klines': mock_klines, 'count': len(mock_klines), 'mock': True})

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
    stocks = []
    is_mock = False
    if raw:
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
    if not stocks:
        # 兜底使用模拟数据
        is_mock = True
        stocks = generate_mock_stocks()
    # 应用筛选条件
    filtered = []
    for s in stocks:
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
        filtered.append(s)
    filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    return jsonify({'total': len(filtered), 'stocks': filtered[:20], 'mock': is_mock})

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify({'stocks': []})
    codes = ','.join(HOT_STOCKS)
    raw = curl_get(f'https://qt.gtimg.cn/q={codes}', 'gbk')
    if not raw:
        # 兜底：从模拟数据中搜索
        mock = generate_mock_stocks()
        results = [s for s in mock if q in s['name'].lower() or q in s['code']]
        return jsonify({'stocks': results, 'mock': True})
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
    import os
    port = int(os.environ.get('PORT', 5888))
    app.run(host='0.0.0.0', port=port, debug=False)