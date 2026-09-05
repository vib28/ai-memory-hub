"""Queue preference-rule proposals for historical regression-like project entries."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--writer", default="user")
    args = parser.parse_args()
    manager = MemoryManager(args.vault)
    try:
        patterns = manager._patterns()
        pattern = patterns.get("regression")
        if not pattern:
            print({"queued": 0, "reason": "regression pattern not found"})
            return
        queued = []
        for path in manager.vault.root.joinpath("projects").glob("*.md"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "regression" not in line.lower() and "bug" not in line.lower():
                    continue
                subject = path.stem
                preference = f"{pattern.get('preference rule', 'Add a regression check before completion.')} [[{subject}]]"
                result = manager.queue(MemoryCandidate(
                    text=preference, kind="preference", tag="preference", subject=subject, writer=args.writer,
                ))
                queued.append(result)
        print({"queued": len(queued), "results": queued})
    finally:
        manager.close()

if __name__ == "__main__":
    main()
