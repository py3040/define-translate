"""IP hashing for abuse control per TR-1.01-03."""

import hmac
import hashlib
import ipaddress


def truncate_ipv4_to_24(ip_str: str) -> str:
    """Truncate IPv4 to /24 (e.g. 192.168.1.100 -> 192.168.1.0)."""
    try:
        addr = ipaddress.ip_address(ip_str)
        if addr.version == 4:
            network = ipaddress.ip_network(f"{ip_str}/24", strict=False)
            return str(network.network_address)
    except ValueError:
        pass
    return ip_str


def hash_client_ip(ip_str: str, hmac_secret: str) -> str:
    """
    HMAC-SHA256 of IP. For IPv4, truncate to /24 first.
    Returns hex digest (or base64 - requirement says "keyed one-way hash").
    """
    truncated = truncate_ipv4_to_24(ip_str)
    return hmac.new(
        hmac_secret.encode("utf-8"),
        truncated.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
