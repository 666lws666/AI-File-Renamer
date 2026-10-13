"""Pinned public resources for an engineering probe; never loads or executes them.

Default CLI operation is offline verification. Network use requires --download.
Incomplete downloads stay in .part files; invalid final files are never replaced.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.local_ai.resource_transport import (  # noqa: E402
    CHUNK_BYTES, DISK_RESERVE_BYTES, SOCKET_TIMEOUT_SECONDS, SOURCE_HOSTS,
    REDIRECT_HOSTS, SAFE_NAME, RESERVED_NAMES, ResourceError, ResourceCancelled,
    validate_resource, verify_resource, fetch_resource, TrustedRedirectHandler,
    urlopen,
)

MANIFEST_PATH = ROOT / "resources/local-models/qwen35-4b-feasibility.json"
DEFAULT_DESTINATION = ROOT / "tests/screenshots/qa-current/local-privacy/resources"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Explicitly fetch pinned public resources")
    parser.add_argument("--only", nargs="+", choices=("runtime-cpu", "model-q4", "vision-f16"))
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        resources = manifest["resources"]
        for item in resources:
            validate_resource(item)
        last_progress = 0.0

        def progress(identifier, received, total):
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress >= 2 or received == total:
                print(f"{identifier}: {received}/{total} bytes", flush=True)
                last_progress = now

        success = True
        for item in resources:
            if args.only and item["id"] not in args.only:
                continue
            if args.download:
                fetch_resource(item, DEFAULT_DESTINATION, progress=progress)
                verified = True
            else:
                verified = verify_resource(DEFAULT_DESTINATION / item["filename"], item)
            print(f"{item['id']}: {'VERIFIED' if verified else 'NOT_VERIFIED'} {item['bytes']} bytes", flush=True)
            success = success and verified
        return 0 if success else 1
    except ResourceError as error:
        print(f"RESOURCE_ERROR: {error}", flush=True)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print("RESOURCE_ERROR: invalid or unavailable resource manifest", flush=True)
        return 1
    except KeyboardInterrupt:
        print("RESOURCE_CANCELLED: partial retained", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
