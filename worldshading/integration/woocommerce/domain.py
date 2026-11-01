"""Version-independent calculations. No Frappe imports or database side effects."""
import base64
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from datetime import datetime
from urllib.parse import urlsplit


def number(value):
    try:
        result = Decimal(str(value if value is not None and value != '' else 0))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid numeric value')
    if not result.is_finite():
        raise ValueError('Numeric value must be finite')
    return result


def money(value):
    return str(number(value).quantize(Decimal('.001'), rounding=ROUND_HALF_UP))


def utc_datetime(value):
    """Woo *_gmt and the explicitly UTC import cutoff have no local offset."""
    text=str(value or '').replace('T',' ').rstrip('Z')
    if text.endswith('+00:00'):text=text[:-6]
    try:
        return datetime.strptime(text,'%Y-%m-%d %H:%M:%S.%f' if '.' in text else '%Y-%m-%d %H:%M:%S')
    except (ValueError,TypeError):
        raise ValueError('A valid UTC order timestamp is required')


def validate_source_order(order):
    if not isinstance(order,dict):raise ValueError('Woo order must be an object')
    order_id=number(order.get('id'))
    if order_id<=0 or order_id!=int(order_id):raise ValueError('Woo order ID must be a positive integer')
    number(order.get('total'))
    utc_datetime(order.get('date_created_gmt'))
    if order.get('date_modified_gmt'):utc_datetime(order['date_modified_gmt'])
    return int(order_id)


def order_in_window(order,cutoff):
    return utc_datetime(order.get('date_created_gmt'))>=utc_datetime(cutoff)


def available_stock(actual, sales=0, production=0, subcontract=0, drafts=0, buffer=0, factor=1):
    factor = number(factor)
    if factor <= 0:
        raise ValueError('Conversion factor must be positive')
    available = number(actual) - sum(max(Decimal(0),number(v)) for v in [sales, production, subcontract, drafts, buffer])
    return int((max(Decimal(0), available) / factor).to_integral_value(rounding=ROUND_FLOOR))


def combined_stock(bins, drafts=0, buffer=0, factor=1):
    available = Decimal(0)
    for row in bins:
        reservations = sum(max(Decimal(0),number(row.get(field))) for field in
                           ['reserved_qty','reserved_qty_for_production','reserved_qty_for_sub_contract'])
        available += max(Decimal(0),number(row.get('actual_qty'))-reservations)
    return available_stock(available, drafts=drafts, buffer=buffer, factor=factor)


def choose_price(prices, sale_uom, stock_uom, factor):
    exact = [p for p in prices if (p.get('uom') or stock_uom) == sale_uom]
    candidates = exact or [p for p in prices if (p.get('uom') or stock_uom) == stock_uom]
    if len(candidates) != 1:
        raise ValueError('Expected one current general Item Price for the mapped UOM; found %d' % len(candidates))
    rate = number(candidates[0]['price_list_rate'])
    if rate < 0:
        raise ValueError('Negative price is unsupported')
    if not exact:
        rate *= number(factor)
    return money(rate)


def match_line(line, mappings):
    product, variation = int(line.get('product_id') or 0), int(line.get('variation_id') or 0)
    candidates = [m for m in mappings if int(m['product_id']) == product and int(m.get('variation_id') or 0) == variation]
    if len(candidates) != 1:
        raise ValueError('Missing or ambiguous product mapping for %s:%s' % (product, variation))
    result = candidates[0]
    if not result.get('sku') or line.get('sku') != result['sku']:
        raise ValueError('Woo SKU differs from the approved product mapping')
    return result


def match_order_lines(lines, mappings):
    """Validate every mapping before creating any Sales Order dependencies."""
    matched, errors = [], []
    for index, line in enumerate(lines, 1):
        try:
            matched.append(match_line(line, mappings))
        except (ValueError, TypeError, AttributeError) as exc:
            label = line.get('name') or line.get('sku') or 'Product' if isinstance(line, dict) else 'Product'
            errors.append('Line %s (%s): %s' % (index, label, exc))
    if errors:
        raise ValueError('Resolve product mappings before importing this order:\n'+'\n'.join(errors))
    return matched


