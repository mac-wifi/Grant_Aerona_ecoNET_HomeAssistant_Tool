"""Pure unit tests for the MAC / host helpers (no HA instance)."""
import pytest

from custom_components.econet_grant import discovery

ARP_HEADER = "IP address       HW type     Flags       HW address            Mask     Device\n"


def _arp(*rows):
    return ARP_HEADER + "".join(rows)


def test_parse_arp_normal_row():
    text = _arp("192.0.2.5  0x1  0x2  aa:bb:cc:dd:ee:ff  *  eth0\n")
    assert discovery.parse_arp_table(text, "192.0.2.5") == "aa:bb:cc:dd:ee:ff"


def test_parse_arp_incomplete_row_skipped():
    text = _arp("192.0.2.5  0x1  0x0  aa:bb:cc:dd:ee:ff  *  eth0\n")
    assert discovery.parse_arp_table(text, "192.0.2.5") is None


def test_parse_arp_all_zero_mac_skipped():
    text = _arp("192.0.2.5  0x1  0x2  00:00:00:00:00:00  *  eth0\n")
    assert discovery.parse_arp_table(text, "192.0.2.5") is None


def test_parse_arp_missing_ip():
    text = _arp("192.0.2.6  0x1  0x2  aa:bb:cc:dd:ee:ff  *  eth0\n")
    assert discovery.parse_arp_table(text, "192.0.2.5") is None


def test_parse_arp_header_only():
    assert discovery.parse_arp_table(ARP_HEADER, "192.0.2.5") is None


@pytest.mark.parametrize("host,expected", [
    ("192.0.2.5", "192.0.2.5"),
    ("192.0.2.5:8080", "192.0.2.5"),
    ("http://192.0.2.5:8080/", "192.0.2.5"),
    ("pump.example.invalid", None),
    ("http://pump.example.invalid:8080", None),
])
def test_host_ip(host, expected):
    assert discovery.host_ip(host) == expected


@pytest.mark.parametrize("old,new,expected", [
    ("192.0.2.5", "192.0.2.9", "192.0.2.9"),
    ("192.0.2.5:8080", "192.0.2.9", "192.0.2.9:8080"),
    ("http://192.0.2.5:8080/", "192.0.2.9", "http://192.0.2.9:8080"),
    ("https://192.0.2.5", "192.0.2.9", "https://192.0.2.9"),
])
def test_replace_host_ip(old, new, expected):
    assert discovery.replace_host_ip(old, new) == expected
