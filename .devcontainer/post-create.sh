#!/usr/bin/env bash
set -euo pipefail

# Named volumes are created root-owned; let vscode write to them.
sudo chown -R vscode:vscode /home/vscode/.claude-persist /home/vscode/.shell-history

# Save each command to history as it runs, so closing a terminal doesn't lose it.
if ! grep -q 'history -a' ~/.bashrc; then
  echo 'PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"' >> ~/.bashrc
fi

pip install --user --upgrade pip
pip install --user -r requirements-webapp.txt

# Create a local .env on first run with freshly generated secrets.
if [ ! -f .env ]; then
  cp .env.example .env
  secret_key=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
  fernet_key=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${secret_key}|" .env
  sed -i "s|^GITHUB_TOKEN_ENCRYPTION_KEY=.*|GITHUB_TOKEN_ENCRYPTION_KEY=${fernet_key}|" .env

  # In Codespaces the app is reached through a forwarded *.app.github.dev URL.
  if [ -n "${CODESPACE_NAME:-}" ]; then
    host="${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
    sed -i "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,${host}|" .env
    sed -i "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=https://${host}|" .env
    sed -i "s|^GITHUB_OAUTH_REDIRECT_URI=.*|GITHUB_OAUTH_REDIRECT_URI=https://${host}/auth/github/callback/|" .env
  fi
  if [ -n "${CLIENT_ID:-}" ] && [ -n "${CLIENT_SECRET:-}" ]; then
    # VS Code's debugger loads .env into launched processes, so placeholders
    # left here would override the Codespaces secrets.
    sed -i "s|^CLIENT_ID=.*|# CLIENT_ID comes from the Codespaces secret|" .env
    sed -i "s|^CLIENT_SECRET=.*|# CLIENT_SECRET comes from the Codespaces secret|" .env
  else
    echo "Created .env — fill in CLIENT_ID / CLIENT_SECRET (or add them as Codespaces secrets)."
  fi
fi

python manage.py migrate
