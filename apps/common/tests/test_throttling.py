from rest_framework.test import APIRequestFactory
from rest_framework.throttling import BaseThrottle

from apps.common.throttling import ByNetwork, network_of


def test_an_ipv4_address_is_itself():
    assert network_of("203.0.113.7") == "203.0.113.7"


def test_an_ipv6_address_is_its_network():
    assert network_of("2001:db8:1:2:aaaa::1") == network_of("2001:db8:1:2:bbbb::2") == "2001:db8:1:2::/64"


def test_something_that_is_no_address_is_left_alone():
    assert network_of("") == ""


def test_a_throttle_counts_the_network():
    class Throttle(ByNetwork, BaseThrottle):
        pass

    request = APIRequestFactory().get("/", REMOTE_ADDR="2001:db8:1:2::1")

    assert Throttle().get_ident(request) == "2001:db8:1:2::/64"
