from __future__ import annotations

from fortisiem_sim.c2 import classify_ioc, merge_c2_import, normalize_c2, parse_c2_text


def test_classify_ioc_ip_and_uri():
    assert classify_ioc("203.0.113.66") == ("ip", "203.0.113.66")
    assert classify_ioc("https://evil.example/beacon")[0] == "uri"
    assert classify_ioc("malware-c2.example.com/gate")[0] == "uri"


def test_parse_c2_text_file():
    text = """
    # IOC lab
    203.0.113.77
    https://c2.example.com/payload
    malware.net/beacon
    """
    parsed = parse_c2_text(text)
    assert "203.0.113.77" in parsed["ips"]
    assert any("c2.example.com" in u for u in parsed["uris"])


def test_normalize_c2_defaults_when_empty():
    c2 = normalize_c2({"ips": [], "uris": []})
    assert c2["default_ip"]
    assert c2["default_uri"]
    assert len(c2["ips"]) >= 1
    assert len(c2["uris"]) >= 1


def test_merge_c2_import():
    base = normalize_c2({"default_ip": "203.0.113.50", "ips": ["203.0.113.50"], "uris": []})
    merged = merge_c2_import(base, {"ips": ["198.51.100.99"], "uris": ["https://new.example/x"]})
    assert "198.51.100.99" in merged["ips"]
    assert "https://new.example/x" in merged["uris"]
