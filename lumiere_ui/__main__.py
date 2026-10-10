# SPDX-License-Identifier: GPL-3.0-or-later
import sys

from .app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
