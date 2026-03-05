# UniFi Access Badge-In Dashboard (V2)

A Dockerised Flask + SQLite web app that receives UniFi Access `access.door.unlock` webhooks,
resolves UUID actor IDs to real user names via the UniFi Access API,
and displays a modern dark dashboard with on-time / late status per person.

---

## Features

- Receives `access.door.unlock` webhooks from either the **UniFi Access developer API** or the legacy **Alarm Manager** format.
- Resolves blank `user_name` UUIDs to real names by querying the UniFi Access REST API on a schedule (every 6 hours) and caching results in SQLite.
- Manual **Sync Users** button in the UI triggers an immediate cache refresh.
- Dark theme with gold accents, green ON TIME / red LATE status chips.
- Date picker + configurable "badged in by" cutoff time.
- Fully Dockerised — single container, persisted SQLite volume.

---

## Project layout

```
.
├── app.py                 # Flask application
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example           # Copy to .env and fill in your values
├── .gitignore
└── static/
    └── index.html         # Dashboard UI
```

---

## Step 1 — Generate a UniFi Access API token

1. Open your **UniFi OS** web interface.
2. Navigate to **UniFi Access → Settings → Integrations** (or the **Developer API** section).
3. Create a new **API Key** (Bearer Token). Copy it — you will need it below.

> Use a dedicated read-only admin account to generate the token if possible.

---

## Step 2 — Create your .env file

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```dotenv
UNIFI_HOST=192.168.1.1          # IP of your UniFi OS controller
UNIFI_API_TOKEN=YOUR_TOKEN_HERE
TZ=America/Chicago
DB_PATH=/data/dashboard.db
```

> **Never commit `.env` to git.** It is listed in `.gitignore`.

---

## Step 3 — Register the webhook with UniFi Access

Run this once from any machine on the same LAN as your controller (replace placeholders):

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

You should see your webhook listed with a unique `id`.

> **Note:** The UniFi Access API runs on **port 45** over HTTPS with a self-signed cert.
> Always pass `-k` to curl, or `verify=False` in Python requests.

---

## Step 4 — Deploy on Unraid

### Clone from GitHub and build locally

SSH into your Unraid server:

```bash
cd /mnt/user/appdata
git clone https://github.com/<your-user>/<your-repo>.git unifi-access-dashboard
cd unifi-access-dashboard
cp .env.example .env
nano .env   # fill in UNIFI_HOST and UNIFI_API_TOKEN
docker compose up -d --build
```

The app is now running on **port 8000**.

### Unraid GUI (Docker tab — Add Container)

If you prefer using the GUI after pushing an image to Docker Hub:

```bash
# On your workstation:
docker build -t <your-dockerhub-user>/unifi-access-dashboard:latest .
docker push <your-dockerhub-user>/unifi-access-dashboard:latest
```

Then in Unraid → Docker → Add Container:

| Field | Value |
|---|---|
| Name | unifi-access-dashboard |
| Repository | `<your-dockerhub-user>/unifi-access-dashboard:latest` |
| Port | Host `8000` → Container `8000` |
| Path | Host `/mnt/user/appdata/unifi-access-dashboard/data` → Container `/data` |
| Env: UNIFI_HOST | `192.168.1.x` |
| Env: UNIFI_API_TOKEN | `your-token` |
| Env: TZ | `America/Chicago` |

---

## Step 5 — Open the dashboard

Browse to:

```
http://<UNRAID-IP>:8000/
```

- Choose a **date** and set the **"Badged in by"** cutoff time (e.g. `09:00`).
- Click **Refresh** to load the day's first badge-in per person.
- Green chip = on time. Red chip = late.
- Click **Sync Users** to immediately pull the latest user list from your UniFi Access controller.

---

## Keeping the user cache fresh

The app automatically re-syncs users from UniFi Access every **6 hours** in the background.
If you add or rename a badge holder, click **Sync Users** in the dashboard or restart the container.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Names show as `Unknown (UUID…)` | Users not yet cached | Click Sync Users or wait for the 6-hour job |
| Webhook not arriving | Firewall / Docker network | Ensure port 8000 is reachable from the UniFi controller |
| `curl` returns SSL error | Self-signed cert | Add `-k` to bypass; already handled in Python |
| 404 on `/api1/users` | Firmware difference | Try `/api/v1/users`; check your Access app version |
| Duplicate events | Both Alarm Manager and API webhook active | Remove one, or they will both store rows (harmless but duplicates) |
| Container exits | `.env` missing | Ensure `.env` exists and `docker compose up` picks it up |

---

## Updating from GitHub

```bash
cd /mnt/user/appdata/unifi-access-dashboard
git pull
docker compose up -d --build
```

---

## Security notes

- The `.env` file is excluded from git via `.gitignore`.
- The UniFi API token is never exposed to the frontend.
- Mount `/data` to persistent storage so badge history survives container restarts.
- For external access, place a reverse proxy (Nginx/Traefik) with HTTPS in front.
