"""python -m backend.app.repositories.cli status|upgrade|check"""
import argparse

from backend.app.core.settings import Settings
from .database import schema_status
from .migration import check, upgrade


def main():
    parser = argparse.ArgumentParser(description="Local schema maintenance; never imports quotation data")
    parser.add_argument("action", choices=("status", "upgrade", "check"))
    args = parser.parse_args()
    url = Settings().database_url
    try:
        if args.action == "upgrade":
            backup_path = upgrade(url)
            if backup_path:
                print("Pre-upgrade backup: " + str(backup_path))
        elif args.action == "check":
            check(url)
        print("Database schema: " + schema_status(url))
    except Exception as error:
        # Do not echo connection strings, SQL parameters or commercial payloads.
        print("Schema maintenance failed (" + type(error).__name__ + "). Check configuration and the documented recovery procedure.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
