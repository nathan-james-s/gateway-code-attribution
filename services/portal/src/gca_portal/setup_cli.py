"""`gca setup github-app` (T055; contracts/github-app.md; research R16).

Default: GitHub's App manifest flow. A local page posts the manifest to GitHub, GitHub redirects back to
localhost with a one-time code, and the code is exchanged for the App's credentials. ``--existing`` instead
packages the credentials of an App created by hand, prompting for secrets on the terminal.

Either way it writes two local files (both gitignored), and prints nothing secret:
  values-github.yaml       github.existingSecret + github.org for `helm install -f`
  github-app.secret.yaml   a Kubernetes Secret with appId, clientId, clientSecret, privateKey, webhookSecret
"""

from __future__ import annotations

import argparse
import getpass
import html
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import yaml

__all__ = ["manifest", "register", "write_outputs"]

SECRET_NAME = "gca-github-app"  # noqa: S105 - a Secret object name, not a secret
PERMISSIONS = {  # least privilege, exactly as contracts/github-app.md lists
    "checks": "write",
    "pull_requests": "read",
    "contents": "read",
    "metadata": "read",
    "members": "read",
    "emails": "read",  # Grafana sign-in needs the verified email
}
# installation and installation_repositories are always delivered to Apps and can't be listed.
EVENTS = ["pull_request", "check_run", "membership", "team", "organization"]


def manifest(
    name: str,
    portal_url: str,
    redirect_url: str,
    webhook_url: str | None,
    grafana_url: str = "http://localhost:3000",
) -> dict[str, Any]:
    return {
        "name": name,
        "url": portal_url,
        "hook_attributes": {
            "url": webhook_url or "https://example.invalid/gca-webhook",
            "active": bool(webhook_url),
        },
        "redirect_url": redirect_url,
        "callback_urls": [
            f"{portal_url.rstrip('/')}/auth/callback",
            grafana_url.rstrip("/") + "/login/github",
        ],
        "public": False,
        "default_permissions": PERMISSIONS,
        "default_events": EVENTS,
        "request_oauth_on_install": False,
    }


def write_outputs(out_dir: Path, creds: dict[str, str], org: str, namespace: str | None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": SECRET_NAME, **({"namespace": namespace} if namespace else {})},
        "type": "Opaque",
        "stringData": {
            k: creds[k] for k in ("appId", "clientId", "clientSecret", "privateKey", "webhookSecret")
        },
    }
    values = {"github": {"existingSecret": SECRET_NAME, "org": org}}
    secret_path = out_dir / "github-app.secret.yaml"
    values_path = out_dir / "values-github.yaml"
    for path, doc in ((secret_path, secret), (values_path, values)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False, default_style=None)
    return values_path, secret_path


