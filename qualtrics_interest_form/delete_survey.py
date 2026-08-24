"""Delete a survey by ID. Usage: python delete_survey.py SV_xxx [SV_yyy ...]"""

from __future__ import annotations

import sys
from qualtrics_client import QualtricsClient, QualtricsError


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python delete_survey.py SV_xxx [SV_yyy ...]")
        sys.exit(1)
    c = QualtricsClient()
    for sid in sys.argv[1:]:
        try:
            c.delete_survey(sid)
            print(f"deleted {sid}")
        except QualtricsError as e:
            print(f"FAIL {sid}: {e}")


if __name__ == "__main__":
    main()
