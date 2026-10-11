"""Read-only production configuration checks; never print secret values."""

import os
import re
import sys
from decimal import Decimal, InvalidOperation
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
    if values.get("GEMINI_ENABLED", "0") == "1":
        from gemini_service import RATES
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", values.get("GOOGLE_CLOUD_PROJECT", "")):
            errors.append("GOOGLE_CLOUD_PROJECT must be the Google Cloud project ID")
        if values.get("GEMINI_MODEL", "gemini-3.1-flash-lite") not in RATES:
            errors.append("GEMINI_MODEL must have a verified cost rate in gemini_service.RATES")
        if not re.fullmatch(r"[a-z0-9_]{3,32}", values.get("GEMINI_BUDGET_USERNAME", "default")):
            errors.append("GEMINI_BUDGET_USERNAME must name the MIRAO account receiving cost warnings")
        try:
            threshold = Decimal(values.get("GEMINI_MONTHLY_WARNING_USD", "8.5"))
            maximum = int(values.get("GEMINI_MAX_CALLS_PER_DAY", "100"))
            if not threshold.is_finite() or not Decimal("0.01") <= threshold <= Decimal("1000000") or not 1 <= maximum <= 10000:
                raise ValueError()
        except (InvalidOperation, ValueError):
            errors.append("Gemini warning threshold and daily request limit must be valid positive numbers")
    if bool(values.get("GEMINI_BILLING_SUBSCRIPTION")) != bool(values.get("GEMINI_BILLING_BUDGET_ID")):
        errors.append("Cloud Billing subscription and budget ID must be configured together")
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
