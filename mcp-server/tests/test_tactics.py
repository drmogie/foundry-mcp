"""Board helpers (distance, movement, hits from chat) and the tools built on them."""

import json

import httpx
import pytest

from foundry_mcp import server, tactics
from foundry_mcp.fga import FgaClient

from tests.test_fga import CLIENTS, Relay

GRID = {"width": 3840, "height": 1920, "grid": {"size": 100, "distance": 5}}


def tok(x, y, w=1, h=1, **more):
    return {"x": x, "y": y, "width": w, "height": h, **more}


# ----- pure helpers -----

def test_distance_counts_gaps_and_diagonals():
    assert tactics.distance_feet(tok(0, 0), tok(100, 0), GRID) == 5
    assert tactics.distance_feet(tok(0, 0), tok(100, 100), GRID) == 5
    assert tactics.distance_feet(tok(0, 0), tok(200, 0), GRID) == 10
    assert tactics.distance_feet(tok(0, 0), tok(200, 300), GRID) == 15
    assert tactics.distance_feet(tok(0, 0, 2, 2), tok(200, 0), GRID) == 5


def test_square_next_to_picks_the_closest_free_square():
    mover, target = tok(2100, 700), tok(2200, 300)
    assert tactics.square_next_to(mover, target, [], GRID) == (2100, 400)
    blocker = tok(2100, 400)
    assert tactics.square_next_to(mover, target, [blocker], GRID) in {(2200, 400), (2000, 400)}


def test_square_next_to_is_none_when_boxed_in():
    target = tok(100, 100)
    ring = [tok(x, y) for x in (0, 100, 200) for y in (0, 100, 200) if (x, y) != (100, 100)]
    assert tactics.square_next_to(tok(1000, 1000), target, ring, GRID) is None


def test_square_away_steps_straight_back_and_stops_when_blocked():
    mover, origin = tok(2100, 400), tok(2200, 300)
    assert tactics.square_away(mover, origin, 10, [], GRID) == (1900, 600)
    assert tactics.square_away(mover, origin, 10, [tok(1900, 600)], GRID) == (2000, 500)
    assert tactics.square_away(tok(0, 0), tok(100, 100), 10, [], GRID) is None


def test_hp_line_and_bloodied():
    assert tactics.hp_line("Foreman", 51, 103)["bloodied"] is True
    assert tactics.hp_line("Foreman", 52, 103)["bloodied"] is False
    assert tactics.hp_line("Foreman", 0, 103)["down"] is True
    assert tactics.hp_line("X", None, None)["hp"] is None


def test_current_combatant_follows_initiative_order():
    combat = {"turn": 1, "combatants": [{"name": "Po", "initiative": 7}, {"name": "Foreman", "initiative": 16}, {"name": "Bob", "initiative": 13}]}
    assert tactics.current_combatant(combat) == "Bob"
    assert tactics.current_combatant({**combat, "turn": 9}) is None


def _row(i, alias, content="", flavor="", rolls=None):
    return {"id": i, "alias": alias, "content": content, "flavor": flavor, "rolls": rolls or []}


CHAT = [
    _row("a1", "Po Tato", flavor="Vicious Glaive - Attack Roll", rolls=[{"total": 26}]),
    _row("a2", "Po Tato", content="<p><em>Hit on Foreman (26 vs AC 18). Rolling damage.</em></p>"),
    _row("a3", "Po Tato", flavor="Vicious Glaive - Damage Roll", rolls=[{"total": 13}]),
    _row("a4", "Po Tato", flavor="Vicious Glaive - Attack Roll", rolls=[{"total": 9}]),
    _row("a5", "Po Tato", content="<p><em>Miss on Foreman (9 vs AC 18). No damage rolled.</em></p>"),
    _row("a6", "Po Tato", flavor="Vicious Glaive - Attack Roll", rolls=[{"total": 30}]),
    _row("a7", "Po Tato", content="Critical Hit on Foreman (30 vs AC 18). Rolling damage."),
    _row("a8", "Po Tato", flavor="Vicious Glaive - Damage Roll", rolls=[{"total": 21}]),
    _row("b1", "Bob", flavor="Shortbow - Attack Roll", rolls=[{"total": 20}]),
    _row("b2", "Bob", content="Hit on Foreman (20 vs AC 18)."),
    _row("b3", "Bob", flavor="Shortbow - Damage Roll", rolls=[{"total": 7}]),
]


def test_read_hits_pairs_each_attack_with_its_damage():
    hits = tactics.read_hits(CHAT, "Po Tato")
    assert [(h["outcome"], h["damage"], h["damageId"]) for h in hits] == [("hit", 13, "a3"), ("miss", None, None), ("critical hit", 21, "a8")]
    assert hits[0]["target"] == "Foreman" and hits[0]["weapon"] == "Vicious Glaive"
    assert [h["damage"] for h in tactics.read_hits(CHAT, "Bob")] == [7]


