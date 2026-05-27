#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = "待审稿"
DEFAULT_OUTPUT_DIR = "review_outputs"
DEFAULT_RUNS_DIR = "runs"
DEFAULT_PROMPT = "review.md"
DEFAULT_TIMEOUT_MINUTES = 90
DEFAULT_MAX_RETRIES = 1
PAPER_EXTENSIONS = {".pdf", ".tex", ".md"}
RELATED_EXTENSIONS = {".tex", ".md", ".bib", ".bbl", ".sty", ".cls", ".zip"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel_display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def resolve_under_root(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (ROOT / path).resolve()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def safe_name(value: str, max_len: int = 80) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
    value = re.sub(r"\s+", "_", value.strip())
    value = value.strip("._ ")
    if not value:
        value = "paper"
    return value[:max_len].rstrip("._ ") or "paper"


def paper_id(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{safe_name(path.stem)}-{digest}"


def prompt_id(path: Path) -> str:
    return safe_name(path.stem)


def load_config(config_path: str | None) -> dict[str, Any]:
    candidates: list[Path] = []
    if config_path:
        candidates.append(resolve_under_root(config_path))
    else:
        candidates.append(ROOT / "config.json")

    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    return {}


def get_setting(args: argparse.Namespace, config: dict[str, Any], name: str, default: Any) -> Any:
    value = getattr(args, name, None)
    if value is not None:
        return value
    return config.get(name, default)


def find_codex_bin(preferred: str | None = None) -> str:
    if preferred:
        found = shutil.which(preferred) or preferred
        return found

    env_bin = os.environ.get("CODEX_BIN")
    if env_bin:
        return shutil.which(env_bin) or env_bin

    candidates = ["codex.cmd", "codex.exe", "codex"] if os.name == "nt" else ["codex", "codex.cmd", "codex.exe"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found

    raise RuntimeError("Could not find Codex CLI. Install it or set CODEX_BIN.")


def discover_papers(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    papers: list[Path] = []
    for path in input_dir.iterdir():
        if path.is_file() and path.suffix.lower() in PAPER_EXTENSIONS and not path.name.startswith("."):
            papers.append(path.resolve())
    return sorted(papers, key=lambda p: p.name.lower())


def resolve_paper_file(value: str, input_dir: Path) -> Path:
    raw = Path(value)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend([Path.cwd() / raw, ROOT / raw, input_dir / raw])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(f"Paper file not found: {value}")


def related_materials(paper: Path) -> list[Path]:
    related: list[Path] = []
    parent = paper.parent
    if not parent.exists():
        return related

    for candidate in parent.iterdir():
        if candidate.resolve() == paper.resolve():
            continue
        if candidate.is_file() and candidate.stem == paper.stem and candidate.suffix.lower() in RELATED_EXTENSIONS:
            related.append(candidate.resolve())
        elif candidate.is_dir() and candidate.name == paper.stem:
            related.append(candidate.resolve())
    return sorted(related, key=lambda p: p.name.lower())


def reset_dir(path: Path, allowed_parent: Path) -> None:
    path = path.resolve()
    allowed_parent = allowed_parent.resolve()
    if not is_relative_to(path, allowed_parent):
        raise RuntimeError(f"Refusing to reset directory outside run dir: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_input_tree(paper: Path, run_dir: Path, input_dir_name: str) -> Path:
    run_input_dir = run_dir / input_dir_name
    reset_dir(run_input_dir, run_dir)

    copied_paper = run_input_dir / paper.name
    shutil.copy2(paper, copied_paper)

    for item in related_materials(paper):
        destination = run_input_dir / item.name
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    return copied_paper


def render_prompt(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", value, rendered)
    return rendered


def write_status(run_dir: Path, status: dict[str, Any]) -> None:
    status["updated_at"] = now_iso()
    with (run_dir / "status.json").open("w", encoding="utf-8") as fh:
        json.dump(status, fh, ensure_ascii=False, indent=2)


def read_status(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "status.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return None


def validate_output(output_path: Path, expected_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not output_path.exists():
        errors.append(f"Output file was not created: {rel_display(expected_path)}")
        return errors, warnings

    text = output_path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 500:
        errors.append("Output file is unexpectedly short.")

    for marker in ("Part 1", "Part 2", "Part 3", "Part 4", "Part 5"):
        if marker not in text:
            warnings.append(f"Could not find section marker: {marker}")

    if not re.search(r"\b(Reject|Weak Reject|Borderline|Weak Accept|Accept)\b", text):
        warnings.append("Could not find a final review decision.")

    if not re.search(r"page\s+\d+\s*,\s*lines?\s+\d+", text, flags=re.IGNORECASE):
        warnings.append("Could not find page/line citations like 'page X, lines Y-Z'.")

    return errors, warnings


def find_actual_output(run_dir: Path, expected_relative: Path) -> Path:
    expected = run_dir / expected_relative
    if expected.exists():
        return expected

    output_dir = run_dir / expected_relative.parent
    markdowns = sorted(output_dir.glob("*.md")) if output_dir.exists() else []
    if len(markdowns) == 1:
        return markdowns[0]
    return expected


def invoke_codex(
    *,
    codex_bin: str,
    run_dir: Path,
    prompt_text: str,
    model: str | None,
    approval_policy: str | None,
    timeout_minutes: int,
) -> int:
    command = [codex_bin]
    if approval_policy:
        command.extend(["-a", approval_policy])

    command.extend(
        [
        "exec",
        "--skip-git-repo-check",
        "-s",
        "workspace-write",
        "-C",
        str(run_dir),
        "-o",
        str((run_dir / "last_message.md").resolve()),
        "--json",
        ]
    )
    if model:
        command.extend(["-m", model])
    command.append("-")

    with (run_dir / "events.jsonl").open("w", encoding="utf-8") as stdout_fh, (
        run_dir / "stderr.log"
    ).open("w", encoding="utf-8") as stderr_fh:
        try:
            completed = subprocess.run(
                command,
                input=prompt_text,
                text=True,
                encoding="utf-8",
                cwd=run_dir,
                stdout=stdout_fh,
                stderr=stderr_fh,
                timeout=timeout_minutes * 60,
                shell=False,
            )
            return completed.returncode
        except subprocess.TimeoutExpired:
            stderr_fh.write(f"\nTimed out after {timeout_minutes} minutes.\n")
            return 124


def run_one(
    *,
    paper: Path,
    prompt_path: Path,
    root_output_dir: Path,
    runs_dir: Path,
    input_dir_name: str,
    output_dir_name: str,
    codex_bin: str,
    model: str | None,
    approval_policy: str | None,
    timeout_minutes: int,
    max_retries: int,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    base_paper_id = paper_id(paper)
    base_prompt_id = prompt_id(prompt_path)
    run_id = f"{base_paper_id}__{base_prompt_id}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    existing = read_status(run_dir)
    if existing and existing.get("status") == "success" and not force:
        print(f"SKIP    {paper.name} already succeeded -> {existing.get('final_output', '')}")
        return existing

    copied_paper = copy_input_tree(paper, run_dir, input_dir_name)
    expected_relative = Path(output_dir_name) / f"{run_id}.md"
    reset_dir(run_dir / output_dir_name, run_dir)
    expected_output = run_dir / expected_relative

    prompt_template = prompt_path.read_text(encoding="utf-8")
    run_input_file = copied_paper.relative_to(run_dir).as_posix()
    prompt_values = {
        "input_file": run_input_file,
        "input_dir": input_dir_name,
        "output_dir": output_dir_name,
        "output_file": expected_relative.as_posix(),
        "run_dir": rel_display(run_dir),
        "original_file": rel_display(paper),
        "paper_stem": paper.stem,
    }
    prompt_text = render_prompt(prompt_template, prompt_values)
    (run_dir / "prompt.rendered.md").write_text(prompt_text, encoding="utf-8")

    status: dict[str, Any] = {
        "paper": paper.name,
        "paper_path": str(paper.resolve()),
        "paper_id": base_paper_id,
        "prompt_id": base_prompt_id,
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "prompt": str(prompt_path.resolve()),
        "status": "queued",
        "attempts": int(existing.get("attempts", 0)) if existing else 0,
        "expected_output": expected_relative.as_posix(),
        "codex_bin": codex_bin,
        "model": model,
        "approval_policy": approval_policy,
    }

    if dry_run:
        status["status"] = "dry_run"
        status["updated_at"] = now_iso()
        with (run_dir / "dry_run_status.json").open("w", encoding="utf-8") as fh:
            json.dump(status, fh, ensure_ascii=False, indent=2)
        print(f"DRYRUN  {paper.name} -> {rel_display(expected_output)}")
        return status

    total_attempts = max_retries + 1
    for attempt_index in range(total_attempts):
        status["status"] = "running"
        status["attempts"] += 1
        status["started_at"] = now_iso()
        write_status(run_dir, status)

        print(f"RUN     {paper.name} attempt {attempt_index + 1}/{total_attempts}")
        exit_code = invoke_codex(
            codex_bin=codex_bin,
            run_dir=run_dir,
            prompt_text=prompt_text,
            model=model,
            approval_policy=approval_policy,
            timeout_minutes=timeout_minutes,
        )

        actual_output = find_actual_output(run_dir, expected_relative)
        errors, warnings = validate_output(actual_output, expected_output)
        if exit_code != 0:
            errors.insert(0, f"Codex exited with code {exit_code}.")

        status.update(
            {
                "finished_at": now_iso(),
                "exit_code": exit_code,
                "actual_output": rel_display(actual_output),
                "validation_errors": errors,
                "validation_warnings": warnings,
            }
        )

        if not errors:
            root_output_dir.mkdir(parents=True, exist_ok=True)
            final_output = root_output_dir / actual_output.name
            shutil.copy2(actual_output, final_output)
            status["status"] = "success"
            status["final_output"] = str(final_output.resolve())
            write_status(run_dir, status)
            print(f"OK      {paper.name} -> {rel_display(final_output)}")
            return status

        status["status"] = "failed"
        write_status(run_dir, status)
        print(f"FAILED  {paper.name}: {'; '.join(errors)}")

    return status


def load_failed_papers(runs_dir: Path) -> list[Path]:
    papers: list[Path] = []
    if not runs_dir.exists():
        return papers
    for status_file in sorted(runs_dir.glob("*/status.json")):
        status = read_status(status_file.parent)
        if not status or status.get("status") != "failed":
            continue
        paper_path = Path(status.get("paper_path", ""))
        if paper_path.exists():
            papers.append(paper_path.resolve())
    return papers


def print_status(runs_dir: Path) -> None:
    if not runs_dir.exists():
        print("No runs yet.")
        return

    rows = []
    for status_file in sorted(runs_dir.glob("*/status.json")):
        status = read_status(status_file.parent)
        if not status:
            continue
        rows.append(
            (
                status.get("status", "unknown"),
                str(status.get("attempts", "")),
                status.get("paper", ""),
                status.get("final_output") or status.get("actual_output") or "",
            )
        )

    if not rows:
        print("No run status files found.")
        return

    print(f"{'STATUS':<10} {'TRIES':<5} {'PAPER':<40} OUTPUT")
    print("-" * 90)
    for status, attempts, paper, output in rows:
        print(f"{status:<10} {attempts:<5} {paper[:40]:<40} {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch paper review runner for Codex CLI.")
    parser.add_argument("--config", help="Optional JSON config file. Defaults to config.json if present.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_run_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--file", help="Review one specific paper file.")
        target.add_argument("--prompt", help="Prompt template path.")
        target.add_argument("--input-dir", help="Directory containing papers.")
        target.add_argument("--output-dir", help="Directory for final Markdown outputs.")
        target.add_argument("--runs-dir", help="Directory for per-paper run logs.")
        target.add_argument("--model", help="Codex model name. Defaults to Codex CLI config.")
        target.add_argument("--approval-policy", help="Codex approval policy. Defaults to never.")
        target.add_argument("--codex-bin", help="Codex executable. Defaults to auto-detection.")
        target.add_argument("--timeout-minutes", type=int, help="Per-attempt timeout.")
        target.add_argument("--max-retries", type=int, help="Retries after the first failed attempt.")
        target.add_argument("--limit", type=int, help="Maximum number of papers to process.")
        target.add_argument("--force", action="store_true", help="Rerun papers that already succeeded.")
        target.add_argument("--dry-run", action="store_true", help="Prepare run folders without calling Codex.")

    run_parser = subparsers.add_parser("run", help="Run reviews for one paper or all papers.")
    add_common_run_args(run_parser)

    retry_parser = subparsers.add_parser("retry-failed", help="Rerun failed papers from status files.")
    add_common_run_args(retry_parser)

    list_parser = subparsers.add_parser("list", help="List discovered paper files.")
    list_parser.add_argument("--input-dir", help="Directory containing papers.")

    status_parser = subparsers.add_parser("status", help="Show previous run statuses.")
    status_parser.add_argument("--runs-dir", help="Directory for per-paper run logs.")

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    input_dir = resolve_under_root(get_setting(args, config, "input_dir", DEFAULT_INPUT_DIR))
    output_dir = resolve_under_root(get_setting(args, config, "output_dir", DEFAULT_OUTPUT_DIR))
    runs_dir = resolve_under_root(get_setting(args, config, "runs_dir", DEFAULT_RUNS_DIR))

    if args.command == "status":
        print_status(runs_dir)
        return 0

    if args.command == "list":
        papers = discover_papers(input_dir)
        if not papers:
            print(f"No papers found in {rel_display(input_dir)}.")
            return 0
        for paper in papers:
            print(rel_display(paper))
        return 0

    prompt_path = resolve_under_root(get_setting(args, config, "prompt", DEFAULT_PROMPT))
    if not prompt_path.exists():
        print(f"Prompt file not found: {prompt_path}", file=sys.stderr)
        return 2

    codex_bin = find_codex_bin(get_setting(args, config, "codex_bin", None))
    model = get_setting(args, config, "model", None)
    approval_policy = get_setting(args, config, "approval_policy", "never")
    timeout_minutes = int(get_setting(args, config, "timeout_minutes", DEFAULT_TIMEOUT_MINUTES))
    max_retries = int(get_setting(args, config, "max_retries", DEFAULT_MAX_RETRIES))
    limit = get_setting(args, config, "limit", None)

    if args.command == "retry-failed":
        papers = load_failed_papers(runs_dir)
    elif args.file:
        papers = [resolve_paper_file(args.file, input_dir)]
    else:
        papers = discover_papers(input_dir)

    if limit is not None:
        papers = papers[: int(limit)]

    if not papers:
        print("No papers to process.")
        return 0

    runs_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for paper in papers:
        status = run_one(
            paper=paper,
            prompt_path=prompt_path,
            root_output_dir=output_dir,
            runs_dir=runs_dir,
            input_dir_name=DEFAULT_INPUT_DIR,
            output_dir_name=DEFAULT_OUTPUT_DIR,
            codex_bin=codex_bin,
            model=model,
            approval_policy=approval_policy,
            timeout_minutes=timeout_minutes,
            max_retries=max_retries,
            force=bool(args.force or args.command == "retry-failed"),
            dry_run=bool(args.dry_run),
        )
        if status.get("status") not in {"success", "skipped", "dry_run"}:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
