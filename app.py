from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import datetime as dt
import os

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "events.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.before_first_request
def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          event TEXT NOT NULL,
          door_name TEXT,
          device_name TEXT,
          actor_id TEXT,
          actor_name TEXT,
          auth_type TEXT,
          result TEXT
        )
        """
    )
    conn.commit()
    conn.close()


@app.post("/unifi-access-webhook")
def unifi_access_webhook():
    payload = request.get_json(force=True, silent=True) or {}
    event = payload.get("event")
    data = payload.get("data", {})

    if event != "access.door.unlock":
        return "", 204

    actor = data.get("actor", {})
    location = data.get("location", {})
    device = data.get("device", {})
    obj = data.get("object", {})

    ts = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    conn = get_db()
    conn.execute(
        """
        INSERT INTO events (ts, event, door_name, device_name,
                            actor_id, actor_name, auth_type, result)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            event,
            location.get("name"),
            device.get("name"),
            actor.get("id"),
            actor.get("name"),
            obj.get("authentication_type"),
            obj.get("result"),
        ),
    )
    conn.commit()
    conn.close()

    return "", 204


@app.get("/api/first-badge-status")
def first_badge_status():
    date = request.args.get("date") or dt.date.today().isoformat()
    cutoff = request.args.get("cutoff", "09:00")  # HH:MM
    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"

    conn = get_db()
    rows = conn.execute(
        """
        SELECT actor_name, actor_id, MIN(ts) AS first_ts
        FROM events
        WHERE event = 'access.door.unlock'
          AND result = 'Access Granted'
          AND ts BETWEEN ? AND ?
          AND actor_id IS NOT NULL
        GROUP BY actor_id, actor_name
        ORDER BY first_ts
        """,
        (start, end),
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        first_ts = r["first_ts"]
        t = dt.datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        badge_time_str = t.strftime("%H:%M")
        on_time = badge_time_str <= cutoff
        result.append(
            {
                "actor_name": r["actor_name"],
                "actor_id": r["actor_id"],
                "first_badge": first_ts,
                "badge_time": badge_time_str,
                "on_time": on_time,
            }
        )

    return jsonify(result)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/static/<path:path>")
def send_static(path):
    return send_from_directory("static", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