def test_fresh_rows_and_done_messages():
    assert [r["id"] for r in tactics.fresh_rows(CHAT, "a7")] == ["a8", "b1", "b2", "b3"]
    assert len(tactics.fresh_rows(CHAT, "gone")) == len(CHAT)
    assert tactics.is_done_message(_row("d", None, content="<p>Done!</p>")) is True
    assert tactics.is_done_message(_row("d", None, content="done", rolls=[{"total": 1}])) is False
    assert tactics.is_done_message(_row("d", None, content="not done yet")) is False


LONGSWORD = {"name": "Longsword", "system": {"range": {"value": 5, "units": "ft"}, "properties": [],
                                              "activities": {"x": {"type": "attack", "attack": {"type": {"value": "melee"}}}}}}
GLAIVE = {"name": "Glaive", "system": {"range": {"value": 5, "units": "ft"}, "properties": ["rch"],
                                        "activities": {"x": {"type": "attack", "attack": {"type": {"value": "melee"}}}}}}
SHORTBOW = {"name": "Shortbow", "system": {"range": {"value": 80, "long": 320, "units": "ft"}, "properties": [],
                                            "activities": {"x": {"type": "attack", "attack": {"type": {"value": "ranged"}}}}}}
DAGGER = {"name": "Dagger", "system": {"range": {"value": 20, "long": 60, "units": "ft"}, "properties": ["thr"],
                                        "activities": {"x": {"type": "attack", "attack": {"type": {"value": "melee"}}}}}}


def test_check_attack_reach_and_range():
    assert tactics.check_attack(LONGSWORD, 5)["ok"] is True
    far = tactics.check_attack(LONGSWORD, 10, target="Bob")
    assert far["ok"] is False and "Reach is 5 ft" in far["note"] and "Bob" in far["note"]
    assert tactics.check_attack(GLAIVE, 10)["ok"] is True
    assert tactics.check_attack(GLAIVE, 15)["ok"] is False
    close = tactics.check_attack(SHORTBOW, 5)
    assert close["ok"] and close["disadvantage"]
    assert tactics.check_attack(SHORTBOW, 5, auto_disadvantage=False)["disadvantage"] is False
    assert tactics.check_attack(SHORTBOW, 20)["disadvantage"] is False
    assert tactics.check_attack(SHORTBOW, 100)["disadvantage"] is True
    assert tactics.check_attack(SHORTBOW, 400)["ok"] is False
    thrown = tactics.check_attack(DAGGER, 30)
    assert thrown["ok"] and thrown["kind"] == "thrown" and thrown["disadvantage"]
    assert tactics.check_attack(DAGGER, 100)["ok"] is False


# ----- the tools, against a pretend board -----

SCENE = {"id": "s1", "name": "Arena", "data": {**GRID, "name": "Arena", "tokens": [
    {"_id": "p", "name": "Po Tato", "actorId": "ap", "actorLink": True, **tok(2300, 200)},
    {"_id": "b", "name": "Bob", "actorId": "ab", "actorLink": True, **tok(2100, 700)},
    {"_id": "f", "name": "Foreman", "actorId": "af", "actorLink": False, "delta": {"system": {"attributes": {"hp": {"value": 37}}}}, **tok(2200, 300)},
]}}
ACTORS = {
    "ap": {"name": "Po Tato", "type": "character", "system": {"attributes": {"hp": {"value": 68, "max": 68}}},
           "items": [{"_id": "g1", "name": "Vicious Glaive", "type": "weapon", "system": {**GLAIVE["system"], "damage": {"base": {"types": ["slashing"]}}}}]},
    "ab": {"name": "Bob", "type": "character", "system": {"attributes": {"hp": {"value": 60, "max": 87}}},
           "items": [{"_id": "s1", "name": "Shortbow", "type": "weapon", "system": SHORTBOW["system"]}]},
    "af": {"name": "Foreman", "type": "npc", "system": {"attributes": {"hp": {"value": 103, "max": 103}}},
           "items": [{"_id": "l1", "name": "Longsword", "type": "weapon", "system": LONGSWORD["system"]}]},
}


