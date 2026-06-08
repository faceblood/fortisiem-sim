from __future__ import annotations

from pathlib import Path

import pytest

from fortisiem_sim.loaders import load_scenario, load_templates
from fortisiem_sim.models import SendOptions
from fortisiem_sim.render import build_context, render_body, render_wire
from fortisiem_sim.validators import validate_all


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates" / "events.yaml"
SCENARIO = ROOT / "scenarios" / "tabletop.yml"


def test_templates_load():
    templates = load_templates(TEMPLATES)
    assert len(templates) >= 27
    assert "login_success" in templates


def test_scenario_validate_clean():
    errors = validate_all(SCENARIO, TEMPLATES)
    assert errors == []


def test_render_placeholders():
    templates = load_templates(TEMPLATES)
    scenario = load_scenario(SCENARIO)
    opts = SendOptions(simulation_marker="simulated=true")
    ctx = build_context(scenario, templates["login_failed"], opts, actor_name="attacker")
    body = render_body(templates["login_failed"], ctx)
    assert "jgarcia" in body
    assert "simulated" in body


def test_wire_rfc3164_prefix():
    templates = load_templates(TEMPLATES)
    scenario = load_scenario(SCENARIO)
    opts = SendOptions()
    ctx = build_context(scenario, templates["login_success"], opts)
    wire = render_wire(templates["login_success"], ctx)
    assert wire.startswith("<134>")
