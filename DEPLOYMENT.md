# Deploying to Render

This app deploys to [Render](https://render.com) as a Blueprint (`render.yaml`
at the repo root). The Blueprint provisions everything in one shot:

- `classroom-web` — the Django app, served by gunicorn.
- `classroom-worker` — a Celery worker for report generation jobs.
- `classroom-db` — managed PostgreSQL.
- `classroom-redis` — managed Redis, used as the Celery broker/result backend.

## First deploy

1. Push `render.yaml` to the branch you want deployed (usually `main`).
2. In the Render dashboard: **New > Blueprint**, point it at this GitHub repo.
   Render reads `render.yaml` and creates all four resources.
3. Render will prompt for the env vars marked `sync: false` in the
   `classroom-secrets` group before the first deploy:
   - `GITHUB_TOKEN_ENCRYPTION_KEY` — generate with:
     ```
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```
   - `CLIENT_ID` / `CLIENT_SECRET` — from a GitHub OAuth App (see below).
   - `DJANGO_SECRET_KEY` is auto-generated (`generateValue: true`) — no action needed.
4. Deploy. `classroom-web`'s `preDeployCommand` runs `python manage.py migrate`
   automatically on every deploy, and its build command runs `collectstatic`.

## One-time host-dependent config (after the first deploy)

Render assigns `classroom-web` a `*.onrender.com` hostname only once the
service exists, so these three `classroom-web` env vars are declared as
placeholders (`sync: false`) in `render.yaml` and must be filled in once the
hostname is known — the same pattern `.devcontainer/post-create.sh` already
uses for GitHub Codespaces:

- `DJANGO_ALLOWED_HOSTS` = `classroom-web.onrender.com` (or your custom domain)
- `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://classroom-web.onrender.com`
- `GITHUB_OAUTH_REDIRECT_URI` = `https://classroom-web.onrender.com/auth/github/callback/`

Setting these in the Render dashboard triggers an automatic redeploy.

## GitHub OAuth App

GitHub OAuth Apps support multiple registered callback URLs, so the existing
dev/Codespaces OAuth App can be reused — add the Render URL as an
**additional** callback URL rather than replacing the dev one:

- **Authorization callback URL**: add
  `https://classroom-web.onrender.com/auth/github/callback/` alongside the
  existing local/Codespaces callback(s).

Use its existing Client ID / Secret as `CLIENT_ID` / `CLIENT_SECRET` above.
Note that this means the same Client Secret is valid for both dev and
production OAuth flows — fine for a small internal tool, but if you want the
environments isolated later, register a second OAuth App and point
production at that one instead.

## Plans and cost

`render.yaml` defaults every resource to the `starter` plan (no cold starts,
persistent Postgres). Render also offers free tiers for testing — check the
current limitations (spin-down behavior, storage caps, and any time limits on
free databases) on Render's pricing page before relying on them for anything
beyond a demo.

## Verifying a deploy

- `GET /health/` should return `{"status": "ok"}`.
- `python manage.py check --deploy` should report no warnings — this is worth
  running locally against a real `DATABASE_URL` before pushing.
- Log in through GitHub OAuth end-to-end and confirm a report job (Celery
  task) completes — this exercises web, worker, Postgres, and Redis together.

## Explicitly out of scope for this setup

- **GitHub App vs. OAuth token model** — still an open decision noted in
  `plan.md`; this deployment keeps the current OAuth token flow.
- **Custom domain / CDN** — not configured; static files are served directly
  by WhiteNoise from the web dyno, which is sufficient at this app's scale.
- **Autoscaling** — each service runs as a single instance.
