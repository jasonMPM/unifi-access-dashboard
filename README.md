# UniFi Access Badge-In Dashboard (V3)

A Dockerised Flask + SQLite web app that receives UniFi Access `access.door.unlock` webhooks,
resolves UUIDs to real user names via the UniFi Access API, and displays a modern dark
attendance dashboard with on-time / late status, first + latest badge times, and a test reset button.

---

## Features

- Receives webhooks from the UniFi Access developer API or legacy Alarm Manager format.
- Resolves UUIDs to real names via the UniFi Access REST API (cached in SQLite, refreshed every 6 hrs).
- **First badge in** column — never overwritten by subsequent badges.
- **Latest badge in** column — shows the most recent entry that day.
- **Sync Users** button — manually refreshes the user name cache.
- **Reset Day** button — confirmation modal deletes all records for the selected date (testing only).
- Green ON TIME / Red LATE status chips based on a configurable cutoff time.
- Fully Dockerised — single container, persistent SQLite volume.

---

## Project layout

```
.
├── app.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── static/
    └── index.html
```

---

## Setup

### 1. Generate a UniFi Access API token

1. Open UniFi OS → UniFi Access → Settings → Integrations / Developer API.
2. Create a new API Key (Bearer Token) and copy it.

### 2. Create your .env file

```bash
cp .env.example .env
# edit .env and fill in UNIFI_HOST and UNIFI_API_TOKEN
```

### 3. Register the webhook with UniFi Access (run once)

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

Verify registration:

```bash
curl -k -X GET "https://192.168.1.1:45/api1/webhooks/endpoints" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### 4. Deploy on Unraid

```bash
cd /mnt/user/appdata
git clone https://github.com/<your-user>/<your-repo>.git unifi-access-dashboard
cd unifi-access-dashboard
cp .env.example .env && nano .env
docker compose up -d --build
```

Open: `http://<UNRAID-IP>:8000/`

### 5. Updating from GitHub

```bash
cd /mnt/user/appdata/unifi-access-dashboard
git pull
docker compose up -d --build
```

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/unifi-access` | Receives webhook from UniFi Access |
| GET | `/api/first-badge-status` | Returns first + latest badge per user for a date |
| GET | `/api/sync-users` | Triggers immediate user cache sync |
| DELETE | `/api/reset-day?date=YYYY-MM-DD` | Deletes all records for the given date |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Names show as `Unknown (UUID…)` | Users not cached yet | Click Sync Users |
| Webhook not arriving | Firewall / port | Ensure port 8000 reachable from controller |
| SSL error on curl | Self-signed cert | Use `-k` flag |
| 404 on `/api1/users` | Firmware path differs | Try `/api/v1/users` |
| Duplicate events | Both Alarm Manager and API webhooks active | Remove one or deduplicate by event ID |
