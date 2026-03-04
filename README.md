# UniFi Access Badge-In Dashboard

A small Flask + SQLite web app that receives UniFi Access `access.door.unlock` webhooks and shows a dark, gold-accented dashboard of daily first badge-in times.

## Features

- Receives UniFi Access webhooks for `access.door.unlock` events and stores them in SQLite.
- Modern dark UI with black background, gold accents, and on-time (green) vs late (red) status.
- Date picker and configurable "badged in by" cutoff time.
- Dockerised for easy deployment on Unraid.

## Repository layout

- `app.py` – Flask application and API endpoints.
- `requirements.txt` – Python dependencies.
- `Dockerfile` – Container image definition.
- `docker-compose.yml` – Example compose file (works on Unraid).
- `static/index.html` – Single‑page dashboard UI.

## UniFi Access configuration

1. Ensure you have UniFi Access running (UA Ultra / UA Hub Door Mini / G3 Intercom etc.).
2. In the UniFi Access web UI, open the API / developer section and create a **Webhook**:[web:24][web:25]
   - Method: `POST`.
   - URL: `http://<UNRAID-IP>:8000/unifi-access-webhook` (or behind HTTPS via reverse proxy).
   - Events: at least `access.door.unlock`.
3. Save and trigger a test door unlock. You should see webhook hits in the container logs and rows in `events.db`.

## Building and running on Unraid

### 1. Create a public GitHub repository

1. On your workstation, create a new folder and put all files from this project in it.
2. Initialize a Git repo, commit, and push to GitHub (public or private with a token):

```bash
git init
git add .
git commit -m "Initial UniFi Access dashboard"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

### 2. Add a new Docker template on Unraid

You can either use the **Docker** tab (Add Container) or deploy via the Unraid terminal.

#### Option A – Using Unraid GUI

1. Go to **Docker → Add Container**.
2. Set **Name** to `unifi-access-dashboard`.
3. For **Repository**, point to your GitHub repo using the GitHub URL with the `Dockerfile` as build context if you build externally, or build the image locally first (Option B). Unraid’s GUI typically expects an image name on Docker Hub; easiest approach is:
   - Build and push your image from a machine with Docker:

```bash
docker build -t <your-user>/unifi-access-dashboard:latest .
docker push <your-user>/unifi-access-dashboard:latest
```

   - Then in Unraid, set **Repository** to `<your-user>/unifi-access-dashboard:latest`.
4. Add a **Port mapping**: host `8000` → container `8000`.
5. Add a **Path mapping** for persistent DB:
   - Host path: `/mnt/user/appdata/unifi-access-dashboard/`
   - Container path: `/data`
6. Add environment variable `TZ` to match your timezone (e.g., `America/Chicago`).
7. Apply to start the container.

#### Option B – Using `docker-compose` on Unraid

If you prefer to build directly on the Unraid box and pull source from GitHub:

1. SSH into Unraid.
2. Clone your GitHub repo:

```bash
cd /mnt/user/appdata
git clone https://github.com/<your-user>/<your-repo>.git unifi-access-dashboard
cd unifi-access-dashboard
```

3. (Optional) Adjust `docker-compose.yml` ports or paths.
4. Build and start:

```bash
docker compose up -d --build
```

5. The app will listen on port `8000` by default.

### 3. Verify the app

1. In a browser, open `http://<UNRAID-IP>:8000/`.
2. You should see the dark dashboard with date and cutoff selectors.
3. After some badge-in activity, click **Refresh** and verify that users show as **ON TIME** (green) or **LATE** (red) depending on the cutoff.

## Environment and volumes

- `DB_PATH` (optional) – path to the SQLite file inside the container (defaults to `/data/events.db` via Dockerfile).
- Mount `/data` to persistent storage on Unraid so badge history survives container restarts.

## Time zones and "on time" logic

- Webhook timestamps are stored in UTC with a `Z` suffix.
- The "badged in by" cutoff is interpreted in 24‑hour `HH:MM` format and compared against the stored time string for that day.
- If you need strict local‑time handling, you can extend `app.py` to convert UTC to your timezone before comparison.

