"""Human-readable lineage from recorded inputs, without asking an LLM."""
import math


def build_provenance(stock, strategy):
    fields = {condition['field'] for condition in strategy['conditions']}
    rows = []
    def recorded(field):
        value = stock.get(field)
        if field == 'industries':
            return isinstance(value, list) and bool(value)
        try:
            return not isinstance(value, bool) and math.isfinite(float(value))
        except (TypeError, ValueError):
            return False
    def add(key, title, source, basis, time_label, timestamp, used_fields, **extra):
        available = sum(recorded(field) for field in used_fields)
        rows.append({'key': key, 'title': title, 'source': source, 'basis': basis, 'time_label': time_label,
                     'timestamp': timestamp, 'availability': 'available' if available == len(used_fields) else 'partial' if available else 'missing', **extra})
    valuation = fields & {'pe_ttm', 'pb_mrq'}
    if valuation:
        add('valuation', '估值数据', '扶摇金融 API · 估值快照',
            '；'.join(text for field, text in [('pe_ttm', 'PE TTM 使用过去12个月盈利口径'), ('pb_mrq', 'PB MRQ 使用最近报告期净资产口径')] if field in valuation) + '。负值或零值不按低估值通过。',
            '上游数据时间', stock.get('valuation_timestamp'), valuation)
    financial = fields & {'parent_net_profit_growth_pct', 'roe_pct', 'revenue_growth_pct'}
    if financial:
        add('financial', '财报指标', '扶摇金融 API · 财务指标',
            '同一只股票使用同一报告期。' + '；'.join(text for field, text in [('parent_net_profit_growth_pct', '归母净利润与去年同期比较'), ('revenue_growth_pct', '营业收入与去年同期比较'), ('roe_pct', 'ROE 使用报告期加权平均值，不自行年化')] if field in financial) + '。',
            '本次查询时间', stock.get('financial_fetched_at'), financial, report=stock.get('financial_report'))
    if 'industries' in fields:
        add('industry', '行业归属', '扶摇金融 API · 同花顺行业分类', '按实际行业归属核验，所选行业满足任一项即可。查询时间不代表行业关系生效时间。',
            '本次查询时间', stock.get('industry_fetched_at'), ['industries'], industry_names=[item['name'] for item in stock.get('industries') or []])
    if 'volatility_20d_pct' in fields:
        prices = stock.get('recent_closes') or []
        # Only expose a complete, valid recorded window as calculation inputs.
        valid = isinstance(prices, list) and len(prices) == 21 and all(isinstance(item, dict) and all(type(item.get(key)) in (float, int) and math.isfinite(item[key]) and item[key] > 0 for key in ('date_ms', 'close_price')) for item in prices)
        valid = valid and all(left['date_ms'] < right['date_ms'] for left, right in zip(prices, prices[1:]))
        window = [{'date_ms': item['date_ms'], 'close_price': item['close_price']} for item in prices] if valid else []
        add('volatility', '波动率计算', '扶摇金融 API · 日K线 + StockLens 本地计算',
            '使用21个完整交易日前复权收盘价，形成20个日收益率，计算样本标准差，未年化。缺失或不齐时不以0补齐。',
            '完整日K线截至', stock.get('kline_timestamp'), ['volatility_20d_pct'], prices=window)
    return rows
