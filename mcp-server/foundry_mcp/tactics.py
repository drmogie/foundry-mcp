"""Plain helpers for the board: distance in feet, free squares, hit points, and reading attacks out of chat.
No network in here, so it is easy to test."""

from __future__ import annotations

import re
from typing import Any

HIT_NOTE = re.compile(r"(critical hit|critical miss|hit|miss)\s+on\s+(.+?)\s+\((\d+)\s+vs\s+AC\s+(\d+)\)", re.I)
DONE_WORDS = {"done", "end turn", "end", "next", "finished", "end my turn"}


def plain(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def grid_of(scene_data: dict[str, Any]) -> tuple[float, float]:
    """Pixels per square and feet per square."""
    grid = scene_data.get("grid") or {}
    size = float(grid.get("size") or 100)
    unit = float(grid.get("distance") or 5)
    return size, unit


def box(token: dict[str, Any], size: float) -> tuple[float, float, float, float]:
    """A token as squares: left, top, width, height."""
    return (float(token.get("x") or 0) / size, float(token.get("y") or 0) / size,
            float(token.get("width") or 1), float(token.get("height") or 1))


def gap_squares(a: dict[str, Any], b: dict[str, Any], size: float) -> float:
    """Empty squares between the edges of two tokens. 0 means they touch."""
    ax, ay, aw, ah = box(a, size)
    bx, by, bw, bh = box(b, size)
    gx = max(0.0, bx - (ax + aw), ax - (bx + bw))
    gy = max(0.0, by - (ay + ah), ay - (by + bh))
    return max(gx, gy)


def distance_feet(a: dict[str, Any], b: dict[str, Any], scene_data: dict[str, Any]) -> float:
    """Feet between two tokens, counting a diagonal as one square like the 5e basic rule."""
    size, unit = grid_of(scene_data)
    return (gap_squares(a, b, size) + 1) * unit


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _free(spot: tuple[float, float, float, float], others: list[dict[str, Any]], size: float, width: float, height: float) -> bool:
    if spot[0] < 0 or spot[1] < 0 or (spot[0] + spot[2]) * size > width or (spot[1] + spot[3]) * size > height:
        return False
    return not any(_overlap(spot, box(o, size)) for o in others)


def square_next_to(mover: dict[str, Any], target: dict[str, Any], others: list[dict[str, Any]], scene_data: dict[str, Any]) -> tuple[float, float] | None:
    """The free square touching the target that is closest to the mover. Pixels, or None when there is none."""
    size, _ = grid_of(scene_data)
    width, height = float(scene_data.get("width") or 10**9), float(scene_data.get("height") or 10**9)
    mx, my, mw, mh = box(mover, size)
    tx, ty, tw, th = box(target, size)
    best: tuple[float, float, float, float] | None = None
    col = tx - mw
    while col <= tx + tw:
        row = ty - mh
        while row <= ty + th:
            spot = (col, row, mw, mh)
            touching = not _overlap(spot, (tx, ty, tw, th))
            if touching and _free(spot, others, size, width, height):
                key = (max(abs(col - mx), abs(row - my)), (col - mx) ** 2 + (row - my) ** 2)
                if best is None or key < best[2:]:
                    best = (col, row, *key)
            row += 1
        col += 1
    if best is None:
        return None
    return best[0] * size, best[1] * size


def squares_moved(a: tuple[float, float], b: tuple[float, float], size: float) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) / size


