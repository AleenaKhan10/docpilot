# DocPilot — Deployment Runbook

End-to-end production deployment. Follow it top to bottom on first launch.

Stack:

| Piece | Host | Cost |
|---|---|---|
| Frontend (React + Vite) | Vercel | Free |
| Backend (FastAPI) | Contabo VPS, Docker | ~$7/mo VPS |
| Celery worker | Same VPS, Docker | (included) |
| Redis | Same VPS, Docker | (included) |
| Postgres | Supabase | Free tier |
| Storage (PDFs/frames) | Supabase Storage | Free tier (1 GB) |
| Domain | Cloudflare Registrar | ~$10/yr |
| Email | Resend | Free (3K/mo) |

You'll do this in roughly this order:

1. [Buy the domain](#1-buy-the-domain) (~10 min)
2. [Buy + boot the VPS](#2-buy-the-vps) (~15 min)
3. [Point DNS records](#3-point-dns) (instant; propagation up to 1 hr)
4. [Run the VPS bootstrap script](#4-bootstrap-the-vps) (~10 min)
5. [Configure env + bring backend up](#5-bring-backend-up) (~10 min)
6. [Get HTTPS via Let's Encrypt](#6-https-via-lets-encrypt) (~5 min)
7. [Deploy the frontend to Vercel](#7-frontend-on-vercel) (~10 min)
8. [Verify end-to-end](#8-verify) (~5 min)
9. [Auto-deploy on git push](#9-auto-deploy-on-git-push) (optional, ~15 min)

---

## 1. Buy the domain

**Recommended registrar: Cloudflare** — sells at wholesale price (~$10/yr for `.com`, no renewal price hike), best-in-class DNS.

1. Go to **https://dash.cloudflare.com/sign-up** → create account (free)
2. Click **Add a domain** → **Register a new domain**
3. Search for the domain you want — e.g. `docpilot.io`, `getdocpilot.com`, `usedocpilot.com`
4. Buy it (~$10/yr for `.com`, ~$30/yr for `.io`, ~$15/yr for `.app`)
5. Once purchased, Cloudflare auto-manages the DNS — you don't need to change name servers

> Don't have time to think about names? Buy something cheap like `usedocpilot.com` for $10. You can always rebrand later.

---

## 2. Buy the VPS

**Contabo** — German VPS provider, very cheap, good for our use case.

1. Go to **https://contabo.com/en/vps/** → pick **VPS S** (~$5-7/mo: 4 vCPU, 8 GB RAM, 200 GB SSD)
2. **Image**: Ubuntu 22.04 LTS
3. **Storage type**: NVMe (faster, sometimes only a few cents more)
4. **Location**: pick close to your users (US/EU/Asia)
5. Add a root password OR upload your SSH public key (recommended for security)
6. Pay → wait 5-15 minutes for the box to provision

You'll get an email with the public IP. Example: `38.123.45.67`.

Test SSH access:

```bash
ssh root@YOUR-VPS-IP
```

If that connects, you're good.

---

## 3. Point DNS

Go to Cloudflare Dashboard → your domain → **DNS** → **Records**. Add:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `api` | `YOUR-VPS-IP` | **DNS only** (grey cloud) |
| CNAME | `app` | `cname.vercel-dns.com` | DNS only |
| CNAME | `@` (root) | `cname.vercel-dns.com` | DNS only |
| CNAME | `www` | `cname.vercel-dns.com` | DNS only |

> **Important**: keep the proxy **DNS only** (grey cloud) for now. Cloudflare's proxy can confuse Let's Encrypt cert issuance. You can flip it back to proxied after SSL is working.

DNS propagation: usually <5 min, max 1 hour. Test:

```bash
dig api.usedocpilot.com   # should return your VPS IP
```

---

## 4. Bootstrap the VPS

SSH to the box and run the setup script. It installs Docker, nginx, certbot, the firewall, and pulls the repo.

```bash
ssh root@YOUR-VPS-IP
curl -fsSL https://raw.githubusercontent.com/AleenaKhan10/docpilot/architecture-update/deploy/setup-vps.sh | bash
```

If you'd rather read the script first (recommended for any cURL-pipe-to-bash):

```bash
ssh root@YOUR-VPS-IP
wget https://raw.githubusercontent.com/AleenaKhan10/docpilot/architecture-update/deploy/setup-vps.sh
less setup-vps.sh           # inspect
bash setup-vps.sh
```

The script will end by telling you what to do next. The remaining steps are:

---

## 5. Bring backend up

Switch to the `docpilot` deploy user:

```bash
su - docpilot
cd ~/docpilot
```

Customise the nginx config — point it at `api.usedocpilot.com`:

```bash
sudo sed -i 's/api\.yourdomain\.com/api.usedocpilot.com/g' /etc/nginx/sites-available/docpilot
sudo nginx -t && sudo systemctl reload nginx
```

Fill in env vars:

```bash
cp .env.production.example .env
nano .env
```

Required values (copy from your dev `.env` if you don't have a fresh prod project):

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`
- `DATABASE_URL` — Supabase **session pooler** URL, password URL-encoded
- `GEMINI_API_KEY`
- `APP_BASE_URL=https://app.usedocpilot.com`
- `RESEND_API_KEY` (optional until you have a verified domain)

Bring the stack up:

```bash
docker compose pull
docker compose build
docker compose up -d
```

First build takes 5-10 min (downloads Python + ffmpeg + Whisper model on first worker start).

Apply DB migrations:

```bash
docker compose exec api alembic upgrade head
```

Verify locally on the box:

```bash
curl http://127.0.0.1:8000/
# should print {"service":"docpilot-api","status":"ok"}
```

---

## 6. HTTPS via Let's Encrypt

```bash
sudo certbot --nginx -d api.usedocpilot.com
```

Certbot will:
- Prove you own the domain (talks to Let's Encrypt + the nginx config we just installed)
- Get the cert + key
- Auto-edit nginx to use them
- Set up auto-renewal (twice daily check, renews when within 30 days)

Test:

```bash
curl https://api.usedocpilot.com/
# should print {"service":"docpilot-api","status":"ok"} over HTTPS
```

If you flip the Cloudflare proxy back to **Proxied** (orange cloud) after this, set Cloudflare → SSL/TLS → **Full (strict)** mode so it requires HTTPS to the origin.

---

## 7. Frontend on Vercel

1. Go to **https://vercel.com/signup** → sign up with GitHub
2. **Import Project** → pick `AleenaKhan10/Docpilot-frontend`
3. Vercel auto-detects Vite. Confirm:
   - Framework: **Vite**
   - Build command: `npm run build`
   - Output directory: `dist`
4. Click **Environment Variables**, add:
   - `VITE_SUPABASE_URL` = same as backend
   - `VITE_SUPABASE_ANON_KEY` = same as backend
   - `VITE_API_BASE_URL` = `https://api.usedocpilot.com`
   - `VITE_WS_BASE_URL` = `wss://api.usedocpilot.com` (note `wss` not `https`)
5. **Deploy**. Wait ~2 min for the first build
6. Once deployed, click **Settings** → **Domains** → add `app.usedocpilot.com` and `usedocpilot.com` (root). Vercel verifies DNS instantly (we added the CNAMEs in step 3)
7. Vercel issues SSL certs automatically

The frontend is now live at `https://app.usedocpilot.com` and `https://usedocpilot.com`.

---

## 8. Verify

1. Open `https://app.usedocpilot.com/login` → sign up flow works
2. Upload a tiny video → watch the live progress timeline
3. Open the generated doc → share link → open in incognito → no auth required
4. Check `docker compose logs -f --tail=200` on the VPS during processing — you should see Pass 1 / Pass 2 / PDF / Storage upload events

If something breaks:

```bash
docker compose ps                   # which services are up?
docker compose logs api             # backend errors
docker compose logs worker          # worker errors (Gemini, ffmpeg, etc.)
sudo tail -f /var/log/nginx/error.log
```

---

## 9. Auto-deploy on git push

This is optional but saves you SSHing in every time.

On the VPS, as the `docpilot` user, create an SSH key for GitHub:

```bash
ssh-keygen -t ed25519 -C "docpilot-vps-deploy"
cat ~/.ssh/id_ed25519.pub
```

Add that key to your GitHub account → **Settings** → **SSH and GPG keys** → **New SSH key**.

Then on the VPS:

```bash
git -C ~/docpilot remote set-url origin git@github.com:AleenaKhan10/docpilot.git
```

Now create a GitHub Actions workflow on the repo (you can do this in the GitHub web UI, file path `.github/workflows/deploy.yml`):

```yaml
name: Deploy backend

on:
  push:
    branches: [architecture-update, main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: SSH deploy
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: docpilot
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd ~/docpilot
            ./deploy/deploy.sh
```

Add secrets at **Repo Settings → Secrets and variables → Actions**:
- `VPS_HOST` = your VPS IP
- `VPS_SSH_KEY` = private SSH key paired with the public key you put on the VPS (different from the GitHub auth key — generate a new pair locally with `ssh-keygen -t ed25519 -f docpilot-deploy`, add the *public* key to `~/.ssh/authorized_keys` on the VPS, paste the *private* key here)

Now every push to `architecture-update` or `main` automatically redeploys.

---

## Day-to-day operations

**Push code change → live**

If auto-deploy is set up (step 9): `git push`. Done.

If not: `ssh docpilot@YOUR-VPS && cd ~/docpilot && ./deploy/deploy.sh`.

**Run a one-off command in the container**

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
docker compose exec api python -c "from main import app; print(len(app.routes))"
```

**See logs**

```bash
docker compose logs -f --tail=100 api
docker compose logs -f --tail=100 worker
```

**Restart just one service**

```bash
docker compose restart api
docker compose restart worker
```

**Update the host OS**

The VPS runs unattended-upgrades for security patches automatically. Periodically (monthly):

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot   # if a kernel update needs it
```

**Disk filling up?**

```bash
df -h
du -sh /var/lib/docker/   # docker is usually the culprit
docker system prune -af   # frees most of it
```

---

## Rollback if a deploy is bad

```bash
ssh docpilot@YOUR-VPS
cd ~/docpilot
git log --oneline -10               # find the last known good commit
git checkout <commit-hash>
docker compose build && docker compose up -d
docker compose exec api alembic downgrade -1   # if the bad deploy ran a migration
```

---

## Backup strategy (do this before launch)

We store data in two places: Supabase (Postgres + Storage) and the VPS Docker volumes (Redis state + Whisper cache + temp_data).

- **Postgres**: Supabase handles daily backups on the free tier (7 days retention). Pro tier extends this.
- **Storage**: Supabase replicates internally; no manual backup needed.
- **Redis**: Ephemeral (just queue state). If it dies, in-flight jobs are lost — that's acceptable.
- **`temp_data/`**: Janitor cleans it hourly. Doesn't need backup.

So: **no manual backups required for this stack**.

For extra safety, you can add a nightly `pg_dump` to S3 — but Supabase's built-in backups cover the common cases.
