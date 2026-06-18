"""Fake JSON-line app-server. Only used to test the localhost bridge."""
import json
import sys

for line in sys.stdin:
    data = json.loads(line)
    method = data.get('method')
    if 'id' not in data:
        continue
    if method == 'initialize':
        result = {"userAgent": "fake-test/1.0"}
    elif method == 'account/rateLimits/read':
        result = {
            "rateLimits": {
                "limitId": "codex",
                "planType": "plus",
                # This is *deliberately* weekly first, so positional guesses fail.
                "primary": {"usedPercent": 33.3, "windowDurationMins": 10080, "resetsAt": 1800000000},
                "secondary": {"usedPercent": 66.6, "windowDurationMins": 300, "resetsAt": 1790000000},
            },
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "planType": "plus",
                    "primary": {"usedPercent": 33.3, "windowDurationMins": 10080, "resetsAt": 1800000000},
                    "secondary": {"usedPercent": 66.6, "windowDurationMins": 300, "resetsAt": 1790000000},
                },
                "codex_other": {
                    "limitId": "codex_other",
                    "limitName": "Other pool",
                    "primary": {"usedPercent": 12, "windowDurationMins": 120, "resetsAt": 1800000000},
                },
            },
            "rateLimitResetCredits": {"availableCount": 2}
        }
    else:
        sys.stdout.write(json.dumps({"id": data['id'], "error": {"message": "unknown method"}}) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"id": data['id'], "result": result}) + "\n")
    sys.stdout.flush()
