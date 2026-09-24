#!/usr/bin/env python3
"""Harbor's narrow Docker Compose calls over Podman on a local benchmark host.

Install this file as `docker` on PATH before Harbor, and set
PODMAN_COMPOSE_BIN to a separately installed podman-compose. Unsupported
commands fail closed; this is not a general Docker CLI replacement.
"""

import os
import subprocess
import sys


def main(args):
    if not args or args[0] != "compose":
        raise SystemExit("REFUSE: only Harbor docker compose is supported")
    args = args[1:]
    project = None
    i = 0
    while i < len(args):
        if args[i] == "-p" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "-f" and i + 1 < len(args):
            i += 2
        else:
            break
    if not project or i >= len(args):
        raise SystemExit("REFUSE: project or compose command missing")
    command, rest = args[i], args[i + 1 :]
    podman = os.environ.get("PODMAN_BIN", "podman")
    if command in ("build", "up", "down", "stop"):
        provider = os.environ.get("PODMAN_COMPOSE_BIN", "podman-compose")
        return subprocess.call([provider, *args])
    container = f"{project}_main_1"
    if command == "cp" and len(rest) == 2:
        source, target = rest
        source = source.replace("main:", f"{container}:", 1)
        target = target.replace("main:", f"{container}:", 1)
        return subprocess.call([podman, "cp", source, target])
    if command == "exec":
        command_args = []
        for arg in rest:
            if arg == "-it":
                continue
            if arg == "main":
                command_args.append(container)
            else:
                command_args.append(arg)
        if container not in command_args:
            raise SystemExit("REFUSE: expected main service")
        return subprocess.call([podman, "exec", *command_args])
    raise SystemExit(f"REFUSE: unsupported compose command {command}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
