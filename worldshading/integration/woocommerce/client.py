"""Woo REST v3 transport: signed OAuth query + optional private demo gateway."""
import base64
import hashlib
import hmac
import re
import time
import uuid
from urllib.parse import quote, urlencode
import requests
from .domain import validate_store_url


class APIError(Exception):
    pass


def oauth_params(method, url, params, key, secret, timestamp=None, nonce=None):
    values = dict(params or {})
    values.update(oauth_consumer_key=key, oauth_signature_method='HMAC-SHA256',
                  oauth_timestamp=str(timestamp or int(time.time())), oauth_nonce=nonce or uuid.uuid4().hex)
    enc = lambda x: quote(str(x), safe='~')
    normalized = '&'.join('%s=%s' % (enc(k), enc(values[k])) for k in sorted(values))
    base = '&'.join([method.upper(), enc(url), enc(normalized)])
    values['oauth_signature'] = base64.b64encode(hmac.new((secret+'&').encode('utf-8'),
                                                        base.encode('utf-8'), hashlib.sha256).digest()).decode('ascii')
    return values


class Client:
    def __init__(self, url, key, secret, gateway_user='', gateway_password='', session=None,allowed_url='https://testshop.worldshading.com'):
        self.url = validate_store_url(url,allowed_url)
        if not key or not secret:
            raise ValueError('Woo API credentials are missing')
        self.key, self.secret = key, secret
        self.auth = (gateway_user, gateway_password) if gateway_user else None
        self.session = session or requests.Session()

    def request(self, method, endpoint, params=None, data=None):
        if not re.match(r'^[a-z][a-z0-9_-]*(/[a-z0-9_-]+)*$', endpoint):
            raise ValueError('Invalid Woo REST endpoint')
        base = self.url + '/wp-json/wc/v3/' + endpoint
        signed = oauth_params(method, base, params, self.key, self.secret)
        try:
            response = self.session.request(method, base+'?'+urlencode(signed), json=data, auth=self.auth,
                                            timeout=(10, 40), allow_redirects=False,
                                            headers={'Accept': 'application/json', 'User-Agent': 'WorldShading-ERPNext12/0.1'})
        except requests.RequestException:
            raise APIError('Woo API transport failed; check network, TLS and gateway availability') from None
        if response.status_code < 200 or response.status_code >= 300:
            guidance = {
                401: 'Check the API credentials and private-store login.',
                403: 'Check API key permissions and the store access rules.',
                404: 'Check the store URL and WooCommerce REST API availability.',
                429: 'The store is limiting requests; retry later.',
            }.get(response.status_code, 'Check store availability and retry.')
            raise APIError('Woo API HTTP %s at %s. %s' % (response.status_code, endpoint, guidance))
        try:
            return response.json()
        except ValueError:
            raise APIError('Woo API returned a non-JSON response') from None

    def get(self, endpoint, params=None):
        return self.request('GET', endpoint, params=params)

    def put(self, endpoint, data):
        return self.request('PUT', endpoint, data=data)

    def post(self, endpoint, data):
        return self.request('POST', endpoint, data=data)


def from_settings(settings):
    from .environment import validate_store
    allowed=validate_store(settings.store_url)
    return Client(settings.store_url, settings.get_password('consumer_key'), settings.get_password('consumer_secret'),
                  settings.gateway_user or '', settings.get_password('gateway_password', raise_exception=False) or '',allowed_url=allowed)


def check_price_configuration(client, currency):
    checks=[('settings/general/woocommerce_currency',currency,'Woo store currency differs from the ERP price currency'),
            ('settings/tax/woocommerce_prices_include_tax','no','Woo prices must be entered excluding tax before syncing ERP net prices'),
            ('settings/general/woocommerce_price_num_decimals','3','This BHD connector requires three decimal places in WooCommerce')]
    for endpoint,expected,message in checks:
        result=client.get(endpoint)
        if not isinstance(result,dict) or str(result.get('value'))!=str(expected):
            raise APIError(message)


def check_connection(client, expected_currency):
    """Verify saved credentials with GETs only; never claim to have tested writes."""
    setting = client.get('settings/general/woocommerce_currency')
    currency = setting.get('value') if isinstance(setting, dict) else None
    if not currency:
        raise APIError('Woo API did not return the store currency')
    if currency != expected_currency:
        raise APIError('Woo store currency does not match the connector currency')
    for endpoint in ('products', 'orders'):
        if not isinstance(client.get(endpoint, {'per_page': 1}), list):
            raise APIError('Woo API did not return readable ' + endpoint)
    return dict(connected=True, store_url=client.url, currency=currency,
                products_readable=True, orders_readable=True, write_access_verified=False,
                message='Connected. Products and orders can be read. No records were changed; write access is verified during product sync.')


def stable_order_window(client, params):
    """Rescan a fixed modified-time window; never advance past an unstable traversal."""
    collected={};previous=None
    for attempt in range(3):
        signature=[]
        for page in range(1,101):
            query=dict(params,per_page=50,page=page,orderby='modified',order='asc')
            batch=client.get('orders',query)
            if not isinstance(batch,list): raise APIError('Woo order page is not a list')
            for row in batch:
                signature.append((row['id'],row.get('date_modified_gmt')))
                collected[row['id']]=row
            if len(batch)<50:break
        else:
            raise APIError('Order pagination limit reached; cursor was not advanced')
        if signature==previous:
            return list(collected.values())
        previous=signature
    raise APIError('Woo order window changed during pagination; cursor was not advanced')
