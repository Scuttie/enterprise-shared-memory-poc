"""Secret providers (P4/§15). Environment secrets are for test/local ONLY and are refused in
staging/production. The external manager is a fail-closed placeholder until wired to a real secret store."""
from __future__ import annotations
import os
from abc import ABC, abstractmethod


class SecretError(Exception):
    pass


class SecretProvider(ABC):
    @abstractmethod
    def get_secret(self, name: str) -> str: ...


class EnvSecretProvider(SecretProvider):
    def __init__(self, environment: str = "test"):
        if environment in ("staging", "production"):
            raise SecretError("environment secrets are forbidden in %s" % environment)
        self._env = environment

    def get_secret(self, name: str) -> str:
        v = os.environ.get(name)
        if not v:
            raise SecretError("missing secret %s" % name)
        return v


class KubernetesSecretReferenceProvider(SecretProvider):
    """Configuration adapter: reads a secret from a mounted file path (K8s secret volume)."""
    def __init__(self, mount_dir: str):
        self._dir = mount_dir

    def get_secret(self, name: str) -> str:
        path = os.path.join(self._dir, name)
        if not os.path.isfile(path):
            raise SecretError("secret file not present: %s" % name)
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if not v:
            raise SecretError("empty secret %s" % name)
        return v


class ExternalSecretManagerProvider(SecretProvider):
    """Placeholder for a real external secret manager. Fail-closed until configured."""
    def __init__(self, client=None):
        self._client = client

    def get_secret(self, name: str) -> str:
        if self._client is None:
            raise SecretError("external secret manager not configured (fail-closed)")
        return self._client.get_secret(name)
