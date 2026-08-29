import sys

# GuildDraw uses PEP 604 unions (`float | None`) throughout, which only became
# legal at runtime in 3.10 -- an older interpreter dies with a bare TypeError
# deep inside the import chain instead of saying what is wrong (issue #11).
if sys.version_info < (3, 12):
    raise SystemExit(
        f"GuildDraw needs Python 3.12 or newer -- this is Python "
        f"{sys.version.split()[0]} ({sys.executable}).\n"
        "macOS ships an older python3 than that. Install a current Python "
        "(python.org installer, or `brew install python@3.12`) and name it "
        "when you build the virtualenv:\n"
        "    python3.12 -m venv .venv\n"
        "    .venv/bin/pip install -r requirements.txt\n"
        "    .venv/bin/python main.py"
    )

from framedraft.app import main  # noqa: E402  (must follow the version gate)

if __name__ == "__main__":
    main()
