"""Who a limit counts an anonymous visitor as."""

import ipaddress


def network_of(address: str) -> str:
    """The address a limit keys on: an IPv4 address itself, an IPv6 address's /64.

    One IPv6 customer normally holds a whole /64, so keyed on the full address,
    every address in it would be a fresh visitor with a fresh quota.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if parsed.version == 4:
        return address
    return str(ipaddress.ip_network(f"{address}/64", strict=False))


class ByNetwork:
    """Mix into a DRF throttle, before it, to count a /64 as one visitor."""

    def get_ident(self, request) -> str:
        return network_of(super().get_ident(request))  # type: ignore[misc]