class Board(Relay):
    def __init__(self):
        super().__init__()
        self.chat = [dict(r) for r in CHAT]
        self.combats = [{"id": "c1", "round": 2, "turn": 1, "started": True, "active": False, "sceneId": None,
                         "combatants": [{"name": "Po", "initiative": 7}, {"name": "Foreman", "initiative": 16}, {"name": "Bob", "initiative": 13}]},
                        {"id": "c2", "round": 1, "turn": 0, "started": True, "active": True, "sceneId": "s1", "combatants": []}]
        self.fail_first = {}

    def __call__(self, request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        q = request.url.params
        if path == "/api/v1/clients":
            return httpx.Response(200, json=CLIENTS)
        self.calls.append((method, path, dict(q), body))
        if self.fail_first.get(path, 0) > 0:
            self.fail_first[path] -= 1
            raise httpx.ReadTimeout("slow")

        def ok(data):
            return httpx.Response(200, json={"ok": True, "data": data})

        if path == "/api/v1/scene":
            return ok(SCENE)
        if path == "/api/v1/document" and method == "GET":
            actor = ACTORS[q["uuid"].rsplit(".", 1)[-1]]
            return ok({"uuid": q["uuid"], "name": actor["name"], "data": {"_id": "x", **actor}})
        if path == "/api/v1/chat" and method == "GET":
            return ok(self.chat[-int(q.get("limit", 20)):])
        if path == "/api/v1/encounters":
            return ok(self.combats)
        if path == "/api/v1/damage":
            return ok({"before": {"value": 90, "max": 103}, "after": {"value": 90 - body["amount"], "max": 103}})
        if path == "/api/v1/rest":
            return ok({"before": {"value": 10}, "after": {"value": 50, "max": 50}})
        return ok({"echo": path})


@pytest.fixture
def board(monkeypatch):
    async def quick(_seconds):
        return None
    monkeypatch.setattr("foundry_mcp.fga.asyncio.sleep", quick)
    b = Board()
    monkeypatch.setattr(server, "_client", FgaClient(base_url="http://relay", api_key="fgat_test", transport=httpx.MockTransport(b)))
    return b


def calls_to(b, path):
    return [c for c in b.calls if c[1] == path]


async def test_distance_tool(board):
    out = json.loads(await server.foundry_distance(from_name="Foreman", to_name="Po Tato"))
    assert out["feet"] == 5 and out["adjacent"] is True
    out = json.loads(await server.foundry_distance(from_name="Bob", to_uuid="Scene.s1.Token.f"))
    assert out["feet"] == 20 and out["adjacent"] is False
    assert "Error" in await server.foundry_distance(from_name="Nobody", to_name="Bob")


async def test_status_shows_hit_points_bloodied_and_whose_turn(board):
    out = json.loads(await server.foundry_status())
    by = {t["name"]: t for t in out["tokens"]}
    assert by["Foreman"]["hp"] == 37 and by["Foreman"]["max"] == 103 and by["Foreman"]["bloodied"] is True
    assert by["Bob"]["hp"] == 60 and by["Bob"]["bloodied"] is False
    assert by["Po Tato"]["bloodied"] is False
    assert {c["id"]: c["up"] for c in out["combats"]} == {"c1": "Bob", "c2": None}
    assert out["chatLatestId"] == "b3"


async def test_move_adjacent_and_move_away(board):
    out = json.loads(await server.foundry_move_adjacent(mover_name="Bob", target_name="Foreman"))
    assert out["moved"] is True and out["to"] == {"x": 2100, "y": 400} and out["feet"] == 15
    sent = calls_to(board, "/api/v1/tokens/move")[-1][3]
    assert sent == {"uuid": "Scene.s1.Token.b", "x": 2100, "y": 400}
    assert "Error" in await server.foundry_move_adjacent(mover_name="Bob", target_name="Foreman", max_feet=10)
    assert json.loads(await server.foundry_move_adjacent(mover_name="Po Tato", target_name="Foreman"))["moved"] is False
    away = json.loads(await server.foundry_move_away(feet=10, mover_name="Po Tato", from_name="Foreman"))
    assert away["moved"] is True and away["feetFrom"] >= 15


async def test_apply_hits_applies_each_damage_roll_once(board):
    out = json.loads(await server.foundry_apply_hits(alias="Po Tato"))
    assert [(a["target"], a["damage"], a["critical"]) for a in out["applied"]] == [("Foreman", 13, False), ("Foreman", 21, True)]
    assert out["total"] == 34
    sent = calls_to(board, "/api/v1/damage")
    assert [c[3]["uuid"] for c in sent] == ["Scene.s1.Token.f"] * 2
    assert sent[0][3]["type"] == "slashing"
    again = json.loads(await server.foundry_apply_hits(alias="Po Tato"))
    assert again["applied"] == [] and len(again["skipped"]) == 2
    assert len(calls_to(board, "/api/v1/damage")) == 2
    since = json.loads(await server.foundry_apply_hits(alias="Bob", since_id="b1"))
    assert [a["damage"] for a in since["applied"]] == [] and "No attacks" in since["note"]


async def test_rest_all_rests_every_token_once(board):
    out = json.loads(await server.foundry_rest_all())
    assert [r["name"] for r in out["rested"]] == ["Po Tato", "Bob", "Foreman"]
    assert [c[3]["uuid"] for c in calls_to(board, "/api/v1/rest")] == ["Actor.ap", "Actor.ab", "Scene.s1.Token.f"]
    only = json.loads(await server.foundry_rest_all(rest_type="short", names=["Bob"]))
    assert [r["name"] for r in only["rested"]] == ["Bob"]
    assert calls_to(board, "/api/v1/rest")[-1][3]["type"] == "short"


async def test_combat_turn_will_not_guess_between_two_combats(board):
    out = await server.foundry_combat_turn(action="nextTurn")
    assert out.startswith("Error") and "c1" in out and "c2" in out
    assert calls_to(board, "/api/v1/combat/control") == []
    await server.foundry_combat_turn(action="nextTurn", combat_id="c1")
    assert calls_to(board, "/api/v1/combat/control")[-1][3]["combatId"] == "c1"


async def test_end_all_combats(board):
    assert "confirm" in await server.foundry_end_all_combats()
    assert calls_to(board, "/api/v1/combat/control") == []
    out = json.loads(await server.foundry_end_all_combats(confirm=True))
    assert out["ended"] == ["c1", "c2"]
    assert all(c[3]["action"] == "end" and c[3]["confirm"] is True for c in calls_to(board, "/api/v1/combat/control"))


async def test_attack_refuses_when_out_of_reach_and_rolls_nothing(board):
    out = json.loads(await server.foundry_attack(actor_uuid="Actor.af", ability_name="Longsword", target_uuid="Scene.s1.Token.b"))
    assert out["applied"] is False and "Nothing was rolled" in out["note"] and out["distance"]["feet"] == 20
    assert calls_to(board, "/api/v1/items/use") == []


async def test_reads_and_safe_writes_retry_once_on_a_timeout(board):
    board.fail_first["/api/v1/scene"] = 1
    assert json.loads(await server.foundry_distance(from_name="Foreman", to_name="Po Tato"))["feet"] == 5
    board.fail_first["/api/v1/tokens/move"] = 1
    out = await server.foundry_move_token(x=1, y=2, uuid="Scene.s1.Token.b")
    assert "Error" not in out and len(calls_to(board, "/api/v1/tokens/move")) == 2
    board.fail_first["/api/v1/damage"] = 1
    out = await server.foundry_apply_damage(amount=3, uuid="Scene.s1.Token.f")
    assert out.startswith("Error") and len(calls_to(board, "/api/v1/damage")) == 1


# ----- waiting for a player -----

async def _wait(board, monkeypatch, feed, **kw):
    """Run the waiter with a fake clock. `feed` is called each poll to add chat rows."""
    client = server.client()
    clock = {"t": 0.0, "n": 0}
    monkeypatch.setattr(client, "_now", lambda: clock["t"])

    async def tick(_seconds):
        clock["t"] += 4.0
        clock["n"] += 1
        feed(board, clock["n"])
    monkeypatch.setattr("foundry_mcp.fga.asyncio.sleep", tick)
    return json.loads(await server.foundry_wait_for_player(**kw))


ATTACK_ROWS = [_row("n1", "Po Tato", flavor="Vicious Glaive - Attack Roll", rolls=[{"total": 22}]),
               _row("n2", "Po Tato", content="Hit on Foreman (22 vs AC 18)."),
               _row("n3", "Po Tato", flavor="Vicious Glaive - Damage Roll", rolls=[{"total": 12}])]


async def test_wait_stops_on_a_done_message(board, monkeypatch):
    def feed(b, n):
        if n == 1:
            b.chat += [dict(r) for r in ATTACK_ROWS] + [_row("n4", None, content="<p>done</p>")]
    out = await _wait(board, monkeypatch, feed, alias="Po Tato", seconds=60, watch_turn=False)
    assert out["reason"] == "done" and out["latestId"] == "n4"
    assert [h["damage"] for h in out["hits"]] == [12]


async def test_wait_stops_when_the_player_goes_quiet(board, monkeypatch):
    def feed(b, n):
        if n == 1:
            b.chat += [dict(r) for r in ATTACK_ROWS]
    out = await _wait(board, monkeypatch, feed, alias="Po Tato", seconds=60, settle=3, watch_turn=False)
    assert out["reason"] == "settled" and out["hits"][0]["outcome"] == "hit"


async def test_wait_stops_when_the_turn_changes(board, monkeypatch):
    def feed(b, n):
        if n == 2:
            b.combats[0]["turn"] = 2
    out = await _wait(board, monkeypatch, feed, alias="Po Tato", seconds=60)
    assert out["reason"] == "turn_changed"


async def test_wait_gives_up_after_the_time(board, monkeypatch):
    out = await _wait(board, monkeypatch, lambda b, n: None, alias="Po Tato", seconds=8, watch_turn=False)
    assert out["reason"] == "timeout" and out["hits"] == []
