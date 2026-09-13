#!/usr/bin/env python3
"""Read-only dashboard and saved-settings preview for HostBackup."""
import argparse
import calendar
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

spec = importlib.util.spec_from_file_location("hostbackup_recovery", Path(__file__).with_name("hostbackup-recovery.py"))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def read_json(path, fallback=None):
    try:
        return json.loads(recovery.read_control(Path(path)))
    except (OSError, ValueError):
        return fallback


def next_run(config, now=None):
    if not config.get("schedule_enabled"):
        return None
    now = now or datetime.now()
    value = config.get("schedule_time", "02:00")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        return None
    hour, minute = map(int, value.split(":"))
    mode = config.get("schedule_mode", "daily")
    for days in range(400):
        candidate = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            continue
        if mode == "weekly" and str((candidate.weekday() + 1) % 7) not in config.get("schedule_weekdays", []):
            continue
        if mode == "monthly":
            months = config.get("schedule_months", [])
            if "*" not in months and str(candidate.month) not in months:
                continue
            last = calendar.monthrange(candidate.year, candidate.month)[1]
            selected = {min(int(x), last) for x in config.get("schedule_monthdays", []) if str(x).isdigit() and 1 <= int(x) <= 31}
            if candidate.day not in selected:
                continue
        if mode not in ("daily", "weekly", "monthly"):
            return None
        # Use the host's timezone rules for the candidate date, not today's fixed UTC offset.
        timestamp = candidate.timestamp()
        if datetime.fromtimestamp(timestamp) != candidate:
            continue
        return {"epoch": int(timestamp), "local": datetime.fromtimestamp(timestamp).astimezone().isoformat(),
                "note": "Geplanter Termin; Sommerzeit und Systemstillstand koennen die Ausfuehrung beeinflussen."}
    return None


def tasks(state):
    result = []
    for file in (state / "tasks").glob("*.log.json"):
        if not re.fullmatch(r"(?:backup|restore|export|import|verify)-[A-Za-z0-9._-]+\.log\.json", file.name):
            continue
        data = read_json(file)
        if not isinstance(data, dict):
            continue
        name = file.name[:-5]
        item = {key: data.get(key) for key in ("state", "phase", "updated_at", "exit_status")}
        item["task"] = name
        item["mtime"] = data.get("updated_at", 0)
        if item["state"] in ("running", "starting", "queued"):
            try:
                pid = int(data.get("pid", 0))
                text = Path(f"/proc/{pid}/stat").read_text()
                ticks = text[text.rfind(")") + 2:].split()[19]
                live = pid > 1 and ticks == str(data.get("process_start_ticks"))
            except (OSError, ValueError, IndexError):
                live = False
            if item["state"] == "queued" and not data.get("pid"):
                updated = data.get("updated_at", 0)
                live = isinstance(updated, (int, float)) and datetime.now().timestamp() - updated < 300
            if not live:
                item["state"] = "interrupted"
                item["phase"] = "process_missing"
        result.append(item)
    return sorted(result, key=lambda x: (x["mtime"] or 0, x["task"]), reverse=True)[:200]


def overview(config, root, state):
    history = tasks(state)
    backups = []
    target = {"configured": bool(config.get("backup_root")), "path": config.get("backup_root", ""),
              "available_mb": None, "readable": False}
    if root and root.is_dir() and not root.is_symlink():
        target["available_mb"] = shutil.disk_usage(root).free // 1048576
        target["readable"] = True
        for folder in root.iterdir():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", folder.name) or not folder.is_dir() or folder.is_symlink():
                continue
            manifest = read_json(folder / "manifest.json")
            validation = read_json(folder / "backup-validation.json", {})
            if not isinstance(validation, dict):
                validation = {}
            if isinstance(manifest, dict):
                backups.append({"backup_id": folder.name, "status": manifest.get("status"),
                                "finished_at": manifest.get("finished_at"), "validation": validation.get("status")})
    good = [b for b in backups if (b["status"], b["validation"]) in (("complete", "ok"), ("complete_with_warnings", "warning"))]
    good.sort(key=lambda b: (b.get("finished_at") or "", b["backup_id"]), reverse=True)
    active = next((t["task"] for t in history if t["state"] in ("running", "starting", "queued")), None)
    failed = next((t for t in history if t["state"] in ("failed", "interrupted", "stopped")), None)
    pending = [d.name for d in (state / "restart-journals").iterdir()
               if d.is_dir() and not d.is_symlink() and (d / "journal.json").is_file()] if (state / "restart-journals").is_dir() else []
    return {"tasks": history, "active_task": active, "last_success": good[0] if good else None,
            "last_failure": failed, "next_run": next_run(config), "target": target,
            "pending_service_recovery": len(pending), "saved_config": True}


