from __future__ import annotations

from fortisiem_sim.mail import normalize_smtp, render_email, send_html_email
from fortisiem_sim.models import Scenario, ScenarioActors, ScenarioEmail, ScenarioPhase


def _mini_scenario() -> Scenario:
    return Scenario(
        name="test",
        org_id=1,
        actors=ScenarioActors(),
        phases=[
            ScenarioPhase(
                name="email_phase",
                phase_type="email",
                emails=[
                    ScenarioEmail(
                        template_id="t1",
                        to_address="user@lab.local",
                        actor="default",
                    )
                ],
            )
        ],
    )


def test_send_html_email_dry_run():
    result = send_html_email(
        normalize_smtp({"enabled": False}),
        to_address="a@b.com",
        subject="Test",
        html_body="<p>Hi</p>",
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["sent"] is False


def test_render_email_substitutes():
    sc = _mini_scenario()
    tmpl = {
        "subject": "Alert {{user}}",
        "html_body": "<p>{{hostname}}</p>",
    }
    subj, html = render_email(tmpl, sc, "default")
    assert "Alert" in subj
    assert "<p>" in html
