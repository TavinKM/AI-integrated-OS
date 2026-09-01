#!/usr/bin/env python3
"""
Run expected-commands tests: needs the docker container to be up

Usage:
  uv run python tests/run_expected_commands.py              # run both modes, then summary
  uv run python tests/run_expected_commands.py --no-graph   # run only no-graph (legacy)
  uv run python tests/run_expected_commands.py tests/expected_commands.txt
"""

import os
import re
import sys
from pathlib import Path

# Project root = parent of tests/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Default workspace for test context (listing, cwd)
os.environ.setdefault("AGENT_WORKDIR", str(PROJECT_ROOT / "workspace"))


def parse_expected_commands(path: Path) -> list[dict]:
    """Parse expected_commands.txt into a list of {query, expected: [str], difficulty: str}."""
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"^\s*---\s*$", text, flags=re.MULTILINE)
    cases = []
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        query = None
        expected = []
        difficulty = "easy"
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("Note:"):
                continue
            if line.startswith("Query:"):
                query = line[6:].strip()
            elif line.startswith("Expected:"):
                expected.append(line[9:].strip())
            elif line.lower().startswith("Difficulty:"):
                d = line[11:].strip().lower()
                if d in ("easy", "hard"):
                    difficulty = d
        if query and expected:
            cases.append({"query": query, "expected": expected, "difficulty": difficulty})
    return cases


def normalize(cmd: str) -> str:
    """Strip and collapse internal whitespace; normalize -n N to -N for head/tail."""
    s = " ".join(cmd.split())
    # head -n 5 / head -n5 / tail -n 5 -> head -5 / tail -5 for comparison
    s = re.sub(r"\bhead\s+-n\s*(\d+)", r"head -\1", s, flags=re.I)
    s = re.sub(r"\btail\s+-n\s*(\d+)", r"tail -\1", s, flags=re.I)
    return s


def run_mode(
    cases: list[dict],
    generator,
    shell,
    use_graph: bool,
) -> tuple[list[int], list[tuple[int, str, str]]]:
    """Run all cases in one mode. Return (passed_indices, failed_list).
    failed_list items are (index, got_command, expected_repr).
    """
    from command_history import get_recent

    passed_indices = []
    failed_list = []  # (i, got, expected_repr)
    for i, case in enumerate(cases, 1):
        query = case["query"]
        expected_list = [normalize(e) for e in case["expected"]]
        shell_context = shell.get_context()
        recent = get_recent(10)
        try:
            command = generator.generate_command(
                query, shell_context=shell_context, recent_history=recent, use_graph=use_graph
            )
        except Exception as e:
            command = f"# Error: {e}"
        cmd_norm = normalize(command.strip()) if command else ""

        if command.startswith("#"):
            match = False
        else:
            match = cmd_norm in expected_list

        if match:
            passed_indices.append(i)
        else:
            failed_list.append((i, command.strip() if command else "", str(case["expected"])))

    return passed_indices, failed_list


def main():
    argv = [a for a in sys.argv[1:] if a != "--no-graph"]
    run_both = "--no-graph" not in sys.argv[1:]
    data_file = Path(argv[0]) if argv else SCRIPT_DIR / "expected_commands.txt"
    if not data_file.is_file():
        print(f"File not found: {data_file}", file=sys.stderr)
        sys.exit(1)

    cases = parse_expected_commands(data_file)
    n = len(cases)

    from main import Neo4jGraphQuery, CommandGenerator
    from shell_session import ShellSession
    import command_history

    workdir = os.getenv("AGENT_WORKDIR")
    shell = ShellSession(cwd=workdir) if workdir else ShellSession()
    graph = Neo4jGraphQuery()
    generator = CommandGenerator(graph, model=os.getenv("LLM_MODEL"))

    if run_both:
        # Run with graph
        print(f"Loaded {n} test cases from {data_file}\n")
        print("=== Running WITH graph ===\n")
        passed_graph, failed_graph = run_mode(cases, generator, shell, use_graph=True)
        failed_graph_set = {i for i, _, _ in failed_graph}
        for i, got, expected_repr in failed_graph:
            c = cases[i - 1]
            short = c["query"][:50] + "..." if len(c["query"]) > 50 else c["query"]
            print(f"FAIL [{i}/{n}] [{c.get('difficulty', 'easy')}] {short}")
            print(f"       Got:      {got}")
            print(f"       Expected: {expected_repr}")

        print(f"\nWith graph: {len(passed_graph)} passed, {len(failed_graph)} failed\n")

        # Run without graph
        print("=== Running WITHOUT graph ===\n")
        passed_nograph, failed_nograph = run_mode(cases, generator, shell, use_graph=False)
        failed_nograph_set = {i for i, _, _ in failed_nograph}
        for i, got, expected_repr in failed_nograph:
            c = cases[i - 1]
            short = c["query"][:50] + "..." if len(c["query"]) > 50 else c["query"]
            print(f"FAIL [{i}/{n}] [{c.get('difficulty', 'easy')}] {short}")
            print(f"       Got:      {got}")
            print(f"       Expected: {expected_repr}")

        print(f"\nWithout graph: {len(passed_nograph)} passed, {len(failed_nograph)} failed\n")

        # Summary: where each failed, and where both failed
        failed_both = failed_graph_set & failed_nograph_set
        failed_graph_only = failed_graph_set - failed_nograph_set
        failed_nograph_only = failed_nograph_set - failed_graph_set

        print("=" * 60)
        print("FAILURE SUMMARY")
        print("=" * 60)
        print("\nFailed in BOTH (with-graph and no-graph):")
        if failed_both:
            for i in sorted(failed_both):
                q = cases[i - 1]["query"]
                short = q[:60] + "..." if len(q) > 60 else q
                print(f"  [{i}] {short}")
            print(f"  Total: {len(failed_both)}")
        else:
            print("  (none)")
        print("\nFailed WITH GRAPH only:")
        if failed_graph_only:
            for i in sorted(failed_graph_only):
                q = cases[i - 1]["query"]
                short = q[:60] + "..." if len(q) > 60 else q
                print(f"  [{i}] {short}")
            print(f"  Total: {len(failed_graph_only)}")
        else:
            print("  (none)")
        print("\nFailed WITHOUT GRAPH only:")
        if failed_nograph_only:
            for i in sorted(failed_nograph_only):
                q = cases[i - 1]["query"]
                short = q[:60] + "..." if len(q) > 60 else q
                print(f"  [{i}] {short}")
            print(f"  Total: {len(failed_nograph_only)}")
        else:
            print("  (none)")
        print()

        total_fail = max(len(failed_graph), len(failed_nograph))
        sys.exit(0 if total_fail == 0 else 1)
    else:
        # old, doesnt run both
        print(f"Loaded {n} test cases from {data_file} (mode: no graph)\n")
        passed, failed_list = run_mode(cases, generator, shell, use_graph=False)
        for i, got, expected_repr in failed_list:
            c = cases[i - 1]
            short = c["query"][:50] + "..." if len(c["query"]) > 50 else c["query"]
            print(f"FAIL [{i}/{n}] [{c.get('difficulty', 'easy')}] {short}")
            print(f"       Got:      {got}")
            print(f"       Expected: {expected_repr}")
        print(f"\nTotal: {len(passed)} passed, {len(failed_list)} failed, {n} cases")
        sys.exit(0 if len(failed_list) == 0 else 1)


if __name__ == "__main__":
    main()
