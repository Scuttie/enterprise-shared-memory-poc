"""P5.2 static coding instrument (frozen, disjoint from P5.1). Ordinary core + edge-case convention with
strata (prior_aligned / context_inferable / prior_conflict) so a nonzero M0 baseline is structurally possible
while >=12/16 calibration families still differ from the common prior."""
from .schema import Task, Family
from . import families, fixtures, solver, audit

GENERATOR_VERSION = families.GENERATOR_VERSION
DOMAINS = families.DOMAINS
STRATA = families.STRATA
generate = families.generate
generation_hash = families.generation_hash

__all__ = ["Task", "Family", "GENERATOR_VERSION", "DOMAINS", "STRATA", "generate", "generation_hash",
           "families", "fixtures", "solver", "audit"]
