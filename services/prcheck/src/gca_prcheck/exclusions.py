"""Exclusion rules (T072; FR-021): glob rules from PortalSettings.exclusion_rules, matched against changed paths.

Excluded files are never read or attributed; they're listed in `ChangeHead.excluded_paths` with reason `rule`.
The glob matching lives in `gcattr.diff`, shared with `gca attribute`.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gcattr.diff import DEFAULT_EXCLUSIONS as DEFAULT_RULES
from gcattr.diff import ExclusionRules as Rules
from gcattr.diff import glob_to_regex

__all__ = ["DEFAULT_RULES", "Rules", "glob_to_regex", "load_rules"]


def load_rules(engine: Engine) -> Rules:
    with engine.connect() as conn:
        rules = conn.execute(text("SELECT exclusion_rules FROM portal_settings WHERE id = 1")).scalar()
    return Rules(DEFAULT_RULES if rules is None else rules)
