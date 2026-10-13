"""Official application entry for the Xuxia QML desktop UI."""

import sys

# The fixed frozen worker must dispatch before importing Qt or constructing UI.
# Normal imports retain the public main alias and existing application runtime.
if __name__ == "__main__" and sys.argv[1:2] == ["--local-preparation-worker-v1"]:
    from src.services.local_ai.preparation_worker import main as _preparation_main
    raise SystemExit(_preparation_main(sys.argv[2:]))

from src.main_qml import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
