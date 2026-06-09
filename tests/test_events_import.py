from __future__ import annotations

from pathlib import Path

import pytest

from fortisiem_sim.loaders import (
    load_templates,
    load_templates_merged,
    merge_custom_events_import,
    parse_events_import,
)
from fortisiem_sim.mitre import build_event_catalog, events_for_tactic


SAMPLE = """
version: 2
events:
  lab_custom_login:
    name: Custom lab login
    format: syslog_generic
    severity: info
    syslog_hostname: "{{hostname}}"
    body: |
      event=custom_login user={{user}} simulated=true
    mitre:
      tactics: [TA0001]
      techniques: [T1078]
"""


def test_parse_events_import_ok():
    events = parse_events_import(SAMPLE)
    assert "lab_custom_login" in events
    assert "body" in events["lab_custom_login"]


def test_parse_events_import_rejects_empty_body():
    bad = "events:\n  bad:\n    format: syslog_generic\n    body: ''\n"
    with pytest.raises(ValueError, match="body vacío"):
        parse_events_import(bad)


def test_merge_custom_events_and_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("FORTISIEM_SIM_STORAGE", "yaml")
    custom = tmp_path / "custom-events.yaml"
    monkeypatch.setattr(
        "fortisiem_sim.loaders.custom_events_path",
        lambda: custom,
    )
    added, updated = merge_custom_events_import(parse_events_import(SAMPLE), path=custom)
    assert added == ["lab_custom_login"]
    assert updated == []
    assert custom.exists()

    base = Path(__file__).resolve().parent.parent / "templates" / "events.yaml"
    monkeypatch.setattr(
        "fortisiem_sim.loaders.custom_events_path",
        lambda: custom,
    )
    merged = load_templates_merged(base)
    assert "lab_custom_login" in merged

    catalog = build_event_catalog(merged)
    entry = next(c for c in catalog if c["id"] == "lab_custom_login")
    assert entry["tactics"] == ["TA0001"]
    assert "lab_custom_login" in events_for_tactic("TA0001", merged)
