#!/usr/bin/env python3
"""Authorize read-only Gmail access and store the credentials in GitHub Secrets."""

import argparse
import json
import secrets
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "http://127.0.0.1:8765"


def load_client(path):
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    client = payload.get("installed") or payload.get("web")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        raise SystemExit("The selected file is not a Google OAuth client JSON file.")
    return client["client_id"], client["client_secret"]


def receive_code(expected_state):
    result = {}
    event = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({key: values[0] for key, values in params.items() if values})
            message = "Gmail authorization received. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode("utf-8"))
            event.set()

        def log_message(self, _format, *_args):
            return

    server = HTTPServer(("127.0.0.1", 8765), Callback)
    while not event.is_set():
        server.handle_request()
    server.server_close()
    if result.get("state") != expected_state:
        raise SystemExit("Google returned an invalid OAuth state value.")
    if result.get("error"):
        raise SystemExit("Google authorization failed: " + result["error"])
    if not result.get("code"):
        raise SystemExit("Google did not return an authorization code.")
    return result["code"]


def exchange_code(client_id, client_secret, code):
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Revoke the app's prior access and run this setup again."
        )
    return refresh_token


def set_secret(repository, name, value):
    subprocess.run(
        ["gh", "secret", "set", name, "--repo", repository],
        input=value,
        text=True,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("client_json", help="Downloaded Google OAuth desktop-client JSON file")
    parser.add_argument("--repo", default="haoyileslie/property-macro-tracker")
    args = parser.parse_args()
    client_id, client_secret = load_client(args.client_json)
    state = secrets.token_urlsafe(24)
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"
    print("Opening Google authorization in your browser...")
    if not webbrowser.open(url):
        print(url)
    code = receive_code(state)
    refresh_token = exchange_code(client_id, client_secret, code)
    set_secret(args.repo, "GMAIL_CLIENT_ID", client_id)
    set_secret(args.repo, "GMAIL_CLIENT_SECRET", client_secret)
    set_secret(args.repo, "GMAIL_REFRESH_TOKEN", refresh_token)
    print(f"Stored three encrypted Gmail secrets in {args.repo}.")


if __name__ == "__main__":
    main()
