"""Viewer roles (FR-029a). Until US3 adds full role resolution (T083), only `is_admin` exists.

Admin: an owner of the configured GitHub organization, or a login listed in `portal.adminLogins`. The list is for
installs on a personal account, which has no organization owners.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["is_admin"]


async def is_admin(user: Any, org: str, login: str, admin_logins: Iterable[str]) -> bool:
    if login.lower() in {a.lower() for a in admin_logins}:
        return True
    if not org:
        return False
    return await user.org_role(org) == "admin"
