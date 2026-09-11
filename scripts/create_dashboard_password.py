#!/usr/bin/env python3
"""Create one PBKDF2 password hash for DASHBOARD_USERS_JSON."""
import base64
import getpass
import hashlib
import json
import secrets

username = input("Username: ").strip()
password = getpass.getpass("Password (12+ characters): ")
if len(username) < 2 or len(password) < 12:
    raise SystemExit("Use a username of 2+ and a password of 12+ characters.")
salt = secrets.token_urlsafe(18)
rounds = 310_000
digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
encoded = base64.urlsafe_b64encode(digest).decode("ascii")
print(json.dumps({username: {"password_hash": f"pbkdf2_sha256${rounds}${salt}${encoded}", "role": "admin"}}, ensure_ascii=False))
