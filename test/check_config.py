"""Pre-flight config check for test/run.cmd.

Fails loudly with an actionable message rather than letting app.py start
half-configured and die somewhere less obvious.
"""

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.json")
PLACEHOLDERS = {"", "YOUR API KEY", "YOUR_API_KEY", "your-api-key-here"}


def fail(msg: str) -> None:
    print(f"[X] {msg}")
    sys.exit(1)


def main() -> None:
    try:
        cfg = json.load(io.open(CFG, encoding="utf-8"))
    except FileNotFoundError:
        fail(f"config.json not found at {CFG}")
    except json.JSONDecodeError as e:
        fail(f"config.json is not valid JSON: {e}\n    Check for a trailing comma or a missing quote.")

    key = str(cfg.get("zhipu_ai_api_key", "")).strip()
    if key in PLACEHOLDERS:
        fail(
            'zhipu_ai_api_key is empty in config.json.\n'
            "    Get one at https://open.bigmodel.cn/usercenter/apikeys\n"
            f"    then paste it into {CFG}"
        )

    channel = str(cfg.get("channel_type", "")).strip()
    if channel not in ("web", "terminal"):
        fail(f"channel_type {channel!r} is not supported. Use 'web' or 'terminal'.")

    print(f"    model={cfg.get('model')}  channel={channel}  port={cfg.get('web_port', 9899)}")


if __name__ == "__main__":
    main()
