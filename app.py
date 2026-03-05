import os, hmac, hashlib, json, logging
from flask import Flask, request, jsonify
from datetime import datetime
import pytz, sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
import requests, urllib3

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", static_url_path="")

UNIFI_HOST     = os.environ.get("UNIFI_HOST", "10.0.0.1")
UNIFI_PORT     = int(os.environ.get("UNIFI_PORT", "12445"))
UNIFI_TOKEN    = os.environ.get("UNIFI_API_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DB_PATH        = os.environ.get("DB_PATH", "/data/dashboard.db")
TZ             = os.environ.get("TZ", "America/Chicago")

UNIFI_BASE     = f"https://{UNIFI_HOST}:{UNIFI_PORT}/api/v1/developer"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS badge_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id  TEXT NOT NULL,
                ts        TEXT NOT NULL,
                date      TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_cache (
                actor_id   TEXT PRIMARY KEY,
                full_name  TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.commit()

def sync_unifi_users():
    try:
        r = requests.get(
            f"{UNIFI_BASE}/users",
            headers={"Authorization": f"Bearer {UNIFI_TOKEN}"},
            verify=False, timeout=10
        )
        if r.status_code != 200:
            log.warning("User sync failed: %s %s", r.status_code, r.text[:200])
            return
        users = r.json().get("data", [])
        with get_db() as db:
            for u in users:
                db.execute("""
                    INSERT INTO user_cache (actor_id, full_name, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(actor_id) DO UPDATE SET
                        full_name  = excluded.full_name,
                        updated_at = excluded.updated_at
                """, (u["id"], u.get("full_name", "").strip() or
                      f"{u.get('first_name','')} {u.get('last_name','')}".strip(),
                      datetime.utcnow().isoformat()))
            db.commit()
        log.info("Synced %d users from UniFi Access", len(users))
    except Exception as e:
        log.error("sync_unifi_users error: %s", e)

def verify_signature(payload_bytes, sig_header):
    """Return True if HMAC-SHA256 signature matches, or if no secret configured."""
    if not WEBHOOK_SECRET:
        return True
    expected = hmac.new(WEBHOOK_SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header or "")

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/api/unifi-access", methods=["POST"])
def receive_webhook():
    raw = request.get_data()

    # Optional signature verification
    sig = request.headers.get("X-Signature-SHA256", "")
    if not verify_signature(raw, sig):
        log.warning("Webhook signature mismatch")
        return jsonify({"error": "invalid signature"}), 401

    try:
        payload = json.loads(raw)
    except Exception:
        return jsonify({"error": "bad json"}), 400

    log.info("Webhook received: %s", json.dumps(payload)[:300])

    # Support both UniFi Access developer API and legacy Alarm Manager formats
    event   = payload.get("event") or payload.get("event_object_id", "")
    actor   = (payload.get("actor") or {}).get("id") or payload.get("actor_id", "")
    ts_raw  = payload.get("timestamp") or payload.get("created_at") or               datetime.utcnow().isoformat()

    if "door.unlock" not in str(event) and "access.door.unlock" not in str(event):
        return jsonify({"status": "ignored"}), 200

    if not actor:
        return jsonify({"error": "no actor"}), 400

    tz   = pytz.timezone(TZ)
    ts   = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    ts_l = ts.astimezone(tz)
    date = ts_l.strftime("%Y-%m-%d")
    ts_s = ts_l.strftime("%H:%M:%S")

    with get_db() as db:
        db.execute(
            "INSERT INTO badge_events (actor_id, ts, date) VALUES (?, ?, ?)",
            (actor, ts_s, date)
        )
        db.commit()

    log.info("Badge-in recorded: actor=%s date=%s ts=%s", actor, date, ts_s)
    return jsonify({"status": "ok"}), 200

@app.route("/api/first-badge-status")
def first_badge_status():
    date   = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    cutoff = request.args.get("cutoff", "09:00")

    with get_db() as db:
        rows = db.execute("""
            SELECT
                b.actor_id,
                MIN(b.ts) AS first_ts,
                MAX(b.ts) AS latest_ts,
                COALESCE(u.full_name, 'Unknown (' || SUBSTR(b.actor_id,1,8) || '...)') AS name
            FROM badge_events b
            LEFT JOIN user_cache u ON u.actor_id = b.actor_id
            WHERE b.date = ?
            GROUP BY b.actor_id
            ORDER BY first_ts ASC
        """, (date,)).fetchall()

    result = []
    for r in rows:
        first  = r["first_ts"]
        latest = r["latest_ts"]
        status = "ON TIME" if first <= cutoff + ":59" else "LATE"
        result.append({
            "actor_id":  r["actor_id"],
            "name":      r["name"],
            "first_ts":  first,
            "latest_ts": latest if latest != first else None,
            "status":    status
        })

    return jsonify(result)

@app.route("/api/sync-users")
def manual_sync():
    sync_unifi_users()
    return jsonify({"status": "synced"})

@app.route("/api/reset-day", methods=["DELETE"])
def reset_day():
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    with get_db() as db:
        cur = db.execute("DELETE FROM badge_events WHERE date = ?", (date,))
        db.commit()
    return jsonify({"status": "ok", "deleted": cur.rowcount, "date": date})

# Initialise DB and kick off background scheduler at import time
with app.app_context():
    init_db()
    sync_unifi_users()

scheduler = BackgroundScheduler()
scheduler.add_job(sync_unifi_users, "interval", hours=6)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
