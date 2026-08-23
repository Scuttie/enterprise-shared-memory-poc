"""P5.1 frozen static multi-user coding instrument (§6). A programmatically generated, executable
engineering/research instrument — NOT a claim of broad real-world coding generality. Each family binds one
reusable local convention across disjoint own-source / cross-user-source / target tasks; hidden tests enforce
the convention; no target answer ever enters memory."""
from .schema import Task, Family, ROLES
from . import families, fixtures, solver, audit

GENERATOR_VERSION = families.GENERATOR_VERSION
DOMAINS = families.DOMAINS
generate = families.generate
generation_hash = families.generation_hash

__all__ = ["Task", "Family", "ROLES", "GENERATOR_VERSION", "DOMAINS", "generate", "generation_hash",
           "families", "fixtures", "solver", "audit"]
