"""Allow `python -m winnow` as well as the installed `winnow` command.

Without this, a user who has not run `pip install -e .` has no way to start the tool at
all -- the README's commands simply fail. Two entry points, one of which needs no install.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
