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

    # channel_type runs one channel or several ("wcf, web"), so check each.
    raw_channel = cfg.get("channel_type", "")
    if isinstance(raw_channel, list):
        channels = [str(c).strip() for c in raw_channel if str(c).strip()]
    else:
        channels = [c.strip() for c in str(raw_channel).split(",") if c.strip()]
    channel = ", ".join(channels)

    unsupported = [c for c in channels if c not in ("web", "terminal", "wcf")]
    if unsupported:
        fail(f"channel_type {unsupported!r} is not supported. "
             "Use 'web', 'terminal', or 'wcf'.")

    if "wcf" in channels:
        try:
            import wcferry  # noqa: F401
        except ImportError:
            fail("channel_type includes 'wcf' but the wcferry package is not installed.\n"
                 r"    Run: .venv\Scripts\pip install wcferry" "\n"
                 "    (wcferry is Windows-only; requirements.txt skips it elsewhere by design.)")

        # Both of these start cleanly, log nothing alarming, and answer every
        # message with silence -- the worst shape a misconfiguration can take.
        if not cfg.get("wcf_contact_white_list"):
            fail("channel_type includes 'wcf' but wcf_contact_white_list is empty, "
                 "so the agent would answer nobody.\n"
                 "    Add a wxid or display name (start with 'filehelper', the "
                 "File Transfer Assistant).")
        prefixes = cfg.get("single_chat_prefix", ["bot", "@bot"])
        if prefixes and "" not in prefixes:
            fail(f"single_chat_prefix is {prefixes!r}, so a WeChat contact would have "
                 f"to start every message with {prefixes[0]!r} to get a reply.\n"
                 '    Set "single_chat_prefix": [""] to answer plain messages.\n'
                 "    (The web console prepends the prefix itself, so it is unaffected.)")

    print(f"    model={cfg.get('model')}  channel={channel}  port={cfg.get('web_port', 9899)}")


if __name__ == "__main__":
    main()
