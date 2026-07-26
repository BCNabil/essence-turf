#!/usr/bin/env python3
"""SUMAPR: deterministic active-memory and prevention gate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

CORE_VERSION = "0.1.0"
MEMORY_PATH = pathlib.Path(".sumapr/memory.json")
AGENTS_PATH = pathlib.Path("AGENTS.md")
WORKFLOW_PATH = pathlib.Path(".github/workflows/sumapr.yml")
HOOK_PATH = pathlib.Path(".githooks/pre-commit")
MARKER = "SUMAPR:BEGIN"
VALID_VERDICTS = {
    "READY",
    "BLOCKED",
    "CONTRADICTION",
    "HUMAN DECISION REQUIRED",
    "RECOVERY MODE",
}


class SumaprError(RuntimeError):
    """Expected, user-actionable SUMAPR error."""


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise SumaprError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def repo_root() -> pathlib.Path:
    return pathlib.Path(run_git("rev-parse", "--show-toplevel")).resolve()


def git_dir(root: pathlib.Path) -> pathlib.Path:
    raw = run_git("-C", str(root), "rev-parse", "--git-dir")
    path = pathlib.Path(raw)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def runtime_dir(root: pathlib.Path) -> pathlib.Path:
    path = git_dir(root) / "sumapr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_memory(root: pathlib.Path) -> dict[str, Any]:
    path = root / MEMORY_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SumaprError(f"missing {MEMORY_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise SumaprError(f"invalid {MEMORY_PATH}: {exc}") from exc
    if not isinstance(value, dict):
        raise SumaprError("memory root must be an object")
    return value


def save_memory(root: pathlib.Path, memory: dict[str, Any]) -> None:
    path = root / MEMORY_PATH
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item.strip().lower() for item in value.split(",") if item.strip()})


def changed_paths(root: pathlib.Path) -> list[str]:
    output = run_git(
        "-C",
        str(root),
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    paths: list[str] = []
    for line in output.splitlines():
        raw = line[3:]
        paths.append(raw.split(" -> ", 1)[-1])
    return sorted(paths)


def recovery_state(root: pathlib.Path) -> list[str]:
    directory = git_dir(root)
    markers = {
        "MERGE_HEAD": "merge",
        "CHERRY_PICK_HEAD": "cherry-pick",
        "REVERT_HEAD": "revert",
        "BISECT_LOG": "bisect",
        "rebase-merge": "rebase",
        "rebase-apply": "rebase",
    }
    return sorted({label for marker, label in markers.items() if (directory / marker).exists()})


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def relevant_rules(
    memory: dict[str, Any], task: str, domains: list[str]
) -> list[dict[str, Any]]:
    task_lower = task.lower()
    selected: list[dict[str, Any]] = []
    for rule in memory.get("rules", []):
        rule_domains = {str(item).lower() for item in rule.get("domains", [])}
        keywords = [str(item).lower() for item in rule.get("when_keywords", [])]
        domain_match = bool(rule_domains.intersection(domains)) or "*" in rule_domains
        keyword_match = bool(keywords) and any(word in task_lower for word in keywords)
        mode = rule.get("mode", "constraint")
        activates_verdict = mode in {"block", "human_decision"}
        selected_by_scope = keyword_match if activates_verdict and keywords else domain_match
        if rule.get("always") or selected_by_scope or keyword_match:
            selected.append(rule)
    return sorted(selected, key=lambda item: str(item.get("id", "")))


def relevant_learnings(
    memory: dict[str, Any], task: str, domains: list[str]
) -> list[dict[str, Any]]:
    task_lower = task.lower()
    result: list[dict[str, Any]] = []
    for item in memory.get("learnings", []):
        item_domains = {str(value).lower() for value in item.get("domains", [])}
        keywords = [str(value).lower() for value in item.get("keywords", [])]
        if item_domains.intersection(domains) or any(word in task_lower for word in keywords):
            result.append(item)
    return sorted(result, key=lambda item: str(item.get("id", "")))


def capsule_text(
    project: dict[str, Any],
    task: str,
    domains: list[str],
    verdict: str,
    reasons: list[str],
    rules: list[dict[str, Any]],
    learnings: list[dict[str, Any]],
) -> str:
    lines = [
        "# SUMAPR action capsule",
        "",
        f"- Project: {project['id']}",
        f"- Task: {task}",
        f"- Domains: {', '.join(domains)}",
        f"- Verdict: {verdict}",
    ]
    if reasons:
        lines.extend(["", "## Reasons", *[f"- {item}" for item in reasons]])
    lines.extend(["", "## Applicable constraints"])
    lines.extend(
        f"- [{item['id']}] {item['statement']} Guard: {item['guard']}"
        for item in rules
    )
    lines.extend(["", "## Validated learnings"])
    if learnings:
        lines.extend(
            f"- [{item['id']}] {item['learning']} Guard: {item['guard']}"
            for item in learnings
        )
    else:
        lines.append("- No validated project learning matched this action.")
    return "\n".join(lines) + "\n"


def choose_verdict(
    root: pathlib.Path,
    memory: dict[str, Any],
    rules: list[dict[str, Any]],
    domains: list[str],
    mutating: bool,
    allow_dirty: bool,
) -> tuple[str, list[str]]:
    project = memory["project"]
    reasons: list[str] = []
    recovery = recovery_state(root)
    if recovery:
        return "RECOVERY MODE", [f"unfinished Git operation: {', '.join(recovery)}"]
    known = {str(item).lower() for item in project["domains"]}
    unknown = sorted(set(domains) - known)
    if unknown:
        return "CONTRADICTION", [f"unknown domain(s): {', '.join(unknown)}"]
    dirty = changed_paths(root)
    if dirty and not allow_dirty:
        return "CONTRADICTION", [
            "working tree already contains changes; isolate or explicitly acknowledge them",
            "existing paths: " + ", ".join(dirty[:20]),
        ]
    branch = run_git("-C", str(root), "branch", "--show-current")
    if mutating and branch in project.get("protected_branches", ["main", "master"]):
        return "BLOCKED", [f"mutating action on protected branch {branch!r}"]
    for rule in rules:
        mode = rule.get("mode", "constraint")
        if mode == "block":
            reasons.append(f"{rule['id']} forbids this scoped action")
            return "BLOCKED", reasons
        if mode == "human_decision":
            reasons.append(f"{rule['id']} requires explicit accountable approval")
            return "HUMAN DECISION REQUIRED", reasons
    return "READY", reasons


def cmd_preflight(args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    project = memory["project"]
    domains = split_csv(args.domains) or ["governance"]
    rules = relevant_rules(memory, args.task, domains)
    learnings = relevant_learnings(memory, args.task, domains)
    verdict, reasons = choose_verdict(
        root, memory, rules, domains, args.mutating, args.allow_dirty
    )
    capsule = capsule_text(project, args.task, domains, verdict, reasons, rules, learnings)
    budget = int(project.get("token_budget", 1200))
    while estimate_tokens(capsule) > budget and learnings:
        learnings.pop()
        capsule = capsule_text(project, args.task, domains, verdict, reasons, rules, learnings)
    if estimate_tokens(capsule) > budget:
        raise SumaprError(
            f"capsule exceeds {budget} tokens; reduce universal rules before proceeding"
        )
    runtime = runtime_dir(root)
    (runtime / "capsule.md").write_text(capsule, encoding="utf-8")
    session = {
        "branch": run_git("-C", str(root), "branch", "--show-current"),
        "created_at": iso(),
        "domains": domains,
        "mutating": bool(args.mutating),
        "project": project["id"],
        "status": "open",
        "task": args.task,
        "verdict": verdict,
    }
    (runtime / "session.json").write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(capsule, end="")
    return 0 if verdict == "READY" else 2


def load_session(root: pathlib.Path) -> tuple[pathlib.Path, dict[str, Any]]:
    path = runtime_dir(root) / "session.json"
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SumaprError("no SUMAPR session; run preflight first") from exc
    return path, session


def session_is_current(
    root: pathlib.Path,
    memory: dict[str, Any],
    session: dict[str, Any],
    allow_closed_success: bool = False,
) -> None:
    allowed_statuses = {"open", "success"} if allow_closed_success else {"open"}
    if session.get("status") not in allowed_statuses or session.get("verdict") != "READY":
        raise SumaprError("SUMAPR session is not current with verdict READY")
    branch = run_git("-C", str(root), "branch", "--show-current")
    if session.get("branch") != branch:
        raise SumaprError("SUMAPR session belongs to a different branch")
    created = dt.datetime.fromisoformat(str(session["created_at"]).replace("Z", "+00:00"))
    ttl = int(memory["project"].get("session_ttl_minutes", 480))
    if now() - created > dt.timedelta(minutes=ttl):
        raise SumaprError("SUMAPR session expired; run preflight again")


def append_incident(
    memory: dict[str, Any],
    domains: list[str],
    symptom: str,
    impact: str,
    source: str,
) -> str:
    timestamp = now()
    identifier = "INC-" + timestamp.strftime("%Y%m%dT%H%M%SZ")
    existing = {str(item.get("id")) for item in memory.get("incidents", [])}
    suffix = 1
    base = identifier
    while identifier in existing:
        suffix += 1
        identifier = f"{base}-{suffix}"
    memory.setdefault("incidents", []).append(
        {
            "created_at": iso(timestamp),
            "domains": domains,
            "id": identifier,
            "impact": impact,
            "source": source,
            "status": "candidate",
            "symptom": symptom,
        }
    )
    return identifier


def cmd_close(args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    path, session = load_session(root)
    session_is_current(root, memory, session)
    if args.status == "success" and not args.validation.strip():
        raise SumaprError("successful closure requires validation evidence")
    incident_id = None
    if args.status != "success" or args.friction:
        incident_id = append_incident(
            memory,
            session["domains"],
            args.friction or f"task closed as {args.status}",
            args.impact or "execution did not close cleanly",
            "close",
        )
        save_memory(root, memory)
    session.update(
        {
            "closed_at": iso(),
            "status": args.status,
            "validation": args.validation.strip(),
        }
    )
    path.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"SUMAPR CLOSED: {args.status.upper()}")
    if incident_id:
        print(f"CANDIDATE INCIDENT: {incident_id}")
    return 0 if args.status == "success" else 2


def cmd_incident(args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    domains = split_csv(args.domains) or ["governance"]
    identifier = append_incident(memory, domains, args.symptom, args.impact, "manual")
    save_memory(root, memory)
    print(identifier)
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    incident = next(
        (item for item in memory.get("incidents", []) if item.get("id") == args.incident_id),
        None,
    )
    if not incident:
        raise SumaprError(f"unknown incident {args.incident_id}")
    if incident.get("status") != "candidate":
        raise SumaprError("only candidate incidents can be promoted")
    learning_id = args.incident_id.replace("INC-", "LRN-", 1)
    memory.setdefault("learnings", []).append(
        {
            "cause": args.cause,
            "domains": incident["domains"],
            "evidence": args.evidence,
            "guard": args.guard,
            "id": learning_id,
            "incident_id": args.incident_id,
            "keywords": split_csv(args.keywords),
            "learning": args.fix,
            "promoted_at": iso(),
        }
    )
    incident["status"] = "promoted"
    incident["learning_id"] = learning_id
    save_memory(root, memory)
    print(learning_id)
    return 0


def duplicate_ids(items: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        identifier = str(item.get("id", ""))
        if not identifier or identifier in seen:
            duplicates.add(identifier or "<missing>")
        seen.add(identifier)
    return sorted(duplicates)


def cmd_check(_args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    errors: list[str] = []
    if memory.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if memory.get("core_version") != CORE_VERSION:
        errors.append(f"core_version must be {CORE_VERSION}")
    project = memory.get("project")
    if not isinstance(project, dict) or not project.get("id") or not project.get("domains"):
        errors.append("project.id and project.domains are required")
    for key in ("rules", "incidents", "learnings"):
        if not isinstance(memory.get(key), list):
            errors.append(f"{key} must be an array")
            continue
        duplicates = duplicate_ids(memory[key])
        if duplicates:
            errors.append(f"duplicate or missing {key} ids: {', '.join(duplicates)}")
    for item in memory.get("learnings", []):
        for key in ("cause", "evidence", "guard", "learning", "incident_id"):
            if not str(item.get(key, "")).strip():
                errors.append(f"{item.get('id', '<learning>')} missing {key}")
    required = {
        AGENTS_PATH: MARKER,
        WORKFLOW_PATH: "tools/sumapr.py check",
        HOOK_PATH: "tools/sumapr.py gate",
    }
    for path, needle in required.items():
        full = root / path
        if not full.exists():
            errors.append(f"missing {path}")
        elif needle not in full.read_text(encoding="utf-8"):
            errors.append(f"{path} missing required SUMAPR marker")
    if errors:
        print("SUMAPR CHECK: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 2
    print(
        "SUMAPR CHECK: READY "
        f"({project['id']}, core {CORE_VERSION}, "
        f"{len(memory['rules'])} rules, {len(memory['learnings'])} learnings)"
    )
    return 0


def cmd_install(_args: argparse.Namespace) -> int:
    root = repo_root()
    hook = root / HOOK_PATH
    if not hook.exists():
        raise SumaprError(f"missing {HOOK_PATH}")
    hook.chmod(hook.stat().st_mode | 0o111)
    run_git("-C", str(root), "config", "core.hooksPath", ".githooks")
    print("SUMAPR hook installed for this clone.")
    return 0


def cmd_gate(_args: argparse.Namespace) -> int:
    root = repo_root()
    memory = load_memory(root)
    _path, session = load_session(root)
    session_is_current(root, memory, session, allow_closed_success=True)
    return cmd_check(argparse.Namespace())


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="sumapr")
    commands = result.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--task", required=True)
    preflight.add_argument("--domains")
    preflight.add_argument("--mutating", action="store_true")
    preflight.add_argument("--allow-dirty", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    close = commands.add_parser("close")
    close.add_argument("--status", choices=("success", "failed", "blocked"), required=True)
    close.add_argument("--validation", default="")
    close.add_argument("--friction", default="")
    close.add_argument("--impact", default="")
    close.set_defaults(func=cmd_close)

    incident = commands.add_parser("incident")
    incident.add_argument("--domains")
    incident.add_argument("--symptom", required=True)
    incident.add_argument("--impact", required=True)
    incident.set_defaults(func=cmd_incident)

    learn = commands.add_parser("learn")
    learn.add_argument("--incident-id", required=True)
    learn.add_argument("--cause", required=True)
    learn.add_argument("--fix", required=True)
    learn.add_argument("--evidence", required=True)
    learn.add_argument("--guard", required=True)
    learn.add_argument("--keywords", default="")
    learn.set_defaults(func=cmd_learn)

    check = commands.add_parser("check")
    check.set_defaults(func=cmd_check)
    install = commands.add_parser("install")
    install.set_defaults(func=cmd_install)
    gate = commands.add_parser("gate")
    gate.set_defaults(func=cmd_gate)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except SumaprError as exc:
        print(f"SUMAPR BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