def preview(config, root, excludes, reference, preflight):
    mounts = subprocess.run(["findmnt", "-J", "-l", "-o", "TARGET,SOURCE,FSTYPE"], capture_output=True, text=True, check=True)
    rows = json.loads(mounts.stdout).get("filesystems", [])
    volumes = []
    for item in rows:
        target = item.get("target", "")
        if not target.startswith("/"):
            continue
        rule = next((r for r in excludes if recovery.glob_matches(target.lstrip("/"), r, True)), None)
        volumes.append({"path": target, "source": item.get("source"), "fstype": item.get("fstype"),
                        "included": rule is None, "reason": f"Ausschluss: {rule}" if rule else "Eingeschlossen; Unterverzeichnisse koennen eigene Ausschluesse haben."})
    return {"saved_config": True, "backup_root": str(root), "backup_mode": config.get("backup_mode", "full"),
            "metadata_mode": config.get("metadata_mode", "native-strict"), "reference_id": reference or None,
            "full_baseline_required": config.get("backup_mode") != "snapshot" or not reference,
            "excludes": excludes, "source_volumes": volumes, "preflight": preflight,
            "available_mb": preflight.get("available_mb"), "baseline_estimate_mb": preflight.get("baseline_estimate_mb") or None,
            "note": "Vorschau der gespeicherten Einstellungen. Keine Dateien werden kopiert oder Dienste gestoppt."}


def check_settings(mode, metadata, enabled, schedule_mode, clock, weekdays, monthdays, months):
    if mode not in ("full", "snapshot") or metadata not in ("native-strict", "network-compatible", "fake-super", "portable-archive"):
        raise ValueError("Ungueltiger Backup-Modus oder Metadaten-Profil.")
    if mode == "snapshot" and metadata == "portable-archive":
        raise ValueError("Portable Archive unterstuetzt keine inkrementellen Snapshots. Bitte Vollbackup waehlen.")
    if enabled != "true":
        return
    if schedule_mode not in ("daily", "weekly", "monthly") or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
        raise ValueError("Gueltigen Zeitplan und Uhrzeit angeben.")
    def selected(value, low, high):
        return bool(value) and all(x.isdigit() and low <= int(x) <= high for x in value.split(","))
    if schedule_mode == "weekly" and not selected(weekdays, 0, 6):
        raise ValueError("Mindestens einen gueltigen Wochentag auswaehlen.")
    if schedule_mode == "monthly" and (not selected(monthdays, 1, 31) or months != "*" and not selected(months, 1, 12)):
        raise ValueError("Mindestens einen Monatstag und einen Monat (oder alle Monate) auswaehlen.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("overview", "preview", "check-settings"))
    parser.add_argument("--config")
    parser.add_argument("--root")
    parser.add_argument("--state")
    parser.add_argument("--reference", default="")
    parser.add_argument("settings", nargs="*")
    args = parser.parse_args()
    if args.action == "check-settings":
        check_settings(*args.settings)
        return
    config = read_json(args.config)
    if not isinstance(config, dict):
        raise ValueError("Gespeicherte Einstellungen sind nicht lesbar.")
    if args.action == "overview":
        result = overview(config, Path(args.root) if args.root else None, Path(args.state))
    else:
        data = json.load(sys.stdin)
        result = preview(config, Path(args.root), data["excludes"], args.reference, data["preflight"])
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(18)
