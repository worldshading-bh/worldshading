"""Site-time picker boundary. Woo cutoff and polling cursor stay UTC internally."""
from datetime import datetime
import pytz


def _datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S.%f' if '.' in str(value) else '%Y-%m-%d %H:%M:%S')


def _zone(time_zone):
    if time_zone is None:
        from frappe.utils import get_time_zone
        time_zone = get_time_zone()
    return pytz.timezone(time_zone)


def site_to_utc(value, time_zone=None):
    zone = _zone(time_zone)
    try:
        local = zone.localize(_datetime(value), is_dst=None)
    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
        raise ValueError('Import start time is ambiguous or invalid in the site timezone; choose another time')
    return local.astimezone(pytz.UTC).replace(tzinfo=None)


def utc_to_site(value, time_zone=None):
    return pytz.UTC.localize(_datetime(value)).astimezone(_zone(time_zone)).replace(tzinfo=None)


def update_order_cutoff(doc):
    """Only the visible site-time value is editable; keep the UTC boundary derived."""
    local = doc.get('order_since_local')
    if not local:
        if not doc.get('order_since'):
            raise ValueError('Choose the order import start time')
        local = utc_to_site(doc.order_since)
        doc.order_since_local = local
    if doc.get('order_since') and _datetime(local) == utc_to_site(doc.order_since):
        doc.order_since = _datetime(doc.order_since)
        return  # Preserve the exact instant across a repeated DST hour or a repeat save.
    doc.order_since = site_to_utc(local)
