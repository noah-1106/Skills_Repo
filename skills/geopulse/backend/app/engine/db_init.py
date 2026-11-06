"""Small migration facade retained for operational scripts."""
from ..migrations import SCHEMA_VERSION, backup, initialize, migrate, restore


def init(seed: bool = True):
    return initialize(seed=seed)


__all__ = ["init", "initialize", "migrate", "backup", "restore", "SCHEMA_VERSION"]
