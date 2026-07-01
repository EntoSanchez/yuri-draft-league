"""The battle-prep DEFENSE chart's EFF_MATRIX must match the canonical
Gen 6+ type chart. Guards against silent transcription errors like the
Steel->Electric / Water->Grass / Ground->Grass / Poison->Psychic bugs.

EFF_MATRIX[attacker][defender] is the multiplier x100 (100=neutral,
50=resist, 200=weak, 0=immune).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TYPES = ["Normal", "Fire", "Water", "Grass", "Electric", "Ice", "Fighting",
         "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
         "Dragon", "Dark", "Steel", "Fairy"]

# Only non-neutral matchups (everything else is 100).
CANON = {
    "Normal": {"Rock": 50, "Ghost": 0, "Steel": 50},
    "Fire": {"Fire": 50, "Water": 50, "Grass": 200, "Ice": 200, "Bug": 200, "Rock": 50, "Dragon": 50, "Steel": 200},
    "Water": {"Fire": 200, "Water": 50, "Grass": 50, "Ground": 200, "Rock": 200, "Dragon": 50},
    "Grass": {"Fire": 50, "Water": 200, "Grass": 50, "Poison": 50, "Ground": 200, "Flying": 50, "Bug": 50, "Rock": 200, "Dragon": 50, "Steel": 50},
    "Electric": {"Water": 200, "Electric": 50, "Grass": 50, "Ground": 0, "Flying": 200, "Dragon": 50},
    "Ice": {"Fire": 50, "Water": 50, "Grass": 200, "Ice": 50, "Ground": 200, "Flying": 200, "Dragon": 200, "Steel": 50},
    "Fighting": {"Normal": 200, "Ice": 200, "Poison": 50, "Flying": 50, "Psychic": 50, "Bug": 50, "Rock": 200, "Ghost": 0, "Dark": 200, "Steel": 200, "Fairy": 50},
    "Poison": {"Grass": 200, "Poison": 50, "Ground": 50, "Rock": 50, "Ghost": 50, "Steel": 0, "Fairy": 200},
    "Ground": {"Fire": 200, "Electric": 200, "Grass": 50, "Poison": 200, "Flying": 0, "Bug": 50, "Rock": 200, "Steel": 200},
    "Flying": {"Grass": 200, "Electric": 50, "Fighting": 200, "Bug": 200, "Rock": 50, "Steel": 50},
    "Psychic": {"Fighting": 200, "Poison": 200, "Psychic": 50, "Dark": 0, "Steel": 50},
    "Bug": {"Fire": 50, "Grass": 200, "Fighting": 50, "Poison": 50, "Flying": 50, "Psychic": 200, "Ghost": 50, "Dark": 200, "Steel": 50, "Fairy": 50},
    "Rock": {"Fire": 200, "Ice": 200, "Fighting": 50, "Ground": 50, "Flying": 200, "Bug": 200, "Steel": 50},
    "Ghost": {"Normal": 0, "Psychic": 200, "Ghost": 200, "Dark": 50},
    "Dragon": {"Dragon": 200, "Steel": 50, "Fairy": 0},
    "Dark": {"Fighting": 50, "Psychic": 200, "Ghost": 200, "Dark": 50, "Fairy": 50},
    "Steel": {"Fire": 50, "Water": 50, "Electric": 50, "Ice": 200, "Rock": 200, "Steel": 50, "Fairy": 200},
    "Fairy": {"Fire": 50, "Fighting": 200, "Poison": 50, "Dragon": 200, "Dark": 200, "Steel": 50},
}


def _parse(path):
    src = open(path, encoding="utf-8").read()
    order = [t.strip().strip('"').strip("'")
             for t in re.search(r"const TYPES = \[(.*?)\];", src, re.S).group(1).split(",")
             if t.strip()]
    blk = re.search(r"const EFF_MATRIX = \[(.*?)\];", src, re.S).group(1)
    matrix = [[int(x) for x in re.findall(r"-?\d+", row)]
              for row in re.findall(r"\[([0-9,\s]+)\]", blk)]
    return order, matrix


def test_battle_prep_type_chart_matches_canonical():
    order, matrix = _parse(os.path.join(ROOT, "templates", "battle_prep.html"))
    assert len(matrix) == 18 and all(len(r) == 18 for r in matrix)
    bad = []
    for ai, atk in enumerate(order):
        for di, dfn in enumerate(order):
            correct = CANON.get(atk, {}).get(dfn, 100)
            if matrix[ai][di] != correct:
                bad.append(f"{atk}->{dfn}: {matrix[ai][di]} (want {correct})")
    assert not bad, "type-chart errors:\n" + "\n".join(bad)
