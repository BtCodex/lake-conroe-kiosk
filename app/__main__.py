"""Run with `python -m app` from the repository root."""
import logging
import uvicorn
from .config import load_config


def main():
    config = load_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP request logs are noisy on an unattended display; errors remain in the journal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run("app.main:app", host=config["server"]["host"], port=config["server"]["port"], access_log=False)


if __name__ == "__main__":
    main()
