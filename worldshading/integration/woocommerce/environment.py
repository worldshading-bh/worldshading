"""Exact site/store destination pair, configured by the site's administrator."""
import frappe
from .domain import https_origin,validate_store_url

DEMO_ERP='https://demo.worldshading.com'
DEMO_STORE='https://testshop.worldshading.com'


def configured_urls():
    erp=frappe.conf.get('ws_woocommerce_erp_url')
    store=frappe.conf.get('ws_woocommerce_store_url')
    if bool(erp)!=bool(store):
        raise ValueError('Configure both ws_woocommerce_erp_url and ws_woocommerce_store_url')
    return https_origin(erp or DEMO_ERP),https_origin(store or DEMO_STORE)


def require_site():
    erp,_=configured_urls()
    if https_origin(frappe.conf.get('host_name'))!=erp:
        raise ValueError('This ERP site does not match ws_woocommerce_erp_url')


def site_is_allowed():
    try:require_site();return True
    except ValueError:return False


def validate_store(url):
    require_site()
    return validate_store_url(url,configured_urls()[1])


def webhook_url():
    require_site()
    return configured_urls()[0]+'/api/method/worldshading.integration.woocommerce.api.webhook'
