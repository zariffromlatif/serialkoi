"""Entry point: `uvicorn server:app` (reads settings from the environment / .env)."""
from pathlib import Path
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")

env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

os.environ.setdefault("SK_DB", str(Path(__file__).with_name("serialkoi.db")))

from app.main import create_app  # noqa: E402

app = create_app()
