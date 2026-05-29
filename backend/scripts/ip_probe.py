"""Probe the deployed /api/_debug/ip endpoint to learn how the platform
forwards client IPs.

Run this from EACH network you want to characterize (home wifi, phone
hotspot/cellular, a VPN exit, etc.). It sends:

  1. A clean request (no spoofing) -> shows the real forwarded chain.
  2. A spoofed request that injects a fake X-Forwarded-For -> shows whether a
     client can poison the value your rate limiter uses.

Usage:
    python scripts/ip_probe.py --base-url https://<service>.ai-builders.space --token <IP_DEBUG_TOKEN>

    # against a local server:
    python scripts/ip_probe.py --base-url http://127.0.0.1:8000 --token devsecret
"""

import argparse
import json
import sys

import httpx

SPOOF_IP = "203.0.113.99"  # TEST-NET-3, obviously fake


def _print_block(title: str, data: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def probe(base_url: str, token: str) -> int:
    url = f"{base_url.rstrip('/')}/api/_debug/ip"

    try:
        with httpx.Client(timeout=15.0) as client:
            clean = client.get(url, params={"token": token})
            spoofed = client.get(
                url,
                params={"token": token},
                headers={"X-Forwarded-For": SPOOF_IP},
            )
    except httpx.HTTPError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 2

    if clean.status_code != 200:
        print(
            f"Unexpected status {clean.status_code}: {clean.text[:300]}",
            file=sys.stderr,
        )
        print(
            "If 404: IP_DEBUG_TOKEN is not set on the server. "
            "If 403: the --token does not match the server's IP_DEBUG_TOKEN.",
            file=sys.stderr,
        )
        return 1

    clean_j = clean.json()
    spoof_j = spoofed.json()

    _print_block("CLEAN REQUEST (what the platform really sends)", clean_j)
    _print_block(f"SPOOFED REQUEST (client sent X-Forwarded-For: {SPOOF_IP})", spoof_j)

    print("\n=== VERDICT ===")
    limiter_ip = clean_j.get("current_limiter_ip")
    spoof_limiter_ip = spoof_j.get("current_limiter_ip")
    print(f"current_limiter_ip (clean)   : {limiter_ip}")
    print(f"current_limiter_ip (spoofed) : {spoof_limiter_ip}")

    if spoof_limiter_ip == SPOOF_IP:
        print(
            "\n[!] SPOOFABLE: a client controlled the IP your rate limiter keys "
            "on. Do NOT trust the left-most X-Forwarded-For. Pick the value the "
            "platform appends (typically the right-most XFF entry) instead."
        )
    else:
        print(
            "\n[ok] The spoofed header did NOT change the limiter IP. Confirm the "
            "clean value matches the public IP of THIS network before trusting it."
        )

    chain = clean_j.get("x_forwarded_for_chain") or []
    print(f"\nX-Forwarded-For chain length (clean): {len(chain)}")
    print(f"  left-most : {clean_j.get('x_forwarded_for_leftmost')}")
    print(f"  right-most: {clean_j.get('x_forwarded_for_rightmost')}")
    print(
        "\nTip: check https://api.ipify.org from this same network to learn this "
        "machine's real public IP, then see which XFF position matches it."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="e.g. https://my-svc.ai-builders.space")
    parser.add_argument("--token", required=True, help="value of IP_DEBUG_TOKEN on the server")
    args = parser.parse_args()
    sys.exit(probe(args.base_url, args.token))


if __name__ == "__main__":
    main()