def square_away(mover: dict[str, Any], origin: dict[str, Any], feet: float, others: list[dict[str, Any]], scene_data: dict[str, Any]) -> tuple[float, float] | None:
    """A free square as far as `feet` straight away from origin. Falls back to fewer squares when the way is blocked."""
    size, unit = grid_of(scene_data)
    width, height = float(scene_data.get("width") or 10**9), float(scene_data.get("height") or 10**9)
    mx, my, mw, mh = box(mover, size)
    ox, oy, ow, oh = box(origin, size)
    dx, dy = (mx + mw / 2) - (ox + ow / 2), (my + mh / 2) - (oy + oh / 2)
    sx = (1 if dx > 0 else -1 if dx < 0 else 0) if abs(dx) * 2 >= abs(dy) else 0
    sy = (1 if dy > 0 else -1 if dy < 0 else 0) if abs(dy) * 2 >= abs(dx) else 0
    if sx == 0 and sy == 0:
        sy = 1
    steps = int(feet // unit)
    for n in range(steps, 0, -1):
        spot = (mx + sx * n, my + sy * n, mw, mh)
        if _free(spot, others, size, width, height):
            return spot[0] * size, spot[1] * size
    return None


def hp_line(name: str, value: Any, maximum: Any, temp: Any = 0) -> dict[str, Any]:
    try:
        v, m = float(value), float(maximum)
    except (TypeError, ValueError):
        return {"name": name, "hp": None, "max": None, "bloodied": None}
    return {"name": name, "hp": int(v), "max": int(m), "temp": int(temp or 0), "bloodied": v * 2 <= m, "down": v <= 0}


def current_combatant(combat: dict[str, Any]) -> str | None:
    """Who is up. The turn number counts through the fighters from the highest initiative down."""
    fighters = list(combat.get("combatants") or [])
    order = sorted(range(len(fighters)), key=lambda i: (-(fighters[i].get("initiative") if fighters[i].get("initiative") is not None else -10**6), i))
    turn = combat.get("turn")
    if not isinstance(turn, int) or not 0 <= turn < len(order):
        return None
    return fighters[order[turn]].get("name")


def combat_marks(combats: Any) -> list[tuple[Any, Any, Any]]:
    return [(c.get("id"), c.get("round"), c.get("turn")) for c in (combats or []) if c.get("started")]


def fresh_rows(rows: list[dict[str, Any]], since_id: str | None) -> list[dict[str, Any]]:
    ids = [r.get("id") for r in rows]
    if since_id and since_id in ids:
        return rows[ids.index(since_id) + 1:]
    return rows


def read_hits(rows: list[dict[str, Any]], alias: str) -> list[dict[str, Any]]:
    """Every attack by this alias in the rows: the roll, hit or miss, target and damage roll. Damage rows carry an id, so each hit is counted once."""
    who = alias.lower()
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        speaker = str(row.get("alias") or "").lower()
        flavor = str(row.get("flavor") or "")
        rolls = row.get("rolls") or []
        if rolls and re.search(r"attack roll", flavor, re.I):
            if who and who not in speaker:
                current = None
                continue
            current = {"attackId": row.get("id"), "weapon": re.sub(r"\s*-\s*Attack Roll.*", "", flavor, flags=re.I) or None,
                       "attack": (rolls[0] or {}).get("total"), "outcome": None, "target": None, "ac": None, "damage": None, "damageId": None}
            out.append(current)
            continue
        if current is None:
            continue
        if who and who not in speaker:
            continue
        match = HIT_NOTE.search(plain(row.get("content")))
        if match and current["outcome"] is None:
            current.update({"outcome": match.group(1).lower(), "target": match.group(2), "ac": int(match.group(4))})
        if rolls and re.search(r"damage roll", flavor, re.I) and current["damage"] is None:
            current.update({"damage": (rolls[0] or {}).get("total"), "damageId": row.get("id")})
    return out


def is_done_message(row: dict[str, Any]) -> bool:
    return not row.get("rolls") and plain(row.get("content")).lower().strip(" .!") in DONE_WORDS


def _attack_kind(item: dict[str, Any]) -> str:
    system = item.get("system") or {}
    acts = system.get("activities") or {}
    rows = acts.values() if isinstance(acts, dict) else acts
    for act in rows:
        if isinstance(act, dict) and act.get("type") == "attack":
            kind = (((act.get("attack") or {}).get("type") or {}).get("value"))
            if kind in ("melee", "ranged"):
                return kind
    return "ranged" if "ranged" in str(((system.get("type") or {}).get("value") or "")).lower() else "melee"


def check_attack(item: dict[str, Any], feet: float, unit: float = 5, auto_disadvantage: bool = True, target: str = "The target") -> dict[str, Any]:
    """Is the target in reach or range? Also says when the attack has disadvantage. Nothing here rolls."""
    system = item.get("system") or {}
    rng = system.get("range") or {}
    normal, long = rng.get("value"), rng.get("long")
    props = set(system.get("properties") or [])
    kind = _attack_kind(item)
    out: dict[str, Any] = {"ok": True, "disadvantage": False, "kind": kind, "feet": feet, "note": None}
    if kind == "melee":
        reach = float(rng.get("reach") or (unit * 2 if "rch" in props else unit))
        out["reach"] = reach
        if feet <= reach:
            return out
        if "thr" in props and normal and feet <= float(long or normal):
            out["kind"] = "thrown"
            out["disadvantage"] = feet > float(normal)
            out["note"] = f"Thrown from {feet:g} ft." + (" Past normal range, so disadvantage." if out["disadvantage"] else "")
            return out
        out.update(ok=False, note=f"{target} is {feet:g} ft away. Reach is {reach:g} ft. Move first.")
        return out
    if not normal or str(rng.get("units") or "ft") != "ft":
        return out
    normal = float(normal)
    limit = float(long or normal)
    out["range"] = [normal, limit]
    if feet > limit:
        out.update(ok=False, note=f"{target} is {feet:g} ft away. The longest range is {limit:g} ft. Move first.")
        return out
    if feet > normal:
        out.update(disadvantage=True, note=f"{feet:g} ft is past normal range ({normal:g} ft), so disadvantage.")
    elif auto_disadvantage and feet <= unit:
        out.update(disadvantage=True, note=f"{target} is within {unit:g} ft, so a ranged attack has disadvantage.")
    return out
