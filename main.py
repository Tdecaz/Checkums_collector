"""Entry point for the checksum collector GUI application."""
from __future__ import annotations

from collector.gui import Application


def main() -> None:
    app = Application()
    app.mainloop()


if __name__ == "__main__":
    main()