# ---------------------------------------------------------------------------------------------- manifest flow
def _run_manifest_flow(args: argparse.Namespace) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # keep the one-time code out of the terminal
            return

        def _send(self, body: str, status: int = 200) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                target = (
                    f"https://github.com/organizations/{args.org}/settings/apps/new"
                    if args.org
                    else "https://github.com/settings/apps/new"
                )
                m = manifest(
                    args.name, args.portal_url, f"http://127.0.0.1:{port}/callback", args.webhook_url
                )
                self._send(
                    f'<form id="f" method="post" action="{html.escape(target)}?state={state}">'
                    f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(m))}">'
                    "<p>Redirecting to GitHub to create the App...</p></form>"
                    "<script>document.getElementById('f').submit()</script>"
                )
            elif url.path == "/callback":
                q = parse_qs(url.query)
                if q.get("state", [""])[0] != state or "code" not in q:
                    self._send(
                        "<p>Invalid state. Start again with <code>gca setup github-app</code>.</p>", 400
                    )
                    return
                result["code"] = q["code"][0]
                self._send("<p>GitHub App created. You can close this tab and return to the terminal.</p>")
                done.set()
            else:
                self._send("not found", 404)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start_url = f"http://127.0.0.1:{port}/"
    print(f"Open {start_url} to create the GitHub App (opening your browser).")
    if not args.no_browser:
        webbrowser.open(start_url)
    try:
        if not done.wait(timeout=600):
            raise SystemExit("timed out waiting for GitHub (10 minutes)")
    finally:
        server.shutdown()
    resp = httpx.post(
        f"https://api.github.com/app-manifests/{result['code']}/conversions",
        headers={"Accept": "application/vnd.github+json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"Created GitHub App {data.get('slug')}: {data.get('html_url')}")
    print(f"Install it on your repositories: {data.get('html_url')}/installations/new")
    return {
        "appId": str(data["id"]),
        "clientId": data["client_id"],
        "clientSecret": data["client_secret"],
        "privateKey": data["pem"],
        "webhookSecret": data.get("webhook_secret") or secrets.token_urlsafe(32),
    }


# ---------------------------------------------------------------------------------------------- existing App
def _existing_app(args: argparse.Namespace) -> dict[str, str]:
    if not (args.app_id and args.client_id and args.private_key_file):
        raise SystemExit("--existing needs --app-id, --client-id and --private-key-file")
    pem = Path(args.private_key_file).expanduser().read_text()
    if "PRIVATE KEY" not in pem:
        raise SystemExit(f"{args.private_key_file} does not look like a PEM private key")
    client_secret = os.environ.get("GCA_GITHUB_CLIENT_SECRET") or getpass.getpass("Client secret (hidden): ")
    if not client_secret:
        raise SystemExit("a client secret is required (generate one on the App's settings page)")
    webhook = os.environ.get("GCA_GITHUB_WEBHOOK_SECRET") or getpass.getpass(
        "Webhook secret (hidden; leave empty to generate one, needed only for webhook delivery): "
    )
    print(
        "Check the App's settings match contracts/github-app.md: callback URL "
        f"{args.portal_url.rstrip('/')}/auth/callback, permissions {PERMISSIONS}, events {EVENTS}."
    )
    return {
        "appId": str(args.app_id),
        "clientId": args.client_id,
        "clientSecret": client_secret,
        "privateKey": pem,
        "webhookSecret": webhook or secrets.token_urlsafe(32),
    }


def _cmd(args: argparse.Namespace) -> int:
    creds = _existing_app(args) if args.existing else _run_manifest_flow(args)
    values_path, secret_path = write_outputs(Path(args.out_dir), creds, args.org or "", args.namespace)
    ns = f" -n {args.namespace}" if args.namespace else ""
    print(f"Wrote {values_path} and {secret_path} (mode 0600; both are gitignored).")
    print(
        f"Next:\n  kubectl apply{ns} -f {secret_path}\n  make demo GATEWAY=agentgateway VALUES={values_path}"
    )
    return 0


def register(sub: Any) -> None:
    root = sub.add_parser("setup", help="one-time setup tasks")
    setup_sub = root.add_subparsers(dest="setup_command", required=True)
    p = setup_sub.add_parser(
        "github-app", help="create (or package) the GitHub App for the PR check and sign-in"
    )
    p.add_argument(
        "--name", default=f"gca-{secrets.token_hex(3)}", help="App name (must be unique on GitHub)"
    )
    p.add_argument("--org", default="", help="create the App under this organization (default: your account)")
    p.add_argument(
        "--portal-url", default="http://localhost:8080", help="portal URL used for sign-in callbacks"
    )
    p.add_argument("--webhook-url", default=None, help="public webhook URL; omit for polling delivery")
    p.add_argument("--port", type=int, default=0, help="local port for the manifest redirect (default: any)")
    p.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    p.add_argument("--out-dir", default=".", help="where to write values-github.yaml and the Secret")
    p.add_argument("--namespace", default=None, help="namespace to put in the Secret manifest")
    p.add_argument("--existing", action="store_true", help="package an App you created by hand instead")
    p.add_argument("--app-id", type=int, help="with --existing: the App ID")
    p.add_argument("--client-id", help="with --existing: the App's client ID")
    p.add_argument("--private-key-file", help="with --existing: the .pem downloaded from the App's settings")
    p.set_defaults(func=_cmd)
