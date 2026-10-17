"""python -m backend: a single loopback-only server, no reload subprocess."""
import uvicorn

from backend.app.core.settings import Settings


def main():
    settings = Settings()
    uvicorn.run("backend.app.main:app", host=settings.app_host, port=settings.app_port,
                workers=1, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
