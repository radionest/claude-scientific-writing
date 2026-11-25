"""Model lanes for the review ensemble: the declared role→lane map (`lanes.json`) and
the dimension→tier map (registry `tier`, overridden by the pack's `lanes`). Model
identifiers never enter the repo — it is public, the harness assigns models to lanes;
lib carries only the lane vocabulary (`fast`/`strong` tier) and the declared lane
names. Reading the harnesses' own assignment files is adapter code outside lib."""
from __future__ import annotations
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lib.house import load_house
from lib.lint_prose import ConfigError
from lib.review_plan import effective_tiers

_LANES_PATH = Path(__file__).resolve().parents[1] / "lanes.json"
_ROLES = ("writer", "judge")


@dataclass(frozen=True, slots=True)
class Lanes:
    writer: str  # the lane the writer role runs on
    judge: str  # the lane the judgment dimensions run on
    tiers: Mapping[str, str]  # dimension id → fast | strong

    def tier_of(self, name: str) -> str:
        """The tier of a dimension, or the declared lane of a role; an unknown name is
        a ValueError, never a silent `fast`."""
        if name in _ROLES:
            return getattr(self, name)
        if name in self.tiers:
            return self.tiers[name]
        raise ValueError(f"неизвестное имя «{name}»: роль {', '.join(_ROLES)} "
                         f"или id измерения ({', '.join(self.tiers)})")


def load_lanes(doc_path: str | Path | None = None) -> Lanes:
    p = _LANES_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"{p}: {e}") from e
    if not isinstance(data, dict) or set(data) != set(_ROLES) \
            or not all(isinstance(x, str) and x.strip() for x in data.values()):
        raise ConfigError(f"{p}: ожидается объект {{writer, judge}} с непустыми строками")
    house = load_house(doc_path) if doc_path is not None else None
    return Lanes(writer=data["writer"], judge=data["judge"],
                 tiers=effective_tiers(house.lanes if house else None))


def tier_of(name: str, doc_path: str | Path | None = None) -> str:
    return load_lanes(doc_path).tier_of(name)
