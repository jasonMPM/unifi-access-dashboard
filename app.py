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

UNIFI_BASE = f"https://{UNIFI_HOST}:{UNIFI_PORT}/api/v1/developer"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS badge_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id  TEXT NOT NULL,
                ts        TEXT NOT NULL,
                date      TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_cache (
                actor_id   TEXT PRIMARY KEY,
                full_name  TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.commit()


def sync_unifi_users():
    try:
        r = requests.get(
            f"{UNIFI_BASE}/users",
            headers={"Authorization": f"Bearer {UNIFI_TOKEN}"},
            verify=False,
            timeout=10,
        )
        if r.status_code != 200:
            log.warning("User sync failed: %s %s", r.status_code, r.text[:200])
            return
        users = r.json().get("data", [])
        with get_db() as db:
            for u in users:
                # Use the same ID field we see in webhooks
                actor_id = u.get("id")
                if not actor_id:
                    continue  # skip malformed entries

                full_name = (u.get("full_name") or "").strip()
                if not full_name:
                    full_name = f"{u.get('first_name','')} {u.get('last_name','')}".strip()

                db.execute(
                    """
                    INSERT INTO user_cache (actor_id, full_name, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(actor_id) DO UPDATE SET
                        full_name  = excluded.full_name,
                        updated_at = excluded.updated_at
                    """,
                    (
                        actor_id,
                        full_name or f"User {actor_id[:8]}",
                        datetime.utcnow().isoformat(),
                    ),
                )
            db.commit()
        log.info("Synced %d users from UniFi Access", len(users))
    except Exception as e:
        log.error("sync_unifi_users error: %s", e)


def verify_signature(payload_bytes, sig_header):
    """
    UniFi Access signature format:

      Header name : Signature
      Header value: t=<unix_timestamp>,v1=<hex_hmac_sha256>
      Signed data : f"{timestamp}.{raw_body}"
    """
    if not WEBHOOK_SECRET:
        return True
    if not sig_header:
        log.warning("No Signature header present")
        return False
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        timestamp = parts.get("t", "")
        received = parts.get("v1", "")
        if not timestamp or not received:
            log.warning("Signature header missing t or v1: %s", sig_header)
            return False
        signed_payload = f"{timestamp}.".encode() + payload_bytes
        expected = hmac.new(
            WEBHOOK_SECRET.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, received)
    except Exception as e:
        log.warning("Signature parse error: %s", e)
        return False


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/unifi-access", methods=["POST"])
def receive_webhook():
    raw = request.get_data()

    sig = request.headers.get("Signature", "")
    if not verify_signature(raw, sig):
        log.warning("Webhook signature mismatch")
        return jsonify({"error": "invalid signature"}), 401

    try:
        payload = json.loads(raw)
    except Exception:
        return jsonify({"error": "bad json"}), 400

    log.info("Webhook received: %s", json.dumps(payload)[:300])

    event = payload.get("event") or payload.get("event_object_id", "") or ""

    # Data block per UniFi Access docs: payload["data"]["actor"], ["event"], etc.
    data = payload.get("data") or {}
    actor_obj = data.get("actor") or {}

    # Use the same field as in your debug output
    actor = actor_obj.get("id")

    if "access.door.unlock" not in str(event):
        return jsonify({"status": "ignored"}), 200

    if not actor:
        log.warning("Webhook has no actor id: %s", json.dumps(payload)[:300])
        return jsonify({"error": "no actor"}), 400

    # Prefer data.event.published (ms since epoch) if present
    event_meta = data.get("event") or {}
    ts_ms = event_meta.get("published")
    if ts_ms:
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=pytz.utc)
    else:
        ts_raw = (
            payload.get("timestamp")
            or payload.get("created_at")
            or datetime.utcnow().isoformat()
        )
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))

    tz = pytz.timezone(TZ)
    ts_local = ts.astimezone(tz)
    date = ts_local.strftime("%Y-%m-%d")
    ts_str = ts_local.strftime("%H:%M:%S")

    with get_db() as db:
        db.execute(
            "INSERT INTO badge_events (actor_id, ts, date) VALUES (?, ?, ?)",
            (actor, ts_str, date),
        )
        db.commit()

    log.info("Badge-in recorded: actor=%s date=%s ts=%s", actor, date, ts_str)
    return jsonify({"status": "ok"}), 200


@app.route("/api/first-badge-status")
def first_badge_status():
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    cutoff = request.args.get("cutoff", "09:00")  # HH:MM

    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                b.actor_id,
                MIN(b.ts) AS first_ts,
                MAX(b.ts) AS latest_ts,
                COALESCE(
                    u.full_name,
                    'Unknown (' || SUBSTR(b.actor_id,1,8) || '...)'
                ) AS name
            FROM badge_events b
            LEFT JOIN user_cache u ON u.actor_id = b.actor_id
            WHERE b.date = ?
            GROUP BY b.actor_id
            ORDER BY first_ts ASC
            """,
            (date,),
        ).fetchall()

    result = []
    for r in rows:
        first = r["first_ts"]
        latest = r["latest_ts"]
        status = "ON TIME" if first <= cutoff + ":59" else "LATE"
        result.append(
            {
                "actor_id": r["actor_id"],
                "name": r["name"],
                "first_ts": first,
                "latest_ts": latest if latest != first else None,
                "status": status,
            }
        )

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


@app.route("/api/debug-user-cache")
def debug_user_cache():
    actor_id = request.args.get("actor_id", "").strip()
    if not actor_id:
        return jsonify({"error": "missing actor_id"}), 400

    try:
        r = requests.get(
            f"{UNIFI_BASE}/users/search",
            headers={"Authorization": f"Bearer {UNIFI_TOKEN}"},
            params={"userid": actor_id},
            verify=False,
            timeout=10,
        )
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return jsonify(
            {
                "status_code": r.status_code,
                "actor_id_param": actor_id,
                "response": data,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


with app.app_context():
    init_db()
    sync_unifi_users()

scheduler = BackgroundScheduler()
scheduler.add_job(sync_unifi_users, "interval", hours=6)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
