import logging

from ..core.config import settings


def configure_logging() -> None:
    level_name = str(settings.log_level or "INFO").upper()
    level_value = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level_value,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
