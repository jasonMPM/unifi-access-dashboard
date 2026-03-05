# UniFi Access Badge-In Dashboard

A Dockerised Flask + SQLite attendance dashboard that receives real-time door unlock
webhooks from the **UniFi Access Developer API**, resolves badge holders to real names,
and displays a live attendance table with first/latest badge times and ON TIME / LATE status.

---

## Requirements

- Unraid server (or any Linux host with Docker + Docker Compose)
- UniFi OS console running **UniFi Access 1.9.1 or later**
- UniFi Access on the same LAN as your Unraid server
- Port **12445** open from your Unraid host to the UniFi controller IP
- A UniFi Access **Developer API token** (NOT a UniFi OS / Network API token)

---

## Step 1 — Open firewall port 12445

The UniFi Access Open API runs exclusively on **port 12445** (HTTPS, self-signed cert).
Your Unraid server and any machine running the dashboard must be able to reach it.

In UniFi Network → Settings → Firewall & Security → Firewall Rules, add a **LAN IN** rule:

| Field | Value |
|---|---|
| Action | Accept |
| Protocol | TCP |
| Destination Port | 12445 |
| Source | your LAN subnet (e.g. `10.0.0.0/8`) |

Verify from your Unraid SSH terminal or PowerShell:

```bash
# Linux / Unraid:
nc -zv 10.0.0.1 12445

# Windows PowerShell:
Test-NetConnection -ComputerName 10.0.0.1 -Port 12445
# TcpTestSucceeded : True  ← required
```

---

## Step 2 — Generate a UniFi Access Developer API token

> ⚠️ This token is different from the UniFi OS / Network API token.
> Creating it in the wrong place will result in 401 Unauthorized errors.

1. Open your UniFi OS console at `https://<controller-ip>` in a browser.
2. Navigate into the **Access** app (blue door icon).
3. Go to **Settings → General → Advanced → API Token**.
4. Click **Create New**, enter a name and validity period, enable **all permission scopes**.
5. Click **Create** and **immediately copy the token** — it is shown only once.

---

## Step 3 — Clone the repo on Unraid

SSH into your Unraid server and run:

```bash
cd /mnt/user/appdata
git clone https://github.com/<your-user>/<your-repo>.git unifi-access-dashboard
cd unifi-access-dashboard
```

---

## Step 4 — Create your .env file

```bash
cp .env.example .env
nano .env
```

Fill in all values:

```dotenv
UNIFI_HOST=10.0.0.1              # IP of your UniFi OS controller
UNIFI_PORT=12445                 # UniFi Access Open API port — do not change
UNIFI_API_TOKEN=YOUR_TOKEN_HERE  # Developer API token from Step 2
WEBHOOK_SECRET=                  # Leave blank until Step 6 gives you the secret
TZ=America/Chicago               # Your local timezone
DB_PATH=/data/dashboard.db       # Path inside the container — do not change
```

> **Never commit `.env` to git.** It is listed in `.gitignore`.

---

## Step 5 — Build and start the container

```bash
cd /mnt/user/appdata/unifi-access-dashboard
/usr/bin/docker compose up -d --build
```

The container will:
- Build the image from the local `Dockerfile`
- Start Flask on port **8000**
- Create `/data/dashboard.db` inside the container (mapped to `./data/` on the host)
- Immediately sync all users from your UniFi Access controller
- Schedule a user cache refresh every 6 hours

Verify it is running:

```bash
/usr/bin/docker ps
# Should show: unifi-access-dashboard   Up X seconds

/usr/bin/docker logs -f unifi-access-dashboard
# Should show: INFO:app:Synced X users from UniFi Access
```

---

## Step 6 — Register the webhook with UniFi Access

This registers your dashboard URL with UniFi Access so it receives door unlock events.
Run this **once** from inside the container console.

### Open the container console

In Unraid UI → **Docker tab** → click `unifi-access-dashboard` → **Console**

Then paste this Python script (replace values with yours):

```bash
python3 -c "
import requests, urllib3
urllib3.disable_warnings()

HOST     = '10.0.0.1'
TOKEN    = 'YOUR_ACCESS_DEVELOPER_TOKEN_HERE'
DASH_URL = 'http://YOUR_UNRAID_IP:8000/api/unifi-access'

r = requests.post(
    f'https://{HOST}:12445/api/v1/developer/webhooks/endpoints',
    headers={
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    },
    json={
        'name': 'Dashboard Unlock Events',
        'endpoint': DASH_URL,
        'events': ['access.door.unlock']
    },
    verify=False,
    timeout=10
)
print('Status:', r.status_code)
print('Response:', r.text)
"
```

