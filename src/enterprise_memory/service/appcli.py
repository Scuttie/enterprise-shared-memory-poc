"""`enterprise-memory-api` entrypoint — runs the production FastAPI app (separate lifecycle from the
worker). The legacy insecure PoC app is never started here."""
import os


def main():
    import uvicorn
    from .app import create_app
    app = create_app()
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
