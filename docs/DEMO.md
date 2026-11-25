# Running a live demo

This runs the whole of Lokdhara on one computer: the database, the API, the background worker that checks recordings, and the contributor app. You only need **Docker Desktop**. Python, Node.js and FFmpeg come inside the containers.

Use it only with test accounts and test recordings. Never record real speakers into the demo: it has no backups, and its consent forms are test forms.

## 1. Install Docker Desktop (once)

Download it from <https://www.docker.com/products/docker-desktop/>, install it, and start it. Wait until it says Docker is running.

## 2. Start Lokdhara

Open a terminal (Git Bash or PowerShell on Windows, Terminal on a Mac) in your `lokdhara` folder:

```bash
git checkout main
git pull origin main
BUILDX_BAKE_ENTITLEMENTS_FS=0 docker compose -f infra/demo/docker-compose.yml up --build -d
```

The first start downloads and builds everything, which takes several minutes (about 6 on a typical laptop). Later starts take a few seconds.

`BUILDX_BAKE_ENTITLEMENTS_FS=0` lets newer Docker versions read `backend/` and `frontend/`, which sit outside the folder of the demo file. Without it, the build stops with "additional privileges requested". It is only needed with `--build`.

## 3. Create the demo accounts (once)

```bash
docker compose -f infra/demo/docker-compose.yml exec api python -m app.cli seed-dev
```

This prints a username and password for each test account. Save them somewhere safe: they are printed only the first time. The useful ones for a demo are:

| Account | Shows |
|---------|-------|
| `dev-contributor` | Recording, consent, text, and My submissions |
| `dev-admin` | The Failed checks page |

A line saying `unknown PostgreSQL timezone` is harmless.

`seed-dev` also loads the prompt texts and pictures from `backend/content/prompts/` into the database (ADR-036). Run it again after an update that adds prompts: it only adds the new ones and keeps the accounts.

## 4. Open the app

Go to <http://localhost:8080> in Chrome or Edge on the same computer, sign in, and record with the laptop's microphone. After **Save and upload**, open **My submissions** and reload after a few seconds: the status moves from "Being checked" to "Waiting for review" once the worker has finished its checks.

The demo is reachable only from this computer. Phones cannot open it, because browsers allow the microphone only on `localhost` or over HTTPS.

## Stopping and starting again

```bash
docker compose -f infra/demo/docker-compose.yml down        # stop; keeps accounts and recordings
docker compose -f infra/demo/docker-compose.yml up -d       # start again
docker compose -f infra/demo/docker-compose.yml down -v     # stop and delete all demo data
```

After `down -v`, run step 3 again to get new accounts.

## If something goes wrong

- **Port already in use:** another program uses port 8080. Close it, or change `127.0.0.1:8080:80` in `infra/demo/docker-compose.yml` to another port such as `127.0.0.1:8090:80`, then open that port.
- **The page does not load:** run `docker compose -f infra/demo/docker-compose.yml ps`. Every service should say `Up`. To see what went wrong, run `docker compose -f infra/demo/docker-compose.yml logs api`.
- **A recording stays "Being checked":** look at `docker compose -f infra/demo/docker-compose.yml logs worker`.
