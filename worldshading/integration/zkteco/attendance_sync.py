import requests
import json
import os
from datetime import datetime
from time import sleep

# ==========================================================
# File Paths (Linux)
# ==========================================================
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_PATH, "config.json")
LAST_SYNC_FILE = os.path.join(BASE_PATH, "last_sync.txt")
LOG_FILE = "/home/erpadmin/frappe-bench/logs/zkteco_sync.log"

# ==========================================================
# Load Config
# ==========================================================
with open(CONFIG_FILE, "r") as f:
    cfg = json.load(f)

DEVICE_API = cfg["device_api"].rstrip("/")
DEVICE_USER = cfg["device_user"]
DEVICE_PASS = cfg["device_pass"]
ERP_URL = cfg["erp_url"].rstrip("/")
ERP_KEY = cfg["erp_api_key"]
ERP_SECRET = cfg["erp_api_secret"]
MAX_LOGS = cfg.get("max_logs", 100)
BATCH_SIZE = 20

DATE_BARRIER = datetime(2025, 10, 18, 0, 0, 0)

# ==========================================================
# Helper: Logging
# ==========================================================
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2 * 1024 * 1024:
        rotated = LOG_FILE.replace(".log", f"_{datetime.now():%Y%m%d%H%M}.log")
        os.rename(LOG_FILE, rotated)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg)

# ==========================================================
# Helper: Sync Time
# ==========================================================
def get_last_sync_time():
    if os.path.exists(LAST_SYNC_FILE):
        try:
            with open(LAST_SYNC_FILE, "r") as f:
                t = f.read().strip()
                if t:
                    return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return datetime(2000, 1, 1, 0, 0, 0)

def update_last_sync_time(ts):
    with open(LAST_SYNC_FILE, "w") as f:
        f.write(ts.strftime("%Y-%m-%d %H:%M:%S"))

# ==========================================================
# Login to BioTime API
# ==========================================================
def get_device_token():
    try:
        res = requests.post(
            f"{DEVICE_API}/api-token-auth/",
            json={"username": DEVICE_USER, "password": DEVICE_PASS},
            timeout=10,
        )
        res.raise_for_status()
        token = res.json().get("token")
        if not token:
            raise ValueError("No token returned")
        log("✅ Logged in to BioTime API")
        return token
    except Exception as e:
        log(f"❌ Device login failed: {e}")
        return None

# ==========================================================
# Optimized: Fetch logs incrementally (fastest method)
# ==========================================================
def fetch_device_logs(session, last_sync):
    """
    Optimized fetch using official BioTime API parameters.
    Fetches only records after last_sync via start_time filter.
    """
    start_time = last_sync.strftime("%Y-%m-%d %H:%M:%S")
    url = f"{DEVICE_API}/iclock/api/transactions/?start_time={start_time}&ordering=punch_time&page_size=100"
    all_logs, page = [], 1

    try:
        while url:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            data = r.json()
            page_data = data.get("data", [])
            if not page_data:
                break

            all_logs.extend(page_data)
            log(f"📦 Page {page}: {len(page_data)} logs (total {len(all_logs)})")

            url = data.get("next")
            if not url:
                break
            page += 1
            sleep(0.1)

    except Exception as e:
        log(f"❌ Error fetching logs: {e}")

    log(f"✅ Finished fetching {len(all_logs)} total logs after {page} page(s)")
    return all_logs

# ==========================================================
# ERPNext: Employee Lookup Cache
# ==========================================================
def get_employee_from_device_id(session, device_id, cache):
    if device_id in cache:
        return cache[device_id]
    try:
        params = {"filters": json.dumps({"attendance_device_id": device_id}), "fields": '["name"]'}
        res = session.get(f"{ERP_URL}/api/resource/Employee", params=params, timeout=10)
        res.raise_for_status()
        data = res.json().get("data")
        if data:
            emp_name = data[0]["name"]
            cache[device_id] = emp_name
            return emp_name
    except Exception as e:
        log(f"❌ Employee lookup failed for {device_id}: {e}")
    cache[device_id] = None
    return None

