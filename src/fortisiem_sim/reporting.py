from __future__ import annotations

import json
from dataclasses import asdict

from .models import EmittedEvent, RunSummary


def record(summary: RunSummary, emitted: EmittedEvent) -> None:
    summary.total += 1
    if emitted.sent:
        summary.sent += 1
    else:
        summary.dry_run += 1
    summary.by_format[emitted.format] = summary.by_format.get(emitted.format, 0) + 1
    phase_key = emitted.phase or "(inline)"
    summary.by_phase[phase_key] = summary.by_phase.get(phase_key, 0) + 1
    summary.by_event[emitted.event_id] = summary.by_event.get(emitted.event_id, 0) + 1


def format_text_line(emitted: EmittedEvent, target: str, port: int) -> str:
    mode = "SPOOF" if emitted.spoof else "NO-SPOOF"
    status = "SENT" if emitted.sent else "DRY"
    return (
        f"[{status}|{mode}] target={target}:{port} event={emitted.event_id} "
        f"phase={emitted.phase or '-'} actor={emitted.actor or '-'} "
        f"packet_src={emitted.packet_src} reporting_ip={emitted.reporting_ip}\n"
        f"{emitted.wire}"
    )


def format_jsonl(emitted: EmittedEvent, target: str, port: int) -> str:
    payload = asdict(emitted)
    payload["target"] = target
    payload["port"] = port
    return json.dumps(payload, ensure_ascii=False)


def print_summary(summary: RunSummary, *, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE (Scapy)"
    print(f"\n=== Resumen [{mode}] ===")
    print(f"  Total eventos : {summary.total}")
    print(f"  Enviados      : {summary.sent}")
    print(f"  Simulados     : {summary.dry_run}")
    if summary.by_phase:
        print("  Por fase:")
        for phase, count in sorted(summary.by_phase.items()):
            print(f"    - {phase}: {count}")
    if summary.by_format:
        print("  Por formato:")
        for fmt, count in sorted(summary.by_format.items()):
            print(f"    - {fmt}: {count}")
