# UniFi Access Badge-In Dashboard (V3)

A Dockerised Flask + SQLite web app that receives UniFi Access `access.door.unlock` webhooks,
resolves UUIDs to real user names via the UniFi Access API, and displays a modern dark
attendance dashboard with on-time / late status, first + latest badge times, and a test reset button.

---

## Features

- Receives webhooks from the UniFi Access developer API or legacy Alarm Manager format
- Resolves badge holder UUIDs to real names via the UniFi Access REST API
- User name cache stored in SQLite, auto-refreshed every 6 hours
- **First Badge In** column — locked to the earliest entry of the day, never overwritten
- **Latest Badge In** column — updates with each subsequent badge-in
- ON TIME / LATE status based on a configurable cutoff time (green / red chips)
- **Sync Users** button — manually pulls the latest user list from your controller
- **Reset Day** button — confirmation modal wipes all records for the selected date (testing only)
- Fully Dockerised — single container, SQLite persisted to a host volume

---

## Project layout

```
.
├── app.py                  # Flask application + API endpoints
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image definition
├── docker-compose.yml      # Compose file for Unraid deployment
├── .env.example            # Environment variable template (copy to .env)
├── .gitignore
└── static/
    └── index.html          # Single-page dashboard UI
```

---

## Step 1 — Generate a UniFi Access API token

1. Open your **UniFi OS** web interface (e.g. `https://192.168.1.1`).
2. Navigate to **UniFi Access → Settings → Integrations** (or **Developer API**).
3. Click **Create API Key**, give it a name (e.g. `Dashboard`), and copy the token.

> Use a dedicated read-only admin account to generate the token where possible.

---

## Step 2 — Clone the repo on your Unraid server

SSH into Unraid and run:

```bash
cd /mnt/user/appdata
git clone https://github.com/<your-user>/<your-repo>.git unifi-access-dashboard
cd unifi-access-dashboard
```

---

## Step 3 — Create your .env file

```bash
cp .env.example .env
nano .env
```

Fill in your values:

```dotenv
UNIFI_HOST=192.168.1.1          # IP address of your UniFi OS controller
UNIFI_API_TOKEN=YOUR_TOKEN_HERE # Bearer token from Step 1
TZ=America/Chicago              # Your local timezone
DB_PATH=/data/dashboard.db      # Path inside the container — do not change
```

> **Never commit `.env` to git.** It is listed in `.gitignore`.

---

## Step 4 — Build and start the container

```bash
docker compose up -d --build
```

The container will:
- Build the image from the local `Dockerfile`
- Start Flask on port **8000**
- Create `/data/dashboard.db` inside the container (mapped to `./data/` on the host)
- Immediately sync users from your UniFi Access controller
- Schedule a user cache refresh every 6 hours

Verify it is running:

```bash
docker ps
# Should show: unifi-access-dashboard   Up X seconds
```

Check logs:

```bash
docker logs -f unifi-access-dashboard
```

---

## Step 5 — Register the webhook with UniFi Access (run once)

Run this from any machine on the same LAN as your controller.
Replace `192.168.1.1`, `YOUR_TOKEN_HERE`, and `YOUR_UNRAID_IP` with your real values:

```bash
curl -k -X POST "https://192.168.1.1:45/api1/webhooks/endpoints" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Dashboard Unlock Events",
    "endpoint": "http://YOUR_UNRAID_IP:8000/api/unifi-access",
    "events": ["access.door.unlock"],
    "headers": { "X-Source": "unifi-access" }
  }'
```

Verify it was registered:

```bash
curl -k -X GET "https://192.168.1.1:45/api1/webhooks/endpoints" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

You should see your webhook listed with a unique `id` field.

> **Note:** The UniFi Access API runs on **port 45** over HTTPS with a self-signed certificate.
> Always use `-k` with curl, and `verify=False` is already set in the Python code.

---

## Step 6 — Open the dashboard

In a browser navigate to:

```
http://<UNRAID-IP>:8000/
```

### Using the dashboard

| Control | Description |
|---|---|
| **Date picker** | Choose which day to view |
| **Badged in by** | Set your on-time cutoff (24-hr format, e.g. `09:00`) |
| **Refresh** | Reload the table for the selected date and cutoff |
| **Sync Users** | Immediately pull the latest user list from UniFi Access |
| **Reset Day** | Delete all badge-in records for the selected date (testing only — requires confirmation) |

### Status chips

| Chip | Meaning |
|---|---|
| 🟢 ON TIME | First badge-in was at or before the cutoff |
| 🔴 LATE | First badge-in was after the cutoff |

### Columns

| Column | Description |
|---|---|
| **#** | Row number |
| **Name** | Resolved display name from UniFi Access |
| **First Badge In** | Earliest door entry for the day — never changes |
| **Latest Badge In** | Most recent door entry — shows *"— same"* if only one badge event |
| **Actor ID** | First 8 characters of the UniFi user UUID |
| **Status** | ON TIME or LATE chip based on first badge vs cutoff |

---

## Unraid GUI deployment (alternative to docker-compose)

If you prefer the Unraid Docker tab UI after pushing an image to Docker Hub:

```bash
# On your workstation:
docker build -t <dockerhub-user>/unifi-access-dashboard:latest .
docker push <dockerhub-user>/unifi-access-dashboard:latest
```

Then in Unraid → **Docker → Add Container**:

| Field | Value |
|---|---|
| Name | `unifi-access-dashboard` |
| Repository | `<dockerhub-user>/unifi-access-dashboard:latest` |
| Network Type | Bridge |
| Port mapping | Host `8000` → Container `8000` (TCP) |
| Path mapping | Host `/mnt/user/appdata/unifi-access-dashboard/data` → Container `/data` |
| Variable: `UNIFI_HOST` | `192.168.1.x` |
| Variable: `UNIFI_API_TOKEN` | your token |
| Variable: `TZ` | e.g. `America/Chicago` |
| Variable: `DB_PATH` | `/data/dashboard.db` |

---

## Updating from GitHub

```bash
cd /mnt/user/appdata/unifi-access-dashboard
git pull
docker compose up -d --build
```

---

## API endpoints reference

| Method | Path | Query params | Description |
|---|---|---|---|
| `POST` | `/api/unifi-access` | — | Receives UniFi Access webhook |
| `GET` | `/api/first-badge-status` | `date`, `cutoff` | Returns first + latest badge per user |
| `GET` | `/api/sync-users` | — | Triggers immediate user cache sync |
| `DELETE` | `/api/reset-day` | `date` | Deletes all records for the given date |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Names show as `Unknown (UUID…)` | Users not cached yet | Click **Sync Users** or wait for the 6-hr job |
| Webhook POST not arriving | Firewall or Docker network | Ensure port `8000` is reachable from the UniFi controller IP |
| `curl` returns SSL error | Self-signed cert on controller | Add `-k` to curl; already handled in Python |
| 404 on `/api1/users` | API path differs for your firmware | Try `/api/v1/users`; check your Access app version |
| Flask exits immediately | `.env` missing or malformed | Ensure `.env` exists alongside `docker-compose.yml` |
| Duplicate events | Both Alarm Manager and API webhooks active | Remove one; both are harmless but will store duplicate rows |
| Container rebuilds but old DB persists | Volume mount working correctly | This is expected — `./data/` survives rebuilds |

---

## Security notes

- `.env` is excluded from git via `.gitignore` — never commit it.
- The API token is never exposed to the browser or frontend.
- For access outside your LAN, place Nginx or Traefik with HTTPS in front of port `8000`.
- The `/api/reset-day` endpoint has no authentication — keep the container on your internal network only.
