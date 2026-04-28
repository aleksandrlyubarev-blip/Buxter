import logging

from rich.logging import RichHandler


def configure(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False, show_path=False)],
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
