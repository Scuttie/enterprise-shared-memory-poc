"""Offline PoC demo entrypoint (P5 §3). This is the legacy, INSECURE demo app (it trusts client-provided
identity/patch/test results). It is for local offline demonstration ONLY and is refused in ci/staging/
production. The production API is `enterprise_memory.service.app.create_app`."""
from enterprise_memory.serving.api import create_offline_demo_app, LegacyAppRefused  # noqa: F401


def main():
    import uvicorn
    app = create_offline_demo_app()      # raises LegacyAppRefused unless ENVIRONMENT is local/test
    uvicorn.run(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
