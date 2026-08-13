"""Frozen prompt / execution-view-compiler manifest (P5.1 §12). Kept in the experiments package so both the
freeze script and the seal tests recompute it from the same source of truth."""
from __future__ import annotations
import hashlib
import inspect

from .plan import INSTRUCTION_TEMPLATE
from enterprise_memory.service.execution import DirectModelExecutionBackend
from enterprise_memory.service import private_view
from enterprise_memory.contracts import codec


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _src_hash(*objs):
    h = hashlib.sha256()
    for o in objs:
        h.update(inspect.getsource(o).encode("utf-8"))
    return h.hexdigest()


def prompt_manifest():
    return {
        "instruction_template": INSTRUCTION_TEMPLATE,
        "instruction_template_hash": _sha(INSTRUCTION_TEMPLATE),
        "prompt_builder_hash": _src_hash(DirectModelExecutionBackend._build_prompt),
        "execution_view_compiler_hash": _src_hash(codec.retrieval_text_and_path_scope,
                                                  private_view.compile_private_view),
    }
