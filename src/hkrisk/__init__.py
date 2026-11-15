"""HK market-risk engine and agent."""

from pathlib import Path

__version__ = "0.1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    from hkrisk.cli import main as cli_main

    cli_main()
