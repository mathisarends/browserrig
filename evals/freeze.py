"""Reproduce the frozen subset from the pinned, unmodified upstream checkout."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "1.2.3"
REVISION = "6473f72db5dcefc97b5725b59e734504edc28a21"
SUBSET = "browserrig-webarena-verified-hard-48-v1"
SEED = SUBSET
DATA = Path(__file__).with_name("data")
QUOTAS = {
    "shopping": 10,
    "shopping_admin": 10,
    "gitlab": 10,
    "reddit": 10,
    "gitlab+reddit": 2,
    "gitlab+wikipedia": 2,
    "map+wikipedia": 2,
    "map+shopping_admin": 1,
    "reddit+shopping": 1,
}


def freeze(checkout: Path, output: Path = DATA) -> None:
    """Select by site, operation and template diversity, without using agent scores."""
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError(f"Expected upstream {REVISION}, got {revision}")
    # Read pinned Git blobs: checkout line endings and local edits cannot change the freeze.
    source = subprocess.check_output(
        [
            "git",
            "-C",
            str(checkout),
            "show",
            f"{REVISION}:assets/dataset/webarena-verified.json",
        ]
    )
    hard_source = subprocess.check_output(
        [
            "git",
            "-C",
            str(checkout),
            "show",
            f"{REVISION}:assets/dataset/subsets/webarena-verified-hard.json",
        ]
    )
    hard_ids = set(json.loads(hard_source)["task_ids"])
    tasks = json.loads(source)
    groups = defaultdict(list)
    for task in tasks:
        if task["task_id"] in hard_ids:
            groups["+".join(sorted(task["sites"]))].append(task)
    selected = []
    for group, count in QUOTAS.items():
        selected.extend(_sample(groups[group], count))
    selected.sort(key=lambda task: task["task_id"])
    payload = (json.dumps(selected, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    manifest = {
        "name": SUBSET,
        "upstream": "https://github.com/ServiceNow/webarena-verified",
        "version": VERSION,
        "revision": REVISION,
        "seed": SEED,
        "selection": "Site quotas; proportional operation quotas by largest remainder; "
        "prefer distinct intent templates; SHA-256(seed:task_id) breaks ties. "
        "No model results or task outcomes are used.",
        "quotas": QUOTAS,
        "task_ids": [task["task_id"] for task in selected],
        "hard_task_ids": sorted(hard_ids),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "hard_source_sha256": hashlib.sha256(hard_source).hexdigest(),
        "tasks_sha256": hashlib.sha256(payload).hexdigest(),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks.json").write_bytes(payload)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help=f"Upstream checkout at {REVISION}")
    args = parser.parse_args()
    freeze(args.checkout)


def _sample(tasks: list[dict], count: int) -> list[dict]:
    operations = defaultdict(list)
    for task in tasks:
        action = task["eval"][0]["expected"]["task_type"]
        operations[action].append(task)
    quotas = {
        action: count * len(items) // len(tasks) for action, items in operations.items()
    }
    remainder = sorted(
        operations,
        key=lambda action: (-(count * len(operations[action]) % len(tasks)), action),
    )
    for action in remainder[: count - sum(quotas.values())]:
        quotas[action] += 1
    selected = []
    for action, quota in sorted(quotas.items()):
        candidates = sorted(
            operations[action],
            key=lambda task: hashlib.sha256(
                f"{SEED}:{task['task_id']}".encode()
            ).hexdigest(),
        )
        templates: Counter[int] = Counter()
        for _ in range(quota):
            task = min(
                candidates,
                key=lambda item, seen=templates: seen[item["intent_template_id"]],
            )
            candidates.remove(task)
            selected.append(task)
            templates[task["intent_template_id"]] += 1
    return selected


if __name__ == "__main__":
    main()
