#!/usr/bin/env python3
"""Search MySQL and MongoDB for DigitalOcean / firewall configuration."""
from __future__ import annotations

import json
import re
import subprocess
import sys

DO_RE = re.compile(
    r"digitalocean|doctl|do_token|do_api|dop_v1|cloud.?firewall|"
    r"firewall_id|DO_FIREWALL|DOCTL",
    re.I,
)
INTERESTING_RE = re.compile(
    r"config|setting|secret|credential|token|key|env|firewall|digital|cloud|integration",
    re.I,
)


def get_creds_from_proc():
    mysql_dsn = ""
    mongo_uri = ""
    import glob
    for path in glob.glob("/proc/[0-9]*/environ"):
        try:
            raw = open(path, "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        for line in raw.split("\0"):
            if line.startswith("MYSQL_DSN=") and not mysql_dsn:
                mysql_dsn = line.split("=", 1)[1]
            elif line.startswith("MONGODB_URI=") and not mongo_uri:
                mongo_uri = line.split("=", 1)[1]
    return mysql_dsn, mongo_uri


def parse_mysql_dsn(dsn):
    m = re.match(r"^([^:]+):([^@]+)@tcp\(([^:]+):(\d+)\)/(.+)$", dsn)
    if not m:
        raise ValueError(f"unrecognized MYSQL_DSN format: {dsn[:80]}")
    return m.group(1), m.group(2), m.group(3), int(m.group(4)), m.group(5)


def mysql_cmd_base(host, port, user, database, env):
    for ssl_flag in (["--ssl-mode=REQUIRED"], ["--ssl"], []):
        cmd = ["mysql", *ssl_flag, "-h", host, "-P", str(port), "-u", user, database]
        out = subprocess.run(cmd + ["-N", "-e", "SELECT 1"], capture_output=True, text=True, timeout=30, env=env)
        if out.returncode == 0:
            return cmd
    return ["mysql", "--ssl", "-h", host, "-P", str(port), "-u", user, database]


def search_mysql(dsn):
    print("=== MYSQL ===")
    if not dsn:
        print("SKIP: no MYSQL_DSN")
        return
    try:
        user, password, host, port, database = parse_mysql_dsn(dsn)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return
    print(f"Connecting to {host}:{port}/{database} as {user}")
    env = {**__import__("os").environ, "MYSQL_PWD": password}
    base = mysql_cmd_base(host, port, user, database, env)
    try:
        out = subprocess.run(
            base + ["-N", "-e", "SHOW TABLES"],
            capture_output=True, text=True, timeout=60, env=env,
        )
    except FileNotFoundError:
        print("ERROR: mysql client not installed")
        return
    if out.returncode != 0:
        print(f"ERROR: MySQL connect failed: {out.stderr.strip()[:200]}")
        return
    tables = [t for t in out.stdout.splitlines() if t.strip()]
    print(f"Tables: {len(tables)}")
    interesting = [t for t in tables if INTERESTING_RE.search(t)]
    print("--- Interesting table names ---")
    for t in interesting:
        print(t)
    print("--- Column name hits ---")
    for t in tables:
        cols_out = subprocess.run(
            base + ["-N", "-e", f"SHOW COLUMNS FROM `{t}`"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if cols_out.returncode != 0:
            continue
        cols = [line.split()[0] for line in cols_out.stdout.splitlines() if line]
        hits = [c for c in cols if DO_RE.search(c)]
        if hits:
            print(f"TABLE {t} COLS: {hits}")
    print("--- Data hits (REGEXP search) ---")
    data_hits = 0
    for t in tables:
        cols_out = subprocess.run(
            base + ["-N", "-e", f"SHOW COLUMNS FROM `{t}`"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if cols_out.returncode != 0:
            continue
        text_cols = []
        for line in cols_out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.search(r"varchar|text|json|char", parts[1], re.I):
                text_cols.append(parts[0])
        for col in text_cols[:12]:
            q = (f"SELECT `{col}` FROM `{t}` WHERE `{col}` REGEXP "
                 f"'digitalocean|doctl|do_token|firewall|dop_v1' LIMIT 5")
            row_out = subprocess.run(
                base + ["-N", "-e", q],
                capture_output=True, text=True, timeout=60, env=env,
            )
            for row in row_out.stdout.splitlines():
                if row.strip():
                    data_hits += 1
                    print(f"{t}.{col}: {row[:200]}")
    if data_hits == 0:
        print("No DO/firewall data matches in MySQL")


def search_mongo(uri):
    print("\n=== MONGODB ===")
    if not uri:
        print("SKIP: no MONGODB_URI")
        return
    try:
        import pymongo
    except ImportError:
        print("Installing pymongo...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pymongo"],
                       check=False, timeout=120)
        import pymongo
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=20000)
        client.admin.command("ping")
        db = client.get_default_database()
        print(f"Connected to database: {db.name}")
        cols = db.list_collection_names()
        print(f"Collections: {len(cols)}")
        interesting = [c for c in cols if INTERESTING_RE.search(c)]
        print("--- Interesting collection names ---")
        for c in interesting:
            print(c)
        print("--- Document hits ---")
        hits = 0
        for c in cols:
            for doc in db[c].find().limit(400):
                s = json.dumps(doc, default=str)
                if DO_RE.search(s):
                    hits += 1
                    print(f"{c}: {s[:250]}")
        if hits == 0:
            print("No DO/firewall matches in scanned MongoDB documents")
        client.close()
    except Exception as exc:
        print(f"MONGO_ERROR: {exc}")


def main():
    print("===== DATABASE DO/FIREWALL SEARCH =====")
    mysql_dsn, mongo_uri = get_creds_from_proc()
    if len(sys.argv) >= 3:
        mysql_dsn = sys.argv[1] or mysql_dsn
        mongo_uri = sys.argv[2] or mongo_uri
    search_mysql(mysql_dsn)
    search_mongo(mongo_uri)


if __name__ == "__main__":
    main()
