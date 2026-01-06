import logging


def configure_logging(level: str = "INFO"):
    level_value = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=level_value,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


__all__ = ["configure_logging"]
