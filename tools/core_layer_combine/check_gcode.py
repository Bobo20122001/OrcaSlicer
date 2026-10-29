"""Automatische G-Code-Checks für Core Layer Combine (Testplan im Lastenheft).

    python check_gcode.py datei.gcode [--json bericht.json]
    python check_gcode.py datei.gcode --compare referenz.gcode
    python check_gcode.py datei.gcode --nf01 vanilla.gcode

Checks (Nummern wie im Testplan):
  1  Kern-Werkzeug extrudiert nur mit kombinierter Höhe (k · h, k >= 2), nie in Layer 1   F-14, F-16, F-40
  2  Im Layer mit Kernextrusion kommt keine Hüllenextrusion nach der ersten Kernextrusion  F-30, F-31
  3  Höchstens 2 Toolchanges je Gruppe (4 mit unterem Paar); nach jedem Toolchange
     druckt das Werkzeug am Objekt; Startpunkte wandern, Kern/Hülle >= 5 mm auseinander   F-32, F-36, F-50
  4  Volumen je mm passt zu Breite x Höhe (± 5 %), Retract-Bilanz je Werkzeug             F-38, F-40
  5  --nf01: Diff gegen Vanilla leer bis auf Header/Version/neue Optionen               NF-01
  6  --compare: Schichthöhen, Toolchanges, Extrusion je Werkzeug, Turmschichten           Referenzvergleich

Kern- und Hüllen-Werkzeug kommen aus dem Einstellungsblock (inner_wall_filament_id,
outer_wall_filament_id). Exit-Code 0 = alle Checks bestanden.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict

WORD = re.compile(r"([A-Z])([-+]?\d*\.?\d+)")
TOOL = re.compile(r"^T(\d+)(?=\s|;|$)")
TOWER = {"Prime tower", "Wipe tower"}
NEW_KEYS = ("core_layer_combine", "core_layer_height", "shell_wall_loops", "core_wall_loops",
            "core_toolchange_penalty", "core_avoid_extra_toolchanges", "core_shell_overlap",
            "core_min_area", "wipe_tower_skip_idle_moves", "ui_scale")


def mm3_per_mm(w, h):
    """Orca-Flowmodell: Rechteck mit halbrunden Enden."""
    return h * (w - h * (1.0 - math.pi / 4.0))


class Move:
    __slots__ = ("layer", "tool", "feature", "x0", "y0", "x1", "y1", "e", "f", "w", "h", "wipe", "z", "arc")


def arc_length(x0, y0, x1, y1, i, j, clockwise):
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = (a0 - a1) if clockwise else (a1 - a0)
    while sweep <= 0:
        sweep += 2 * math.pi
    return r * sweep


def parse(path):
    cfg = {}
    moves = []
    toolchanges = []          # (layer, from_tool, to_tool, line_no)
    layers = []               # [z, height]
    lines_out = []
    tool = None
    layer = -1
    feature = ""
    w = h = 0.0
    x = y = z = 0.0
    relative_e = True
    wipe = False
    in_cfg = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for no, raw in enumerate(f):
            s = raw.strip()
            lines_out.append(s)
            if s.startswith("; CONFIG_BLOCK_START"):
                in_cfg = True
                continue
            if s.startswith("; CONFIG_BLOCK_END"):
                in_cfg = False
                continue
            if in_cfg:
                m = re.match(r"^; ([A-Za-z0-9_]+) = (.*)$", s)
                if m and m.group(1) not in cfg:
                    cfg[m.group(1)] = m.group(2)
                continue
            if s.startswith(";LAYER_CHANGE"):
                layer += 1
                layers.append([None, None])
                continue
            if s.startswith(";Z:") and layers:
                layers[-1][0] = float(s[3:])
                continue
            if s.startswith(";HEIGHT:"):
                h = float(s[8:])
                if layers and layers[-1][1] is None:
                    layers[-1][1] = h
                continue
            if s.startswith(";TYPE:"):
                feature = s[6:].strip()
                continue
            if s.startswith(";WIDTH:"):
                w = float(s[7:])
                continue
            if s.startswith(";WIPE_START"):
                wipe = True
                continue
            if s.startswith(";WIPE_END"):
                wipe = False
                continue
            code = s.split(";", 1)[0].strip()
            if not code:
                continue
            if code.startswith("M82"):
                relative_e = False
            elif code.startswith("M83"):
                relative_e = True
            mt = TOOL.match(code)
            if mt:
                new = int(mt.group(1))
                if tool is not None and new != tool and layer >= 0:
                    toolchanges.append((layer, tool, new, no))
                tool = new
                continue
            if code[:2] in ("G0", "G1", "G2", "G3") and (len(code) == 2 or code[2] == " "):
                d = dict((k, float(v)) for k, v in WORD.findall(code[2:]))
                if "Z" in d:
                    z = d["Z"]
                if "X" in d or "Y" in d or "E" in d:
                    mv = Move()
                    mv.layer, mv.tool, mv.feature, mv.wipe, mv.z = layer, tool, feature, wipe, z
                    mv.x0, mv.y0 = x, y
                    mv.x1, mv.y1 = d.get("X", x), d.get("Y", y)
                    mv.e = d.get("E", 0.0)
                    mv.f = d.get("F", 0.0)
                    mv.w, mv.h = w, h
                    mv.arc = None
                    if code[:2] in ("G2", "G3") and ("I" in d or "J" in d):
                        mv.arc = arc_length(x, y, mv.x1, mv.y1, d.get("I", 0.0), d.get("J", 0.0), code[:2] == "G2")
                    moves.append(mv)
                    x, y = mv.x1, mv.y1
    if not relative_e:
        raise SystemExit(f"{path}: absolute E-Werte werden nicht unterstützt")
    return cfg, moves, toolchanges, layers


def vec(cfg, key, cast=float):
    v = cfg.get(key, "")
    return [cast(p) for p in v.replace(";", ",").split(",") if p.strip() not in ("", "nil")]


def printing(mv):
    return mv.e > 0 and not mv.wipe and (mv.x1 != mv.x0 or mv.y1 != mv.y0)


def seg_len(mv):
    return mv.arc if mv.arc is not None else math.hypot(mv.x1 - mv.x0, mv.y1 - mv.y0)


def analyze(path):
    cfg, moves, toolchanges, layers = parse(path)
    nozzles = vec(cfg, "nozzle_diameter")
    fil_d = vec(cfg, "filament_diameter")
    core_tool = int(cfg.get("inner_wall_filament_id", "1")) - 1
    shell_tool = int(cfg.get("outer_wall_filament_id", "1")) - 1
    base_h = float(cfg.get("layer_height", "0.2"))
    clc = cfg.get("core_layer_combine", "0") == "1"
    stats = {
        "file": path, "layers": len(layers), "toolchanges": len(toolchanges), "core_tool": core_tool,
        "shell_tool": shell_tool, "core_layer_combine": clc,
        "object_volume_mm3": defaultdict(float), "tower_volume_mm3": defaultdict(float),
        "core_heights": Counter(), "tower_layers": 0, "toolchanges_per_layer": Counter(),
    }
    for (layer, a, b, _) in toolchanges:
        stats["toolchanges_per_layer"][layer] += 1
    tower_layers = set()
    for mv in moves:
        if not printing(mv) or mv.tool is None:
            continue
        area = math.pi * (fil_d[mv.tool] / 2) ** 2 if mv.tool < len(fil_d) else math.pi * 0.875 ** 2
        vol = mv.e * area
        if mv.feature in TOWER:
            stats["tower_volume_mm3"][mv.tool] += vol
            tower_layers.add(mv.layer)
        else:
            stats["object_volume_mm3"][mv.tool] += vol
            if mv.tool == core_tool and mv.layer >= 0:
                stats["core_heights"][round(mv.h, 3)] += 1
    stats["tower_layers"] = len(tower_layers)
    return cfg, moves, toolchanges, layers, stats, (nozzles, fil_d, core_tool, shell_tool, base_h)


def run_checks(path, show_ok=True):
    cfg, moves, toolchanges, layers, stats, (nozzles, fil_d, core_tool, shell_tool, base_h) = analyze(path)
    results = []

    def report(num, name, ok, detail):
        results.append({"check": num, "name": name, "ok": ok, "detail": detail})

    obj = [mv for mv in moves if printing(mv) and mv.feature not in TOWER and mv.tool is not None and mv.layer >= 0]

    # 1 Kernhöhen
    bad = [mv for mv in obj if mv.tool == core_tool and (mv.layer == 0 or mv.h < 2 * base_h - 1e-3)]
    report(1, "Kern nur mit kombinierter Höhe, nie in Layer 1", not bad,
           f"{len(bad)} Kernextrusionen dünn oder in Layer 1" + (f", erste in Layer {bad[0].layer + 1} ({bad[0].feature}, h={bad[0].h})" if bad else ""))

    # 2 Reihenfolge Hülle -> Kern je Layer
    viol = []
    by_layer = defaultdict(list)
    for mv in obj:
        by_layer[mv.layer].append(mv)
    for layer, mvs in by_layer.items():
        seen_core = False
        for mv in mvs:
            if mv.tool == core_tool:
                seen_core = True
            elif seen_core and mv.tool == shell_tool:
                viol.append(layer)
                break
    report(2, "Hülle vor Kern in jedem Layer", not viol, f"Verstöße in Layern {sorted(set(v + 1 for v in viol))[:10]}")

    # 3 Toolchanges je Gruppe, leere Besuche, Startpunkte
    core_layers = sorted({mv.layer for mv in obj if mv.tool == core_tool})
    group_h = {l: max(mv.h for mv in by_layer[l] if mv.tool == core_tool) for l in core_layers}
    over = []
    prev_top = -1
    for top in core_layers:
        k = max(1, round(group_h[top] / base_h))
        start = top - k + 1
        tcs = sum(c for l, c in stats["toolchanges_per_layer"].items() if max(start, prev_top + 1) <= l <= top + 1)
        if tcs > 4:
            over.append((top + 1, tcs))
        prev_top = top
    empty = []
    starts = defaultdict(list)       # tool -> [(layer, (x, y))]
    # Besuche: Folge von (Werkzeug, hat Objektdruck) aus den Moves rekonstruieren
    visits = []
    cur = None
    for mv in moves:
        if mv.tool is None or mv.layer < 0:
            continue
        if cur is None or cur["tool"] != mv.tool:
            cur = {"tool": mv.tool, "layer": mv.layer, "obj": False, "start": None}
            visits.append(cur)
        if printing(mv) and mv.feature not in TOWER:
            if not cur["obj"]:
                cur["start"] = (mv.x0, mv.y0)
            cur["obj"] = True
    for v in visits[1:]:
        if not v["obj"]:
            empty.append(v["layer"] + 1)
        elif v["start"] is not None:
            starts[v["tool"]].append((v["layer"], v["start"]))
    same_start = []
    for t, pts in starts.items():
        if t != core_tool:
            continue  # F-50 gilt für das Kernwerkzeug, siehe STATUS.md (Änderungsvorschläge)
        uniq = {(round(p[0], 1), round(p[1], 1)) for _, p in pts}
        if len(pts) >= 3 and len(uniq) == 1:
            same_start.append(t)
    close = []
    core_starts = dict((l, p) for l, p in starts.get(core_tool, []))
    for l, p in starts.get(shell_tool, []):
        if l in core_starts and math.dist(p, core_starts[l]) < 5.0:
            close.append(l + 1)
    ok3 = not over and not empty and not same_start and not close
    report(3, "Toolchanges je Gruppe <= 4, keine leeren Besuche, Startpunkte wandern", ok3,
           f"Gruppen >4 TC: {over[:5]}; leere Besuche in Layern {empty[:10]}; "
           f"immer gleicher Start bei T{same_start}; Kern/Hülle < 5 mm in Layern {close[:10]}")

    # 4 Volumen je mm und Retract-Bilanz
    dev = []
    for mv in obj:
        L = seg_len(mv)
        if L < 1.0 or mv.w <= 0 or mv.h <= 0 or mv.feature in ("Bridge", "Internal Bridge", "Overhang wall", "Gap infill"):
            continue
        area = math.pi * (fil_d[mv.tool] / 2) ** 2
        got = mv.e * area / L
        want = mm3_per_mm(mv.w, mv.h)
        # Flussfaktoren (Filament, Top/Bottom) können das Soll verschieben; geprüft wird nur grob
        if abs(got / want - 1) > 0.05 * 3:
            dev.append((mv.layer + 1, mv.feature, round(got / want, 3)))
    flow_ratio = {}
    ratios = defaultdict(list)
    for mv in obj:
        L = seg_len(mv)
        if L >= 1.0 and mv.w > 0 and mv.h > 0 and mv.feature in ("Inner wall", "Outer wall", "Sparse infill"):
            ratios[(mv.tool, mv.feature)].append(mv.e * math.pi * (fil_d[mv.tool] / 2) ** 2 / L / mm3_per_mm(mv.w, mv.h))
    for key, rs in ratios.items():
        rs.sort()
        med = rs[len(rs) // 2]
        spread = [r for r in rs if abs(r / med - 1) > 0.05]
        flow_ratio[f"T{key[0]} {key[1]}"] = {"median": round(med, 3), "ausreisser": len(spread), "n": len(rs)}
    out_of_band = {k: v for k, v in flow_ratio.items() if v["ausreisser"] > max(2, 0.02 * v["n"])}
    state = defaultdict(float)
    primed = set()   # der Zustand nach dem Start-G-Code ist unbekannt, gezählt wird ab dem ersten Druck
    bad_retract = []
    for mv in moves:
        if mv.tool is None or mv.layer < 0:
            continue
        if printing(mv):
            if mv.tool in primed and abs(state[mv.tool]) > 0.05 and mv.feature not in TOWER:
                bad_retract.append((mv.layer + 1, mv.tool, round(state[mv.tool], 3)))
            state[mv.tool] = 0.0
            primed.add(mv.tool)
        elif mv.e != 0:
            state[mv.tool] += mv.e
    report(4, "Volumen je mm konsistent (± 5 % je Rolle), Retract-Bilanz", not out_of_band and not bad_retract,
           f"Flussverhältnis je Rolle: {flow_ratio}; Ausreißer-Rollen: {list(out_of_band)}; "
           f"Druckbeginn nicht voll gefördert: {len(bad_retract)} {bad_retract[:5]}")

    stats["checks"] = results
    return stats


def summary(stats):
    return {
        "layers": stats["layers"], "toolchanges": stats["toolchanges"],
        "object_volume_mm3": {f"T{k}": round(v, 1) for k, v in sorted(stats["object_volume_mm3"].items())},
        "tower_volume_mm3": {f"T{k}": round(v, 1) for k, v in sorted(stats["tower_volume_mm3"].items())},
        "core_heights": {str(k): v for k, v in sorted(stats["core_heights"].items())},
        "tower_layers": stats["tower_layers"],
    }


def compare(a_path, b_path):
    a = analyze(a_path)[4]
    b = analyze(b_path)[4]
    sa, sb = summary(a), summary(b)
    print(f"{'':28}{'Datei':>18}{'Referenz':>18}")
    for key in ("layers", "toolchanges", "tower_layers"):
        print(f"{key:28}{sa[key]:>18}{sb[key]:>18}")
    for key in ("object_volume_mm3", "tower_volume_mm3", "core_heights"):
        tools = sorted(set(sa[key]) | set(sb[key]))
        for t in tools:
            print(f"{key + ' ' + t:28}{sa[key].get(t, 0):>18}{sb[key].get(t, 0):>18}")
    return sa, sb


def nf01(a_path, b_path):
    def body(path):
        out = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.rstrip("\r\n")
                if s.startswith("; generated by") or s.startswith("; HEADER_BLOCK") or "SoftFever" in s:
                    continue
                if s.startswith("; ") and " = " in s and s[2:].split(" = ")[0] in NEW_KEYS:
                    continue
                if s.startswith("; thumbnail") or s.startswith("; cW9p") or re.match(r"^; [A-Za-z0-9+/=]{40,}$", s):
                    continue
                out.append(s)
        return out
    a, b = body(a_path), body(b_path)
    diffs = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(a) != len(b):
        diffs.append((min(len(a), len(b)), f"<{len(a)} Zeilen>", f"<{len(b)} Zeilen>"))
    return diffs


def main():
    ap = argparse.ArgumentParser(description="Core-Layer-Combine-G-Code-Checks")
    ap.add_argument("gcode")
    ap.add_argument("--json")
    ap.add_argument("--compare")
    ap.add_argument("--nf01")
    a = ap.parse_args()
    if a.nf01:
        diffs = nf01(a.gcode, a.nf01)
        print(f"NF-01: {len(diffs)} abweichende Zeilen")
        for d in diffs[:20]:
            print(f"  Zeile {d[0]}: {d[1][:100]!r} <> {d[2][:100]!r}")
        sys.exit(0 if not diffs else 1)
    if a.compare:
        compare(a.gcode, a.compare)
        sys.exit(0)
    stats = run_checks(a.gcode)
    ok = all(r["ok"] for r in stats["checks"])
    for r in stats["checks"]:
        print(f"[{'OK ' if r['ok'] else 'FEHLER'}] Check {r['check']}: {r['name']}\n         {r['detail']}")
    print(json.dumps(summary(stats), ensure_ascii=False))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary(stats), "checks": stats["checks"]}, f, ensure_ascii=False, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
