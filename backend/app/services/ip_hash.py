"""IP hashing for abuse control."""

import hmac
import hashlib
import ipaddress


def truncate_ip(ip_str: str) -> str:
    try:
        addr = ipaddress.ip_address(ip_str)
        prefix = 24 if addr.version == 4 else 64
        network = ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False)
        return str(network.network_address)
    except ValueError:
        return ip_str


# Backwards-compatible alias.
truncate_ipv4_to_24 = truncate_ip


def hash_client_ip(ip_str: str, hmac_secret: str) -> str:
    truncated = truncate_ip(ip_str)
    return hmac.new(
        hmac_secret.encode("utf-8"),
        truncated.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
