"""Entry script for the packaged desktop app (see ausl_solver.spec)."""

import sys

from wildflyer.desktop import main

if __name__ == "__main__":
    sys.exit(main())
