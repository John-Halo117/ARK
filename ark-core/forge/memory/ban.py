"""Decayed failure memory for no-repeat behavior."""

from __future__ import annotations

from dataclasses import dataclass

from ..control.decay import decayed_overlap
from ..transform.apply import extract_changed_files, extract_hunk_headers


@dataclass(frozen=True)
class FailureRecord:
    """One failure signature captured after evaluation."""

    error_class: str
    files_touched: tuple[str, ...]
    hunk_fingerprints: tuple[str, ...]
    strategy: str


class BanList:
    """Multi-timescale no-repeat memory."""

    def __init__(self) -> None:
        self._records: list[tuple[int, FailureRecord]] = []

    def add(self, record: FailureRecord, step: int) -> None:
        self._records.append((step, record))

    def is_blocked(
        self, record: FailureRecord, step: int, threshold: float = 0.55
    ) -> bool:
        return self.similarity(record, step) >= threshold

    def similarity(self, record: FailureRecord, step: int) -> float:
        return max(
            (
                self._score(record, old, step - old_step)
                for old_step, old in self._records
            ),
            default=0.0,
        )

    def hot_regions(self, step: int, limit: int = 5) -> tuple[str, ...]:
        scores: dict[str, float] = {}
        for old_step, record in self._records:
            age = max(step - old_step, 0)
            for path in record.files_touched:
                scores[path] = scores.get(path, 0.0) + decayed_overlap(1.0, age, 3.0)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return tuple(path for path, _ in ranked[:limit])

    def repeat_pressure(self, step: int) -> int:
        return sum(1 for old_step, _ in self._records if step - old_step <= 3)

    def export(self) -> list[dict[str, object]]:
        """Serialize the current failure memory."""

        return [
            {
                "step": step,
                "record": {
                    "error_class": record.error_class,
                    "files_touched": list(record.files_touched),
                    "hunk_fingerprints": list(record.hunk_fingerprints),
                    "strategy": record.strategy,
                },
            }
            for step, record in self._records
        ]

    @classmethod
    def from_payload(cls, payload: list[dict[str, object]]) -> "BanList":
        """Rebuild a banlist from serialized records."""

        banlist = cls()
        for item in payload:
            record_payload = item.get("record", {})
            banlist.add(
                FailureRecord(
                    error_class=str(record_payload.get("error_class", "")),
                    files_touched=tuple(record_payload.get("files_touched", [])),
                    hunk_fingerprints=tuple(
                        record_payload.get("hunk_fingerprints", [])
                    ),
                    strategy=str(record_payload.get("strategy", "")),
                ),
                int(item.get("step", 0)),
            )
        return banlist

    def _score(self, record: FailureRecord, old: FailureRecord, age: int) -> float:
        patch = decayed_overlap(
            _jaccard(record.hunk_fingerprints, old.hunk_fingerprints), age, 1.5
        )
        files = decayed_overlap(
            _jaccard(record.files_touched, old.files_touched), age, 3.0
        )
        error = decayed_overlap(float(record.error_class == old.error_class), age, 6.0)
        strategy = decayed_overlap(float(record.strategy == old.strategy), age, 6.0)
        return (0.4 * patch) + (0.25 * files) + (0.2 * error) + (0.15 * strategy)


def failure_record(patch: str, strategy: str, error_class: str) -> FailureRecord:
    """Build a signature from an evaluated patch."""

    return FailureRecord(
        error_class=error_class,
        files_touched=extract_changed_files(patch),
        hunk_fingerprints=extract_hunk_headers(patch),
        strategy=strategy,
    )


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left and not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    return len(left_set & right_set) / len(left_set | right_set)
