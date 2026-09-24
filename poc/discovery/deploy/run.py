"""Apply private output permissions before running the batch CLI."""

import os

from ..__main__ import main


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