# ==========================================================
# ERPNext: Batch Insert (safe and simple)
# ==========================================================
def push_batch_to_erp(session, batch):
    batch = [b for b in batch if isinstance(b, dict) and b.get("employee") and b.get("time")]
    if not batch:
        log("⚠️ Skipping empty or invalid batch")
        return

    for doc in batch:
        try:
            res = session.post(f"{ERP_URL}/api/resource/Employee Checkin", json=doc, timeout=10)
            if res.status_code == 200:
                log(f"✅ Inserted: {doc['employee']} @ {doc['time']}")
            elif "Duplicate" in res.text or "already exists" in res.text:
                log(f"🔁 Duplicate skipped: {doc['employee']} @ {doc['time']}")
            else:
                snippet = res.text[:100].replace("\n", " ")
                log(f"⚠️ Insert failed ({res.status_code}): {snippet}")
        except Exception as e:
            log(f"❌ Insert error: {e}")

# ==========================================================
# Main Sync Logic
# ==========================================================
def run_sync():
    log("\n🚀 Starting ZKTeco → ERPNext sync")
    last_sync = get_last_sync_time()
    log(f"🕓 Last sync time: {last_sync}")

    token = get_device_token()
    if not token:
        log("⛔ Aborting (no token).")
        return

    bio_session = requests.Session()
    bio_session.headers.update({"Authorization": f"Token {token}", "Accept-Encoding": "gzip"})

    erp_session = requests.Session()
    erp_session.headers.update({
        "Authorization": f"token {ERP_KEY}:{ERP_SECRET}",
        "Content-Type": "application/json"
    })

    all_logs = fetch_device_logs(bio_session, last_sync)
    if not all_logs:
        log("⚠️ No new logs retrieved.")
        return

    # Filter and process only new valid logs
    new_logs = []
    for entry in all_logs:
        try:
            pt = datetime.strptime(entry["punch_time"], "%Y-%m-%d %H:%M:%S")
            if pt > last_sync and pt >= DATE_BARRIER:
                new_logs.append(entry)
        except Exception:
            continue

    new_logs = sorted(new_logs, key=lambda x: x["punch_time"])[:MAX_LOGS]
    log(f"📋 {len(new_logs)} new logs to process")

    latest_time = last_sync
    emp_cache, seen, batch = {}, set(), []

    for entry in new_logs:
        emp_code = str(entry.get("emp_code")).strip()
        punch_time = entry.get("punch_time")
        punch_state = (entry.get("punch_state_display") or "").lower()
        log_type = "IN" if "in" in punch_state else "OUT"

        if not emp_code or not punch_time:
            continue

        key = f"{emp_code}-{punch_time}"
        if key in seen:
            continue
        seen.add(key)

        emp_name = get_employee_from_device_id(erp_session, emp_code, emp_cache)
        if not emp_name:
            log(f"⚠️ Skipping unmapped device ID {emp_code}")
            continue

        record = {
            "doctype": "Employee Checkin",
            "employee": emp_name,
            "log_type": log_type,
            "time": punch_time,
            "punch_state": entry.get("punch_state_display", ""),
            "department": entry.get("department") or "",
            "device_name": entry.get("terminal_alias") or entry.get("device_name") or ""
        }

        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            push_batch_to_erp(erp_session, batch)
            batch.clear()

        pt = datetime.strptime(punch_time, "%Y-%m-%d %H:%M:%S")
        if pt > latest_time:
            latest_time = pt

    if batch:
        push_batch_to_erp(erp_session, batch)

    update_last_sync_time(latest_time)
    log(f"🗓️ Updated last sync → {latest_time}")
    log("✅ Sync completed.\n")

# ==========================================================
# ERPNext Scheduler Hook
# ==========================================================
def run():
    run_sync()

if __name__ == "__main__":
    run_sync()
