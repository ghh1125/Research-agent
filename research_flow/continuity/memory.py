from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from research_flow.schema import ResearchMemoryEntry


class ResearchMemoryLog:
    """Append-only research memory for historical judgment review."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: ResearchMemoryEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(), ensure_ascii=False) + "\n")

    def replace_all(self, entries: list[ResearchMemoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(entry.model_dump(), ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def load(self) -> list[ResearchMemoryEntry]:
        if not self.path.exists():
            return []
        entries: list[ResearchMemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(ResearchMemoryEntry.model_validate_json(line))
        return entries

    def context_for(self, entity: str | None, limit: int = 5) -> str:
        entries = self.load()
        if entity:
            entries = [entry for entry in entries if entry.entity == entity]
        lines = []
        for entry in entries[-limit:]:
            outcome = ""
            if entry.status == "resolved":
                outcome = f"; raw_return={entry.raw_return}; alpha_return={entry.alpha_return}; reflection={entry.reflection or ''}"
            lines.append(
                f"{entry.entity or entry.symbols}: {entry.conclusion}; "
                f"assumptions={', '.join(entry.key_assumptions)}; triggers={', '.join(entry.revisit_triggers)}{outcome}"
            )
        return "\n".join(lines)

    def resolve_pending(self, symbol: str, *, current_price: float, benchmark_return: float = 0.0, reflection: str | None = None) -> int:
        entries = self.load()
        resolved = 0
        normalized = symbol.upper()
        updated: list[ResearchMemoryEntry] = []
        for entry in entries:
            symbols = [item.upper() for item in entry.symbols]
            if entry.status != "pending" or normalized not in symbols or not entry.price_context:
                updated.append(entry)
                continue
            try:
                base_price = float(str(entry.price_context).replace(",", ""))
            except ValueError:
                updated.append(entry)
                continue
            if base_price == 0:
                updated.append(entry)
                continue
            raw_return = (current_price - base_price) / base_price
            updated.append(
                entry.model_copy(
                    update={
                        "status": "resolved",
                        "resolved_at": datetime.utcnow().isoformat(),
                        "current_price": current_price,
                        "benchmark_return": benchmark_return,
                        "raw_return": raw_return,
                        "alpha_return": raw_return - benchmark_return,
                        "reflection": reflection or "待人工复盘：已根据最新价格更新收益表现。",
                    }
                )
            )
            resolved += 1
        if resolved:
            self.replace_all(updated)
        return resolved
