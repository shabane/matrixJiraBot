"""Entry point: python -m matrix_jira_bot [path/to/config.yaml]"""
from __future__ import annotations

import asyncio
import logging
import sys

from .bot import Bot
from .config import load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)
    bot = Bot(config)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
