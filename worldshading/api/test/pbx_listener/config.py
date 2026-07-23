import os


BENCH_PATH = os.environ.get("PBX_BENCH_PATH", "/home/erpadmin/frappe-bench")
SITES_PATH = os.path.join(BENCH_PATH, "sites")

HOST = "109.63.116.44"
PORT = 7777
USERNAME = "erpnext_user"

# Set this before running:
#   export PBX_AMI_SECRET='your-ami-secret'
SECRET = os.environ.get("PBX_AMI_SECRET", "")

RECONNECT_DELAY = 5
SOCKET_TIMEOUT = 10
READ_TIMEOUT = 1
PING_INTERVAL = 20
READ_SIZE = 4096

EXTENSION_PREFIX = "PJSIP/"
INTERNAL_EXTENSION_LENGTH = 4

# Company-owned caller IDs / trunk numbers. Calls that present these as caller
# numbers are outbound/internal from World Shading and should not open Call
# Assistant popups.
COMPANY_NUMBERS = (
    "17644117",
    "17644170",
)

ERP_SITE = os.environ.get("PBX_ERP_SITE", "erp.worldshading.com")
REALTIME_ENABLED = os.environ.get("PBX_REALTIME_ENABLED", "1") == "1"
REALTIME_TEST_USER = os.environ.get(
    "PBX_REALTIME_TEST_USER",
    "hilal@worldshading.com"
)
REALTIME_EVENT_NAME = "pbx_incoming_call"

# Keep this enabled during the prototype so existing Desk sessions can see the
# popup even before the custom JS include is refreshed. Set to 0 later.
REALTIME_EVAL_JS_ENABLED = os.environ.get("PBX_REALTIME_EVAL_JS", "1") == "1"

# During the prototype all extension popups are sent to one test user. In a
# ring-all call this would show duplicate popups, so send only one popup per
# LinkedID until extension-to-user mapping is added.
REALTIME_DEDUP_PER_CALL = os.environ.get("PBX_REALTIME_DEDUP_PER_CALL", "1") == "1"
