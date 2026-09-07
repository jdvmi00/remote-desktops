#!/usr/bin/env python3
"""Build and run this checkout without installing desktop binaries."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "target/debug/remote-desktops"
UI = ROOT / "build/ui/remote-desktops-manager"


def build():
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("cargo is not on PATH; activate your Rust toolchain first")
    # Keep the executable path deterministic even with a custom Cargo target dir.
    subprocess.run([cargo, "build", "--locked", "--target-dir", str(ROOT / "target")], cwd=ROOT, check=True)
    subprocess.run(["cmake", "-S", "ui", "-B", "build/ui", "-DCMAKE_BUILD_TYPE=Debug"], cwd=ROOT, check=True)
    subprocess.run(["cmake", "--build", "build/ui", "--parallel", "2"], cwd=ROOT, check=True)


def check_daemon():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is required for live development")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        try:
            connection.connect(str(Path(runtime) / "remote-desktops/control.sock"))
        except (FileNotFoundError, ConnectionRefusedError) as error:
            raise RuntimeError("Start python3 scripts/dev.py daemon in another terminal first") from error
        pid, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise RuntimeError("The daemon belongs to another user")
        if not os.path.samefile(f"/proc/{pid}/exe", BACKEND):
            raise RuntimeError(
                f"Daemon PID {pid} is not the current checkout build. Disconnect streams and finish recovery, "
                "then stop that daemon and run python3 scripts/dev.py daemon. "
                "No running process was stopped."
            )
    print(f"Using checkout daemon PID {pid}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "preview", "daemon", "ui", "cli"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="arguments passed to the preview or CLI")
    args = parser.parse_args()
    if args.arguments and args.command not in ("preview", "cli"):
        parser.error("extra arguments are supported only for preview and cli")
    if args.command == "build":
        build()
        return
    executable = UI if args.command in ("preview", "ui") else BACKEND
    if not executable.is_file():
        raise RuntimeError("Run python3 scripts/dev.py build first")
    os.environ["REMOTE_DESKTOPS_HELPERS"] = str(ROOT)
    if args.command == "ui":
        check_daemon()
        command = [str(UI), "--backend", str(BACKEND)]
    elif args.command == "preview":
        command = [str(UI), "--demo", *args.arguments]
    elif args.command == "daemon":
        command = [str(BACKEND), "daemon"]
    else:
        command = [str(BACKEND), *args.arguments]
    print(f"Checkout: {ROOT}", flush=True)
    print(f"Executable: {executable}", flush=True)
    os.chdir(ROOT)
    os.execv(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"dev: {error}", file=sys.stderr)
        sys.exit(1)
