# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib
import sys


def main() -> int | None:
    module_name, attributes, command, *arguments = sys.argv[1:]
    target = importlib.import_module(module_name)
    for attribute in attributes.split("."):
        target = getattr(target, attribute)
    sys.argv = [command, *arguments]
    return target()


if __name__ == "__main__":
    raise SystemExit(main())
