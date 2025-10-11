#!/usr/bin/env python3
"""Send a quick DingTalk robot message for manual verification."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import httpx


def send_message(url: str, content: str, timeout: float = 5.0) -> httpx.Response:
    payload = {
        "msgtype": "text",
        "text": {
            "content": content,
        },
    }
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a SecLens test message to a DingTalk webhook.")
    parser.add_argument("url", help="DingTalk robot webhook URL, e.g. https://oapi.dingtalk.com/robot/send?access_token=...")
    parser.add_argument(
        "--message",
        "-m",
        default="[SecLens] Webhook test message from SecLens.",
        help="Text content to send. Default includes the SecLens keyword.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP timeout in seconds (default: 5.0)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        response = send_message(args.url, args.message, timeout=args.timeout)
    except httpx.HTTPStatusError as exc:
        sys.stderr.write(
            f"Request returned HTTP {exc.response.status_code}:\n{exc.response.text}\n"
        )
        return 1
    except httpx.HTTPError as exc:
        sys.stderr.write(f"Request failed: {exc}\n")
        return 1
    else:
        print(f"Message sent, response: {response.text}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
