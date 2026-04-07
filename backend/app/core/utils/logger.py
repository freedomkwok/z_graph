import logging


def get_logger(name: str) -> logging.Logger:
    """Backward-compatible logger helper."""
    return logging.getLogger(name)
