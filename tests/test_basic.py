from __future__ import annotations

from pathlib import Path

import pytest

from fortisiem_sim.loaders import load_scenario, load_templates, validate_all
from fortisiem_sim.models import SendOptions
from fortisiem_sim.render import build_context, render_body, render_wire


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates" / "events.yaml"
SCENARIO = ROOT / "scenarios" / "tabletop.yml"


def test_templates_load():
    templates = load_templates(TEMPLATES)
    assert len(templates) >= 23
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


def test_render_c2_from_config_pools():
    from fortisiem_sim.assets import apply_config_c2_to_scenario, load_assets
    from fortisiem_sim.loaders import load_scenario, load_templates
    from fortisiem_sim.models import SendOptions
    from fortisiem_sim.render import build_context, render_body

    templates = load_templates(TEMPLATES)
    scenario = load_scenario(SCENARIO)
    apply_config_c2_to_scenario(scenario)
    assets = load_assets(ROOT / "config" / "assets.yaml")
    assert scenario.actors.pools.c2_ips
    ctx = build_context(scenario, templates["outbound_connection"], SendOptions(), actor_name="attacker")
    body = render_body(templates["outbound_connection"], ctx)
    assert assets["c2"]["default_ip"] in body or ctx["dst_ip"] in body
    assert "C2" in body or ctx["c2_host"] in body


def test_wire_rfc3164_prefix():
    templates = load_templates(TEMPLATES)
    scenario = load_scenario(SCENARIO)
    opts = SendOptions()
    ctx = build_context(scenario, templates["login_success"], opts)
    wire = render_wire(templates["login_success"], ctx)
    assert wire.startswith("<134>")
