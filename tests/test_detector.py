"""Detector rules: length, entropy and rate, plus the warning threshold."""

from __future__ import annotations

import os

from app import detector, protocol


def _tunnel_queries(count: int = 25) -> list[str]:
    """Real encoder output: the queries a live transfer actually sends."""
    stream, header = protocol.build_stream(os.urandom(1200), "t.bin", compress=False)
    chunks = protocol.chunk_stream(stream)
    return [f"{i:03d}.{chunk}.{header['session']}.dnstunnel.cc.cd"
            for i, chunk in enumerate(chunks[:count], start=1)]


def test_shannon_entropy_bounds():
    assert detector.shannon_entropy("") == 0.0
    assert detector.shannon_entropy("aaaa") == 0.0
    assert detector.shannon_entropy("ab") == 1.0
    assert abs(detector.shannon_entropy("abcdefghijklmnopqrstuvwxyz234567") - 5.0) < 1e-9
    assert detector.shannon_entropy("hello") < 3.0


def test_long_random_label_is_flagged():
    engine = detector.Detector()
    qname = "mfrggzdfmztwq2lknnwg23tpobyxe43u7fqxs3dpq.482534.dnstunnel.cc.cd"
    assert detector.max_label_length(qname) > detector.LENGTH_LABEL_LIMIT
    result = engine.observe(qname, "10.0.0.9")
    rules = {alert["rule"] for alert in result["alerts"]}
    assert detector.RULE_LENGTH in rules
    assert any("label" in alert["reason"] for alert in result["alerts"])
    assert detector.RULE_ENTROPY in rules


def test_long_query_below_label_limit_is_flagged():
    engine = detector.Detector()
    # labels <= 40 chars each, whole name > 60
    qname = ".".join(["a" * 20, "b" * 20, "c" * 20, "example", "com"])
    assert len(qname) > detector.LENGTH_QUERY_LIMIT
    result = engine.observe(qname, "10.0.0.9")
    assert detector.RULE_LENGTH in {a["rule"] for a in result["alerts"]}


def test_normal_dns_passes_all_rules():
    engine = detector.Detector()
    names = [
        "www.google.com", "mail.google.com", "api.github.com",
        "cdn.jsdelivr.net", "docs.python.org", "example.com",
        "10.0.0.1.in-addr.arpa", "my-router.local",
    ]
    for name in names:
        result = engine.observe(name, "192.0.2.10")
        assert result["alerts"] == [], (name, result["alerts"])
        assert result["warning"] is False
    assert engine.warnings == 0


def test_high_rate_flags_after_twenty_queries():
    engine = detector.Detector()
    fired = []
    for index in range(25):
        result = engine.observe(f"host{index}.example.com", "192.0.2.20")
        if any(a["rule"] == detector.RULE_RATE for a in result["alerts"]):
            fired.append(index)
    assert fired, "rate rule never fired"
    assert fired[0] >= detector.RATE_COUNT


def test_rate_rule_needs_unique_names():
    engine = detector.Detector()
    for _ in range(30):
        result = engine.observe("same.example.com", "192.0.2.21")
        assert all(a["rule"] != detector.RULE_RATE for a in result["alerts"])
    assert engine.alerts == 0


def test_two_rules_inside_the_window_raise_the_warning():
    engine = detector.Detector()
    emitted = 0
    for index, qname in enumerate(_tunnel_queries(25)):
        result = engine.observe(qname, "10.0.0.9", now=1000.0 + index * 0.05)
        emitted += len(result["alerts"])
    assert result["warning"] is True
    assert set(result["rules_in_window"]) == {"entropy", "rate"}
    assert emitted > 0
    assert engine.warnings > 0


def test_one_rule_alone_does_not_warn():
    engine = detector.Detector()
    # A single long, low-entropy label trips only the length rule.
    qname = "a" * 55 + ".example.com"
    for index in range(3):
        result = engine.observe(qname, "192.0.2.30", now=2000.0 + index)
    assert result["warning"] is False
    assert result["rules_in_window"] == [detector.RULE_LENGTH]


def test_alerts_are_rate_limited_but_rules_keep_firing():
    engine = detector.Detector()
    qname = "mfrggzdfmztwq2lknnwg23tpobyxe43u7fqxs3dp.482534.dnstunnel.cc.cd"
    first = engine.observe(qname, "10.0.0.9", now=3000.0)
    again = engine.observe(qname, "10.0.0.9", now=3000.5)
    later = engine.observe(qname, "10.0.0.9", now=3005.0)
    assert first["alerts"]
    assert again["alerts"] == []          # cooldown suppresses the duplicate
    assert later["alerts"]                # and it comes back