def affected_stock_items(payload, mappings):
    """Identify exposure by exact target, even if the SKU no longer matches."""
    if not isinstance(payload, dict) or not isinstance(payload.get('line_items'), list) or not payload['line_items']:
        raise ValueError('Cannot identify order product lines')
    items = set()
    for line in payload['line_items']:
        if not isinstance(line, dict):
            raise ValueError('Cannot identify order product line')
        try:
            product = number(line.get('product_id'))
            variation = number(line.get('variation_id'))
            if product <= 0 or variation < 0 or product != int(product) or variation != int(variation):
                raise ValueError('Invalid order product identity')
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Cannot identify order product identity')
        for mapping in mappings:
            if int(mapping['product_id']) == int(product) and int(mapping.get('variation_id') or 0) == int(variation):
                items.add(mapping['item_code'])
    return items


def prepare_order(order, currency='BHD'):
    if order.get('currency') != currency:
        raise ValueError('Order currency differs from connector currency')
    if order.get('refunds') or order.get('status') not in ('pending', 'on-hold', 'processing', 'completed'):
        raise ValueError('Order status/refund requires human review')
    lines = []
    for raw in order.get('line_items', []):
        qty, total = number(raw.get('quantity')), number(raw.get('total'))
        if qty <= 0 or total < 0:
            raise ValueError('Order lines require positive quantity and nonnegative totals')
        lines.append({'source': raw, 'qty': qty, 'total': total, 'rate': total / qty})
    if not lines:
        raise ValueError('Order has no product lines')
    shipping, tax = number(order.get('shipping_total')), number(order.get('total_tax'))
    fees = sum(number(f.get('total')) for f in order.get('fee_lines', []))
    if shipping < 0 or tax < 0 or any(number(f.get('total')) < 0 for f in order.get('fee_lines', [])):
        raise ValueError('Negative shipping/tax/fee requires human review')
    expected = sum(l['total'] for l in lines) + shipping + tax + fees
    if abs(expected - number(order.get('total'))) > Decimal('.001'):
        raise ValueError('Woo line, shipping, fee and tax totals do not reconcile')
    return {'lines': lines, 'shipping': shipping, 'tax': tax, 'fees': fees, 'total': number(order['total'])}


def verify_signature(body, signature, secret):
    if not body or not signature or not secret:
        return False
    expected = base64.b64encode(hmac.new(secret.encode('utf-8'), body, hashlib.sha256).digest()).decode('ascii')
    return hmac.compare_digest(expected, str(signature))


def https_origin(url):
    parsed = urlsplit(url or '')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.netloc!=parsed.hostname
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use an exact HTTPS origin without credentials, port, path, query or fragment')
    return 'https://'+parsed.hostname


def validate_store_url(url,allowed_url='https://testshop.worldshading.com'):
    expected=https_origin(allowed_url)
    if https_origin(url)!=expected:
        raise ValueError('Woo store URL does not match the configured allowed store')
    return expected


def order_fingerprint(order):
    keys = ('currency', 'line_items', 'shipping_total', 'shipping_tax', 'fee_lines',
            'total_tax', 'total', 'billing', 'shipping', 'customer_id', 'discount_total', 'coupon_lines')
    raw = json.dumps({k: order.get(k) for k in keys}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def retry_delay(attempt):
    return min(3600, 60 * (2 ** min(max(int(attempt) - 1, 0), 6)))


def customer_key(order):
    email=((order.get('billing') or {}).get('email') or '').strip().lower()
    external='id:'+str(order['customer_id']) if order.get('customer_id') else 'email:'+email if email else 'order:'+str(order['id'])
    return 'testshop:'+hashlib.sha256(external.encode('utf-8')).hexdigest()[:32]
