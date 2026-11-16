#!/usr/bin/env python3
"""Prepare an isolated, loopback-only production Compose deployment. Never switches the app."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-supabase"
UPSTREAM_COMMIT = "189adda99d1b56da55fc5a6ee3f849354aaea92a"


def jwt(secret: str, role: str) -> str:
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    payload = enc({"alg": "HS256", "typ": "JWT"}) + b"." + enc({
        "role": role, "iss": "supabase", "iat": int(time.time()), "exp": int(time.time()) + 10 * 365 * 86400,
    })
    return (payload + b"." + base64.urlsafe_b64encode(hmac.new(secret.encode(), payload, hashlib.sha256).digest()).rstrip(b"=")).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True, help="Checkout of the pinned official Supabase repository")
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != UPSTREAM_COMMIT:
        parser.error("Upstream checkout does not match the reviewed release commit")
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    runtime = STATE / "runtime"
    if runtime.exists():
        parser.error("Runtime already exists; refusing to overwrite credentials or persistent data")
    shutil.copytree(args.upstream / "docker", runtime)
    image_lock = ROOT / "deploy/local-supabase/images.lock.yml"
    if image_lock.exists():
        shutil.copyfile(image_lock, runtime / "images.lock.yml")
    values = {}
    for line in (runtime / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    secret = secrets.token_hex(32)
    values.update({
        "COMPOSE_FILE": "docker-compose.yml:pairrole.override.yml" + (":images.lock.yml" if image_lock.exists() else ""),
        "POSTGRES_PASSWORD": secrets.token_hex(32), "JWT_SECRET": secret,
        "ANON_KEY": jwt(secret, "anon"), "SERVICE_ROLE_KEY": jwt(secret, "service_role"),
        "DASHBOARD_USERNAME": "pairrole", "DASHBOARD_PASSWORD": secrets.token_hex(24),
        "SECRET_KEY_BASE": secrets.token_hex(48), "REALTIME_DB_ENC_KEY": secrets.token_hex(8),
        "VAULT_ENC_KEY": secrets.token_hex(16), "PG_META_CRYPTO_KEY": secrets.token_hex(32),
        "LOGFLARE_PUBLIC_ACCESS_TOKEN": secrets.token_hex(32), "LOGFLARE_PRIVATE_ACCESS_TOKEN": secrets.token_hex(32),
        "S3_PROTOCOL_ACCESS_KEY_ID": secrets.token_hex(16), "S3_PROTOCOL_ACCESS_KEY_SECRET": secrets.token_hex(32),
        "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
        "SUPABASE_PUBLIC_URL": "http://127.0.0.1:55321", "API_EXTERNAL_URL": "http://127.0.0.1:55321/auth/v1",
        "SITE_URL": "http://127.0.0.1:8501", "DISABLE_SIGNUP": "true", "ENABLE_EMAIL_SIGNUP": "false",
        "ENABLE_PHONE_SIGNUP": "false", "ENABLE_PHONE_AUTOCONFIRM": "false",
        "POOLER_TENANT_ID": "pairrole-local", "STUDIO_DEFAULT_PROJECT": "PairRole local",
        "STUDIO_DEFAULT_ORGANIZATION": "Private", "OPENAI_API_KEY": "",
        "PGRST_DB_SCHEMAS": "public", "PGRST_DB_EXTRA_SEARCH_PATH": "public,extensions",
    })
    (runtime / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    (runtime / ".env").chmod(0o600)
    override = """name: pairrole-local
services:
  studio:
    container_name: pairrole-local-studio
  api-gw:
    container_name: pairrole-local-gateway
    ports: !override
      - "127.0.0.1:55321:8000"
  auth:
    container_name: pairrole-local-auth
  rest:
    container_name: pairrole-local-rest
  realtime:
    container_name: realtime-dev.pairrole-local-realtime
  storage:
    container_name: pairrole-local-storage
  imgproxy:
    container_name: pairrole-local-imgproxy
  meta:
    container_name: pairrole-local-meta
  functions:
    container_name: pairrole-local-functions
  db:
    container_name: pairrole-local-db
    image: public.ecr.aws/supabase/postgres:17.11.0.006
    ports:
      - "127.0.0.1:55322:5432"
  supavisor:
    container_name: pairrole-local-pooler
    ports: !reset []
"""
    (runtime / "pairrole.override.yml").write_text(override)
    (STATE / "deployment.json").write_text(json.dumps({
        "upstream_commit": commit, "upstream_tag": "self-hosted/v0.8.4",
        "project": "pairrole-local", "api_url": values["SUPABASE_PUBLIC_URL"], "database_port": 55322,
    }, indent=2) + "\n")
    (STATE / "destination.env").write_text(
        f"SUPABASE_URL={values['SUPABASE_PUBLIC_URL']}\n"
        f"SUPABASE_SECRET_KEY={values['SERVICE_ROLE_KEY']}\n"
        f"DASHBOARD_SUMMARY_SUPABASE_SECRET_KEY={values['SERVICE_ROLE_KEY']}\n"
        "PAIRROLE_EXPECTED_SUPABASE_URL=http://127.0.0.1:55321\n"
    )
    print("Prepared isolated deployment. Online application configuration is unchanged.")


if __name__ == "__main__":
    main()
