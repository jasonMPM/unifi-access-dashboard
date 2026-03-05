from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import datetime as dt
import requests
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)

DB_PATH         = os.environ.get("DB_PATH", "/data/dashboard.db")
UNIFI_HOST      = os.environ.get("UNIFI_HOST", "")
UNIFI_API_TOKEN = os.environ.get("UNIFI_API_TOKEN", "")


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.before_first_request
def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS unlocks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT NOT NULL,
            event         TEXT NOT NULL DEFAULT 'access.door.unlock',
            door_name     TEXT,
            device_name   TEXT,
            actor_id      TEXT,
            actor_name    TEXT,
            resolved_name TEXT,
            auth_type     TEXT,
            result        TEXT
        );

        CREATE TABLE IF NOT EXISTS access_users (
            id         TEXT PRIMARY KEY,
            name       TEXT,
            email      TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    for col in ("resolved_name", "device_name"):
        try:
            conn.execute(f"ALTER TABLE unlocks ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── UniFi user cache ──────────────────────────────────────────────────────────

def sync_unifi_users():
    if not UNIFI_HOST or not UNIFI_API_TOKEN:
        print("[UniFi Sync] UNIFI_HOST or UNIFI_API_TOKEN not set — skipping.")
        return
    url     = f"https://{UNIFI_HOST}:45/api1/users"
    headers = {"Authorization": f"Bearer {UNIFI_API_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        users = resp.json().get("data", [])
        conn  = get_db()
        for user in users:
            conn.execute(
                """INSERT INTO access_users (id, name, email, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name,
                       email=excluded.email,
                       updated_at=excluded.updated_at""",
                (user.get("id"), user.get("name"), user.get("email", "")),
            )
        conn.commit()
        conn.close()
        print(f"[UniFi Sync] Cached {len(users)} users.")
    except Exception as e:
        print(f"[UniFi Sync] Failed: {e}")


def resolve_user_name(user_id: str) -> str:
    if not user_id:
        return "Unknown"
    conn = get_db()
    row  = conn.execute(
        "SELECT name FROM access_users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["name"] if row else f"Unknown ({user_id[:8]}…)"


# ── Webhook receiver ──────────────────────────────────────────────────────────

@app.post("/api/unifi-access")
def unifi_access_webhook():
    payload = request.get_json(force=True, silent=True) or {}
    ts      = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    if payload.get("event") == "access.door.unlock":
        data        = payload.get("data", {})
        actor       = data.get("actor", {})
        location    = data.get("location", {})
        device      = data.get("device", {})
        obj         = data.get("object", {})
        actor_id    = actor.get("id", "")
        actor_name  = actor.get("name") or resolve_user_name(actor_id)
        door_name   = location.get("name")
        device_name = device.get("name")
        auth_type   = obj.get("authentication_type")
        result      = obj.get("result", "Access Granted")

    elif "events" in payload:
        event       = payload["events"][0]
        actor_id    = event.get("user", "")
        actor_name  = event.get("user_name") or resolve_user_name(actor_id)
        door_name   = event.get("location_name") or event.get("location", "Unknown Door")
        device_name = None
        auth_type   = event.get("unlock_method_text", "Unknown")
        result      = "Access Granted"

    else:
        return "", 204

    conn = get_db()
    conn.execute(
        """INSERT INTO unlocks
               (ts, event, door_name, device_name, actor_id,
                actor_name, resolved_name, auth_type, result)
           VALUES (?, 'access.door.unlock', ?, ?, ?, ?, ?, ?, ?)""",
        (ts, door_name, device_name, actor_id, actor_name,
         actor_name, auth_type, result),
    )
    conn.commit()
    conn.close()
    return "", 204


# ── Dashboard data API ────────────────────────────────────────────────────────

@app.get("/api/first-badge-status")
def first_badge_status():
    date   = request.args.get("date")   or dt.date.today().isoformat()
    cutoff = request.args.get("cutoff", "09:00")
    start  = f"{date}T00:00:00Z"
    end    = f"{date}T23:59:59Z"

    conn = get_db()
    # First badge per person
    first_rows = conn.execute(
        """SELECT COALESCE(resolved_name, actor_name, actor_id) AS display_name,
                  actor_id,
                  MIN(ts) AS first_ts
           FROM unlocks
           WHERE event  = 'access.door.unlock'
             AND result = 'Access Granted'
             AND ts BETWEEN ? AND ?
             AND (actor_id IS NOT NULL OR actor_name IS NOT NULL)
           GROUP BY actor_id
           ORDER BY first_ts""",
        (start, end),
    ).fetchall()

    # Latest badge per person (may equal first if they only badged once)
    latest_rows = conn.execute(
        """SELECT actor_id, MAX(ts) AS latest_ts
           FROM unlocks
           WHERE event  = 'access.door.unlock'
             AND result = 'Access Granted'
             AND ts BETWEEN ? AND ?
             AND actor_id IS NOT NULL
           GROUP BY actor_id""",
        (start, end),
    ).fetchall()
    conn.close()

    latest_map = {r["actor_id"]: r["latest_ts"] for r in latest_rows}

    result = []
    for r in first_rows:
        t_first = dt.datetime.fromisoformat(r["first_ts"].replace("Z", "+00:00"))
        first_time = t_first.strftime("%H:%M")

        latest_ts  = latest_map.get(r["actor_id"], r["first_ts"])
        t_latest   = dt.datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
        latest_time = t_latest.strftime("%H:%M")

        result.append({
            "actor_name":   r["display_name"],
            "actor_id":     r["actor_id"],
            "first_badge":  r["first_ts"],
            "badge_time":   first_time,
            "latest_badge": latest_ts,
            "latest_time":  latest_time,
            "on_time":      first_time <= cutoff,
        })

    return jsonify(result)


# ── Sync users ────────────────────────────────────────────────────────────────

@app.get("/api/sync-users")
def manual_sync():
    sync_unifi_users()
    return jsonify({"status": "ok"})


# ── Reset day (testing only) ──────────────────────────────────────────────────

@app.delete("/api/reset-day")
def reset_day():
    """Delete all unlock records for a given date (defaults to today).
    Intended for development/testing only.
    """
    date  = request.args.get("date") or dt.date.today().isoformat()
    start = f"{date}T00:00:00Z"
    end   = f"{date}T23:59:59Z"
    conn  = get_db()
    res   = conn.execute(
        "DELETE FROM unlocks WHERE ts BETWEEN ? AND ?", (start, end)
    )
    conn.commit()
    deleted = res.rowcount
    conn.close()
    return jsonify({"status": "ok", "deleted": deleted, "date": date})


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_from_directory("static", "index.html")

@app.get("/static/<path:path>")
def send_static(path):
    return send_from_directory("static", path)


# ── Startup ───────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(sync_unifi_users, "interval", hours=6)
scheduler.start()

if __name__ == "__main__":
    with app.app_context():
        init_db()
        sync_unifi_users()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
