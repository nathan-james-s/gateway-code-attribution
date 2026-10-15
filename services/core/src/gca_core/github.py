"""Thin githubkit wrapper for the GitHub App (contracts/github-app.md; research R11, R16; T035).

Code fetched here (patches, blame) is returned to the caller in memory and never logged or stored.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from githubkit import AppAuthStrategy, GitHub, TokenAuthStrategy

__all__ = [
    "AppClient",
    "BlameRange",
    "ChangedFile",
    "Comparison",
    "PrCommit",
    "SignInError",
    "UserClient",
    "authorize_url",
    "exchange_code",
]

BLAME_QUERY = """
query($owner: String!, $repo: String!, $oid: GitObjectID!, $path: String!) {
  repository(owner: $owner, name: $repo) {
    object(oid: $oid) {
      ... on Commit {
        blame(path: $path) {
          ranges { startingLine endingLine commit { oid } }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    status: str
    additions: int
    patch: str | None  # None when GitHub omits the patch (large files or diffs) -> caller falls back (T053)
    sha: str | None
    previous_filename: str | None = None  # set for renames


@dataclass(frozen=True)
class Comparison:
    merge_base_sha: str
    files: list[ChangedFile]
    commit_shas: list[str]


@dataclass(frozen=True)
class PrCommit:
    sha: str
    author_github_id: int | None  # None when GitHub links the commit author to no account (FR-015)


@dataclass(frozen=True)
class BlameRange:
    start: int
    end: int
    commit_sha: str


@dataclass
class AppClient:
    app_id: int
    private_key: str
    _installations: dict[int, GitHub[Any]] = field(default_factory=dict)
    _app_gh: GitHub[Any] | None = None

    def _app(self) -> GitHub[Any]:
        # githubkit's `.rest` namespaces hold only a weak reference to their client, so the client must be
        # kept alive here rather than built per call.
        if self._app_gh is None:
            self._app_gh = GitHub(AppAuthStrategy(str(self.app_id), self.private_key))
        return self._app_gh

    def installation(self, installation_id: int) -> GitHub[Any]:
        if installation_id not in self._installations:
            app = self._app()
            self._installations[installation_id] = app.with_auth(
                app.auth.as_installation(installation_id)  # type: ignore[union-attr]
            )
        return self._installations[installation_id]

    async def list_installations(self) -> list[dict[str, Any]]:
        resp = await self._app().rest.apps.async_list_installations(per_page=100)
        return [i.model_dump() for i in resp.parsed_data]

    async def installation_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        gh = self.installation(installation_id)
        resp = await gh.rest.apps.async_list_repos_accessible_to_installation(per_page=100)
        return [r.model_dump() for r in resp.parsed_data.repositories]

    async def get_pull(self, installation_id: int, owner: str, repo: str, number: int) -> dict[str, Any]:
        gh = self.installation(installation_id)
        resp = await gh.rest.pulls.async_get(owner, repo, number)
        return resp.parsed_data.model_dump()

    async def open_pulls(self, installation_id: int, owner: str, repo: str) -> list[dict[str, Any]]:
        gh = self.installation(installation_id)
        out: list[dict[str, Any]] = []
        async for pr in gh.paginate(
            gh.rest.pulls.async_list, owner=owner, repo=repo, state="open", per_page=100
        ):
            out.append(pr.model_dump())
        return out

    async def compare(self, installation_id: int, owner: str, repo: str, base: str, head: str) -> Comparison:
        gh = self.installation(installation_id)
        resp = await gh.rest.repos.async_compare_commits(owner, repo, f"{base}...{head}", per_page=100)
        data = resp.parsed_data
        files = [
            ChangedFile(
                f.filename,
                f.status,
                f.additions,
                getattr(f, "patch", None) or None,
                getattr(f, "sha", None),
                getattr(f, "previous_filename", None) or None,
            )
            for f in (data.files or [])
        ]
        return Comparison(data.merge_base_commit.sha, files, [c.sha for c in data.commits])

    async def pr_commits(self, installation_id: int, owner: str, repo: str, number: int) -> list[PrCommit]:
        gh = self.installation(installation_id)
        out: list[PrCommit] = []
        async for c in gh.paginate(
            gh.rest.pulls.async_list_commits, owner=owner, repo=repo, pull_number=number, per_page=100
        ):
            author = getattr(c, "author", None)
            out.append(PrCommit(c.sha, getattr(author, "id", None) if author else None))
        return out

    async def blame(
        self, installation_id: int, owner: str, repo: str, oid: str, path: str
    ) -> list[BlameRange]:
        gh = self.installation(installation_id)
        data = await gh.async_graphql(BLAME_QUERY, {"owner": owner, "repo": repo, "oid": oid, "path": path})
        ranges = (((data.get("repository") or {}).get("object") or {}).get("blame") or {}).get("ranges") or []
        return [BlameRange(r["startingLine"], r["endingLine"], r["commit"]["oid"]) for r in ranges]

    async def blob_text(self, installation_id: int, owner: str, repo: str, path: str, ref: str) -> str | None:
        """Raw file content at ``ref`` (in memory only), or None if missing or binary."""
        gh = self.installation(installation_id)
        try:
            resp = await gh.arequest(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref},
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except Exception:
            return None
        try:
            return resp.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def org_teams(self, installation_id: int, org: str) -> list[dict[str, Any]]:
        gh = self.installation(installation_id)
        return [t.model_dump() async for t in gh.paginate(gh.rest.teams.async_list, org=org, per_page=100)]

    async def team_members(
        self, installation_id: int, org: str, team_slug: str, role: str
    ) -> list[dict[str, Any]]:
        gh = self.installation(installation_id)
        return [
            m.model_dump()
            async for m in gh.paginate(
                gh.rest.teams.async_list_members_in_org, org=org, team_slug=team_slug, role=role, per_page=100
            )
        ]

    async def org_owners(self, installation_id: int, org: str) -> list[dict[str, Any]]:
        gh = self.installation(installation_id)
        return [
            m.model_dump()
            async for m in gh.paginate(gh.rest.orgs.async_list_members, org=org, role="admin", per_page=100)
        ]

    async def create_check_run(self, installation_id: int, owner: str, repo: str, **body: Any) -> int:
        gh = self.installation(installation_id)
        resp = await gh.rest.checks.async_create(owner, repo, data=body)
        return int(resp.parsed_data.id)

    async def update_check_run(
        self, installation_id: int, owner: str, repo: str, check_run_id: int, **body: Any
    ) -> None:
        gh = self.installation(installation_id)
        await gh.rest.checks.async_update(owner, repo, check_run_id, data=body)


# ---------------------------------------------------------------------------------------------- user OAuth
def authorize_url(client_id: str, redirect_uri: str, state: str | None = None) -> tuple[str, str]:
    state = state or secrets.token_urlsafe(24)
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return f"https://github.com/login/oauth/authorize?{query}", state


@dataclass
class UserClient:
    """Acts as the signed-in user (identity, live org and team roles; FR-029a)."""

    gh: GitHub[Any]
    token: str = field(default="", repr=False)

    @classmethod
    def from_token(cls, token: str) -> UserClient:
        return cls(GitHub(TokenAuthStrategy(token)), token)

    async def me(self) -> dict[str, Any]:
        resp = await self.gh.rest.users.async_get_authenticated()
        return resp.parsed_data.model_dump()

    async def org_role(self, org: str) -> str | None:
        """'admin' (org owner), 'member', or None if not a member."""
        try:
            resp = await self.gh.rest.orgs.async_get_membership_for_authenticated_user(org)
        except Exception:
            return None
        return str(resp.parsed_data.role)

    async def team_role(self, org: str, team_slug: str, username: str) -> str | None:
        """'maintainer', 'member', or None."""
        try:
            resp = await self.gh.rest.teams.async_get_membership_for_user_in_org(org, team_slug, username)
        except Exception:
            return None
        return str(resp.parsed_data.role)

    async def maintained_teams(self, org: str, login: str) -> list[str]:
        """Slugs of the teams in ``org`` that the user maintains. Empty on any GitHub error (fail closed)."""
        try:
            slugs = [
                t.slug
                async for t in self.gh.paginate(
                    self.gh.rest.teams.async_list_for_authenticated_user, per_page=100
                )
                if t.organization.login.lower() == org.lower()
            ]
        except Exception:
            return []
        return [s for s in slugs if await self.team_role(org, s, login) == "maintainer"]

    async def login_for_id(self, account_id: int) -> str | None:
        try:
            resp = await self.gh.rest.users.async_get_by_id(account_id)
        except Exception:
            return None
        return str(resp.parsed_data.login)

    async def user_by_login(self, login: str) -> dict[str, Any] | None:
        try:
            resp = await self.gh.rest.users.async_get_by_username(login)
        except Exception:
            return None
        return dict(resp.parsed_data.model_dump())

    async def can_view_repo(self, owner: str, repo: str) -> bool:
        try:
            await self.gh.rest.repos.async_get(owner, repo)
        except Exception:
            return False
        return True


TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - an endpoint, not a secret


class SignInError(RuntimeError):
    """GitHub refused the sign-in code (expired, already used, or a client mismatch)."""


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> UserClient:
    """Exchange a one-time sign-in code for a user token, with exactly one request.

    githubkit's OAuthWebAuthStrategy sends its exchange through a client whose auth flow exchanges the code
    first, so the real request fails with bad_verification_code. Codes are single use, so it's done directly.
    """
    body = {"client_id": client_id, "client_secret": client_secret, "code": code}
    if redirect_uri:
        body["redirect_uri"] = redirect_uri
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        resp = await client.post(TOKEN_URL, data=body, headers={"Accept": "application/json"})
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    token = data.get("access_token")
    if resp.status_code != 200 or not token:
        raise SignInError(str(data.get("error") or f"HTTP {resp.status_code}"))
    return UserClient.from_token(str(token))
