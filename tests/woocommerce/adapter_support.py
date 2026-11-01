"""No-site adapter harness. Never imports or initializes a real Frappe database."""
import contextlib
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

PACKAGE = 'worldshading.integration.woocommerce'
ROOT = Path(__file__).resolve().parents[2] / 'worldshading' / 'integration' / 'woocommerce'

# The feature is an overlay, not a complete installed app. Always resolve its
# modules from this checkout, even when Python has another Worldshading app
# installed (the remote Python 3.6 acceptance environment).
for package,path in [('worldshading',ROOT.parent.parent),('worldshading.integration',ROOT.parent),(PACKAGE,ROOT)]:
    module=types.ModuleType(package);module.__path__=[str(path)]
    sys.modules[package]=module
    if '.' in package:
        parent,child=package.rsplit('.',1);setattr(sys.modules[parent],child,module)


@contextlib.contextmanager
def adapter(module_name):
    frappe = types.ModuleType('frappe')
    frappe.db = Mock()
    frappe.db.count.return_value = 0
    frappe.db.get_single_value.return_value = 0
    frappe.get_doc = Mock()
    frappe.get_all = Mock(return_value=[])
    frappe.set_user = Mock()
    frappe.destroy = Mock()
    frappe.init = Mock()
    frappe.connect = Mock()
    frappe.flags = types.SimpleNamespace()
    frappe.local = types.SimpleNamespace(response={})
    frappe.PermissionError = PermissionError
    def throw(message, error=ValueError):
        raise error(message)
    frappe.throw = throw
    frappe.whitelist = lambda *args, **kwargs: lambda func: func
    utils = types.ModuleType('frappe.utils')
    utils.now_datetime = lambda: datetime(2026, 10, 29, 12)
    utils.today = lambda: '2026-10-29'
    def get_datetime(value):
        if isinstance(value,datetime):return value
        value=str(value).replace('T',' ').rstrip('Z')
        return datetime.strptime(value,'%Y-%m-%d %H:%M:%S.%f' if '.' in value else '%Y-%m-%d %H:%M:%S')
    utils.get_datetime = get_datetime
    utils.add_to_date = Mock()
    utils.add_days = Mock()
    common = types.ModuleType(PACKAGE + '.common')
    common.SETTINGS, common.MAP, common.ORDER, common.LOG = 'Settings', 'Map', 'Order', 'Log'
    common.settings = Mock()
    common.mappings = Mock(return_value=[])
    common.log = Mock()
    common.manager_only = Mock()
    common.start_operation = Mock()
    class LockBusy(ValueError):pass
    common.LockBusy = LockBusy
    @contextlib.contextmanager
    def lock(key):
        yield
    common.lock = lock
    orders = types.ModuleType(PACKAGE + '.orders')
    orders.retry_due = Mock(return_value=0)
    orders.store_payload = Mock()
    orders.import_order = Mock()
    custom_fields=types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
    custom_fields.create_custom_fields=Mock()
    full_name = PACKAGE + '.' + module_name
    with patch.dict(sys.modules, {'frappe': frappe, 'frappe.utils': utils,
                                 'frappe.custom.doctype.custom_field.custom_field':custom_fields,
                                 PACKAGE + '.common': common, PACKAGE + '.orders': orders}):
        # Python 3.6 mock.patch resolves parent attributes before sys.modules.
        # A prior fixture may have restored sys.modules but left those aliases.
        package=sys.modules[PACKAGE]
        for key,value in list(vars(package).items()):
            if isinstance(value,types.ModuleType) and key not in ('domain','client'):delattr(package,key)
        package.common=common;package.orders=orders
        # Frappe adapters imported as dependencies must use this fixture's DB,
        # rather than retaining the mocked database from an earlier test case.
        for name in list(sys.modules):
            if name.startswith(PACKAGE+'.') and name not in (PACKAGE+'.common',PACKAGE+'.orders',PACKAGE+'.domain',PACKAGE+'.client'):
                del sys.modules[name]
                parent,child=name.rsplit('.',1)
                if parent in sys.modules and hasattr(sys.modules[parent],child):delattr(sys.modules[parent],child)
        spec = importlib.util.spec_from_file_location(full_name, str(ROOT / (module_name + '.py')))
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name]=module
        setattr(sys.modules[PACKAGE],module_name,module)
        spec.loader.exec_module(module)
        yield module, frappe, common, orders
