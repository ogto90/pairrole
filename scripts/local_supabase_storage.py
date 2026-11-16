#!/usr/bin/env python3
"""Snapshot private cloud objects and copy/verify them against the isolated local API."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-supabase"
LOCAL_URL = "http://127.0.0.1:55321"


def read_env(path: Path) -> dict[str, str]:
    return dict((k.strip(), v.strip().strip('\"').strip("'")) for k, v in (
        line.split("=", 1) for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class API:
    def __init__(self, values: dict[str, str], *, destination=False):
        self.url = values["SUPABASE_URL"].rstrip("/")
        if destination and self.url != LOCAL_URL:
            raise ValueError("Destination must be the isolated loopback API on port 55321")
        self.key = values["SUPABASE_SECRET_KEY"]
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, *, data=None, content_type="application/json", headers=None):
        req = Request(self.url + path, data=data, method=method, headers={
            "apikey": self.key, "Authorization": "Bearer " + self.key,
            "Content-Type": content_type, **(headers or {}),
        })
        try:
            with self.opener.open(req, timeout=60) as result:
                return result.read()
        except HTTPError as exc:
            raise RuntimeError(f"Storage request failed: HTTP {exc.code}") from None

    def json(self, method, path, data=None):
        return json.loads(self.request(method, path, data=None if data is None else json.dumps(data).encode()))


def objects(api: API, bucket: str):
    prefixes = [""]
    seen = set()
    while prefixes:
        prefix = prefixes.pop()
        if prefix in seen:
            raise ValueError("Repeated Storage prefix")
        seen.add(prefix)
        offset = 0
        while True:
            rows = api.json("POST", f"/storage/v1/object/list/{quote(bucket, safe='')}", {
                "prefix": prefix, "limit": 100, "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            })
            if not isinstance(rows, list):
                raise ValueError("Invalid Storage list response")
            for row in rows:
                name = (prefix + "/" if prefix else "") + row["name"]
                if row.get("id") is None:
                    prefixes.append(name)
                else:
                    yield name, row
            if len(rows) < 100:
                break
            offset += len(rows)


def object_path(bucket: str, name: str) -> str:
    return f"/storage/v1/object/{quote(bucket, safe='')}/{quote(name, safe='/')}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "restore", "verify"])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--local-source", action="store_true", help="Back up the local deployment instead of the cloud source")
    parser.add_argument("--expected-source-url", help="Independent confirmation of the cloud source API origin")
    parser.add_argument("--source-env", type=Path, default=ROOT / ".env", help="Private source credentials file")
    args = parser.parse_args()
    os.umask(0o077)
    folder = args.snapshot.resolve()
    if not folder.is_relative_to(STATE.resolve()):
        parser.error("Snapshots must remain in the private ignored deployment directory")
    manifest_path = folder / "storage.json"
    if args.action == "snapshot":
        if manifest_path.exists():
            parser.error("Snapshot already exists; use a fresh directory")
        api = API(read_env(STATE / "destination.env" if args.local_source else args.source_env), destination=args.local_source)
        if not args.local_source and (not args.expected_source_url or api.url != args.expected_source_url.rstrip("/")):
            parser.error("Source is not the expected cloud project")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        (folder / "objects").mkdir(mode=0o700, exist_ok=True)
        buckets = api.json("GET", "/storage/v1/bucket")
        manifest = {"buckets": buckets, "objects": []}
        for bucket in buckets:
            for name, metadata in objects(api, bucket["id"]):
                content = api.request("GET", object_path(bucket["id"], name))
                digest = hashlib.sha256(content).hexdigest()
                (folder / "objects" / digest).write_bytes(content)
                manifest["objects"].append({"bucket": bucket["id"], "name": name,
                    "sha256": digest, "bytes": len(content), "metadata": metadata})
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    else:
        manifest = json.loads(manifest_path.read_text())
        api = API(read_env(STATE / "destination.env"), destination=True)
        if args.action == "restore":
            current = {bucket["id"]: bucket for bucket in api.json("GET", "/storage/v1/bucket")}
            for bucket in manifest["buckets"]:
                settings = {key: bucket[key] for key in ["public", "file_size_limit", "allowed_mime_types"] if key in bucket}
                if bucket["id"] in current:
                    api.json("PUT", "/storage/v1/bucket/" + quote(bucket["id"], safe=""), settings)
                else:
                    api.json("POST", "/storage/v1/bucket", {"id": bucket["id"], "name": bucket["name"], **settings})
            for obj in manifest["objects"]:
                digest = obj["sha256"]
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("Invalid content digest")
                content = (folder / "objects" / digest).read_bytes()
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError("Snapshot object checksum failed")
                metadata = obj["metadata"].get("metadata") or {}
                api.request("POST", object_path(obj["bucket"], obj["name"]), data=content,
                            content_type=metadata.get("mimetype", "application/octet-stream"), headers={"x-upsert": "true"})
        expected = {(o["bucket"], o["name"]) for o in manifest["objects"]}
        actual = {(b["id"], name) for b in manifest["buckets"] for name, _ in objects(api, b["id"])}
        if expected != actual:
            raise ValueError("Destination object inventory differs from snapshot")
        for obj in manifest["objects"]:
            content = api.request("GET", object_path(obj["bucket"], obj["name"]))
            if hashlib.sha256(content).hexdigest() != obj["sha256"]:
                raise ValueError("Destination object checksum failed")
    print(f"Storage {args.action}: {len(manifest['objects'])} objects, {sum(o['bytes'] for o in manifest['objects'])} bytes")


if __name__ == "__main__":
    main()
