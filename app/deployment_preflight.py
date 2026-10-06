"""Read-only production configuration checks; never print secret values."""

import os
import sys
from urllib.parse import urlsplit


def validate_environment(values):
    errors = []
    origin = values.get("RADAR_PUBLIC_ORIGIN", "").strip()
    try:
        parsed = urlsplit(origin)
        valid_origin = (parsed.scheme == "https" and bool(parsed.hostname) and
                        not parsed.username and not parsed.password and
                        origin == f"{parsed.scheme}://{parsed.netloc}")
    except ValueError:
        valid_origin = False
    if not valid_origin:
        errors.append("RADAR_PUBLIC_ORIGIN must be an HTTPS origin without a path or trailing slash")
    if len(values.get("RADAR_WORKER_TOKEN", "")) < 32:
        errors.append("RADAR_WORKER_TOKEN must be a nonempty random value of at least 32 characters")
    if values.get("RADAR_ALLOW_HTTP_LOCAL") == "1":
        errors.append("RADAR_ALLOW_HTTP_LOCAL must be disabled in production")
    return errors


def main():
    errors = validate_environment(os.environ)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Production account configuration: OK (no secret values shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
