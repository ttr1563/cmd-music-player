"""Keep multiprocessing dispatch before imports that initialize the CLI."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--internal-resolver"]:
        from music_cli.resolver import main
    else:
        from music_cli.cli import main
    main()
