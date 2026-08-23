# Sandbox security

Local/test: hardened subprocess sandbox (env allow-list, path/network guards, process-tree kill).
**Production refuses the subprocess sandbox** (settings gate). Production requires `KubernetesJobSandbox`
with: pinned image digest, non-root, read-only rootfs, all caps dropped, seccomp RuntimeDefault, no
hostPath/Docker-socket/service-account-token, no API/model/DB credentials, ephemeral workspace,
CPU/memory/PID limits, wall-clock + activeDeadlineSeconds, ttlSecondsAfterFinished, default-deny
NetworkPolicy. Kubernetes isolation without gVisor/Kata/Firecracker requires company security approval;
a `SandboxProvider` adapter point is provided. The escape suite must run in the company cluster; a
detected escape is an immediate release blocker. Not run in this environment.
