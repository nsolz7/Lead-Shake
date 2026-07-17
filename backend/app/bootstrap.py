from app.config import get_settings
from app.database import SessionLocal
from app.source_catalog import seed_source_catalog


def main() -> None:
    settings = get_settings()
    (settings.data_dir / "imports").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "exports").mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed_source_catalog(db)


if __name__ == "__main__":
    main()