A successful response looks like:

```json
{
  "code": "SUCCESS",
  "data": {
    "endpoint": "http://10.2.0.11:8000/api/unifi-access",
    "events": ["access.door.unlock"],
    "id": "afdb4271-...",
    "name": "Dashboard Unlock Events",
    "secret": "6e1d30c6ea8fa423"
  }
}
```

Copy the **`secret`** value from the response.

### Add the secret to your .env

On Unraid SSH:

```bash
nano /mnt/user/appdata/unifi-access-dashboard/.env
# Set: WEBHOOK_SECRET=6e1d30c6ea8fa423  (use your actual secret)
```

Then restart the container to pick up the new value:

```bash
/usr/bin/docker compose up -d --build
```

---

## Step 7 — Open the dashboard

Navigate to:

```
http://<UNRAID-IP>:8000/
```

### Dashboard controls

| Control | Description |
|---|---|
| **Date picker** | Choose which day to view |
| **Badged in by** | Set your on-time cutoff (e.g. `09:00 AM`) |
| **Refresh** | Reload the table for the selected date/cutoff |
| **Sync Users** | Immediately pull latest users from UniFi Access |
| **Reset Day** | Delete all badge records for the selected date (testing only) |

### Dashboard columns

| Column | Description |
|---|---|
| **#** | Row number |
| **Name** | Resolved display name from UniFi Access |
| **First Badge In** | Earliest door entry for the day — never changes once set |
| **Latest Badge In** | Most recent entry — shows *"— same"* if only one badge event |
| **Actor ID** | First 8 characters of the UniFi user UUID |
| **Status** | ON TIME (green) or LATE (red) based on first badge vs cutoff |

---

## Updating from GitHub

```bash
cd /mnt/user/appdata/unifi-access-dashboard
git pull
/usr/bin/docker compose up -d --build
```

The SQLite database in `./data/` persists across rebuilds automatically.

---

## API reference

| Method | Path | Params | Description |
|---|---|---|---|
| `POST` | `/api/unifi-access` | — | Receives UniFi Access webhook |
| `GET` | `/api/first-badge-status` | `date`, `cutoff` | Returns first + latest badge per user |
| `GET` | `/api/sync-users` | — | Triggers immediate user cache sync |
| `DELETE` | `/api/reset-day` | `date` | Deletes all records for given date |
| `GET` | `/api/debug-user-cache` | `actor_id` | Queries Access API for a specific user ID |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Webhook signature mismatch` | Wrong or missing `WEBHOOK_SECRET` in `.env` | Copy `secret` from Step 6 response into `.env`, rebuild |
| `401 Unauthorized` on webhook | Token invalid or wrong scope | Regenerate token in Access → Settings → General → API Token |
| `Port 12445 connection refused` | Firewall blocking port | Add LAN IN firewall rule in UniFi Network (Step 1) |
| Names show as `(Unknown)` | Users not cached yet | Click **Sync Users**; check logs for `Synced X users` |
| `before_first_request` error | Running Flask 3.0+ with old code | Use the latest `app.py` which uses `with app.app_context()` |
| `-SkipCertificateCheck` error in PowerShell | PowerShell 5.1 (not Core) | Add `[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }` before the request |
| Webhook POST returns 400 / no actor | Old `app.py` extracting wrong field | Use latest `app.py` which reads `data.actor.id` |
| Dashboard shows stale names after user rename | Cache not refreshed | Click **Sync Users** or wait for 6-hour auto-sync |
| Container starts but no users synced | `UNIFI_API_TOKEN` missing or wrong in `.env` | Check `.env` and rebuild |

---

## Security notes

- `.env` is excluded from git via `.gitignore` — never commit it.
- The `WEBHOOK_SECRET` ensures only genuine UniFi Access events are accepted (HMAC-SHA256).
- The API token is never exposed to the browser.
- The `/api/reset-day` and `/api/debug-user-cache` endpoints have no authentication — keep the container on your internal network only.
- For external access, place Nginx or Traefik with HTTPS in front of port `8000`.
