"""Test-only uncooperative native child. Never imported by product workers."""
import ctypes
import os
import subprocess
import sys


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "descendant":
        child = subprocess.Popen([sys.executable, "-I", __file__, "hang"])
        os.write(1, str(child.pid).encode("ascii") + b"\n")
        ctypes.windll.kernel32.Sleep(0xFFFFFFFF)
    elif mode == "hang":
        ctypes.windll.kernel32.Sleep(0xFFFFFFFF)
    elif mode == "overflow":
        while True:
            os.write(1, b"x" * 65536)
    else:
        raise SystemExit(2)
