# /// script
# requires-python = ">=3.10"
# dependencies = []
#
# [tool.orcaslicer.plugin]
# name = "Core Layer Combine"
# description = "Druckt alles, was ein bestimmtes Tool (z.B. 1.2er Duese) druckt, nur jede n-te Schicht mit entsprechend mehr Material - dicke Kernschichten bei duennen Aussenschichten."
# author = "Ole Kisters"
# version = "0.1.1"
# ///
"""
Core Layer Combine - G-Code-Nachbearbeitung fuer Multi-Tool-Drucker (Prusa XL).

Idee: Orca slict alles mit der feinen Schichthoehe (z.B. 0,2 mm). Dieses Script fasst
fuer EIN Tool (z.B. T1 mit 1,2er Duese) mehrere Schichten zusammen: In den unteren
Schichten einer Gruppe werden dessen Bahnen geloescht, in der obersten Schicht wird
die Extrusion so erhoeht, dass die Bahn die volle Gruppenhoehe (z.B. 0,6 mm) fuellt.
Leer gewordene Tool-Besuche werden samt Werkzeugwechsel entfernt.

Laeuft als Orca-Plugin (Slicing Pipeline, Schritt psGCodePostProcess) oder standalone:
    python core_layer_combine.py input.gcode [-o output.gcode] [--config cfg.json]
"""
from __future__ import annotations

import json
import math
import re
import sys

MARKER = "; core_layer_combine: processed"

DEFAULT_CONFIG = {
    # Tool, dessen Schichten zusammengefasst werden. -1 = automatisch (groesste Duese).
    "tool": -1,
    # Maximale Hoehe einer zusammengefassten Schicht in mm.
    "max_combined_height": 0.6,
    # Die ersten n Schichten nie anfassen (Haftung / Bodenschichten).
    "skip_first_layers": 1,
    # Maximal erlaubte Abweichung der Bahnlaenge innerhalb einer Gruppe (0.25 = 25 %).
    # Aendert sich die Geometrie staerker (Schraegen, Absaetze), wird nicht kombiniert.
    "similarity_tolerance": 0.25,
    # Features, bei denen eine Gruppe NICHT kombiniert wird.
    "excluded_features": ["Bridge", "Internal Bridge", "Overhang wall", "Support",
                          "Support interface", "Support transition", "Ironing",
                          "Prime tower", "Skirt", "Brim"],
    # Volumenstrom-Grenze fuer das Tool in mm^3/s. 0 = aus Orca-Filamentprofil lesen.
    "max_volumetric_speed": 0,
    # Filamentdurchmesser in mm. 0 = aus Orca lesen (Fallback 1.75).
    "filament_diameter": 0,
}

TOOL_RE = re.compile(r"^T(\d+)(?=\s|;|$)")
WORD_RE = re.compile(r"([A-Za-z])([-+]?\d*\.?\d+)")
STRUCTURAL_PREFIXES = (";LAYER_CHANGE", ";Z:", ";HEIGHT:", ";BEFORE_LAYER_CHANGE",
                       ";AFTER_LAYER_CHANGE", "M73", "M117", "M486", "G92", "; Z_HEIGHT",
                       "; CHANGE_LAYER", "; LAYER_HEIGHT", ";_GP_", "; stop printing object",
                       "; start printing object", "; printing object", "; stop printing object")
STATE_PREFIXES = ("M106", "M107")


class GLine:
    __slots__ = ("raw", "cmd", "words", "tool", "layer", "feature", "width", "printing",
                 "x0", "y0", "drop", "new", "ch")

    def __init__(self, raw: str):
        self.raw = raw
        code = raw.split(";", 1)[0].strip()
        parts = code.split(None, 1)
        self.cmd = parts[0].upper() if parts else ""
        self.words = {}
        if self.cmd in ("G0", "G1", "G2", "G3") and len(parts) > 1:
            for k, v in WORD_RE.findall(parts[1]):
                self.words[k.upper()] = float(v)
        self.tool = -1
        self.layer = -1
        self.feature = ""
        self.width = 0.0
        self.printing = False
        self.x0 = self.y0 = 0.0
        self.drop = False
        self.new = None  # replacement text
        self.ch = 0.0  # kombinierte Hoehe (nur skalierte Bahnen)


class Result:
    def __init__(self):
        self.groups = 0
        self.dropped_layers = 0
        self.removed_toolchanges = 0
        self.messages = []


# --------------------------------------------------------------------------- parsing
def annotate(lines: list[GLine]):
    """Tool, Layer, Feature, Breite und Startpunkt jeder Zeile bestimmen."""
    tool = -1
    layer = -1
    feature = ""
    width = 0.0
    x = y = 0.0
    layers = []  # (z, height, first_line_index)
    pending_z = None
    for i, ln in enumerate(lines):
        s = ln.raw.lstrip()
        if s.startswith(";LAYER_CHANGE"):
            layer += 1
            layers.append([None, None, i])
        elif s.startswith(";Z:") and layers:
            layers[-1][0] = float(s[3:])
        elif s.startswith(";HEIGHT:") and layers and layers[-1][1] is None:
            layers[-1][1] = float(s[8:])
        elif s.startswith(";TYPE:"):
            feature = s[6:].strip()
        elif s.startswith(";WIDTH:"):
            try:
                width = float(s[7:])
            except ValueError:
                pass
        m = TOOL_RE.match(s)
        if m:
            tool = int(m.group(1))
        ln.tool, ln.layer, ln.feature, ln.width = tool, layer, feature, width
        ln.x0, ln.y0 = x, y
        if ln.cmd in ("G0", "G1"):
            w = ln.words
            e = w.get("E", 0.0)
            if e > 0 and ("X" in w or "Y" in w):
                ln.printing = True
            x = w.get("X", x)
            y = w.get("Y", y)
    for L in layers:
        if L[1] is None:
            L[1] = 0.0
    return layers


def seg_len(ln: GLine) -> float:
    return math.hypot(ln.words.get("X", ln.x0) - ln.x0, ln.words.get("Y", ln.y0) - ln.y0)


def mm3_per_mm(width: float, height: float) -> float:
    """Slic3r/Orca-Flowmodell: Rechteck mit halbrunden Enden."""
    return height * (width - height * (1.0 - math.pi / 4.0))


# --------------------------------------------------------------------------- grouping
def plan_groups(lines, layers, tool, cfg, res: Result):
    n = len(layers)
    length = [0.0] * n
    feats = [set() for _ in range(n)]
    for ln in lines:
        if ln.printing and ln.tool == tool and ln.layer >= 0:
            length[ln.layer] += seg_len(ln)
            feats[ln.layer].add(ln.feature)
    excluded = set(cfg["excluded_features"])
    maxh = cfg["max_combined_height"] + 1e-6

    def eligible(i):
        return (i >= cfg["skip_first_layers"] and length[i] > 0
                and not (feats[i] & excluded) and layers[i][1] > 0)

    def similar(a, b):
        hi = max(length[a], length[b])
        return hi == 0 or abs(length[a] - length[b]) / hi <= cfg["similarity_tolerance"]

    groups = []
    i = 0
    while i < n:
        if not eligible(i):
            i += 1
            continue
        grp = [i]
        h = layers[i][1]
        j = i + 1
        while (j < n and eligible(j) and h + layers[j][1] <= maxh
               and all(similar(k, j) for k in grp)):
            grp.append(j)
            h += layers[j][1]
            j += 1
        if len(grp) > 1:
            groups.append((grp, h))
        i = j
    res.groups = len(groups)
    return groups


# --------------------------------------------------------------------------- transform
def apply_groups(lines, layers, tool, groups, cfg, res: Result):
    dropped = set()
    scale_layer = {}  # layer -> combined height
    for grp, h in groups:
        dropped.update(grp[:-1])
        scale_layer[grp[-1]] = h
    res.dropped_layers = len(dropped)

    fil_area = math.pi * (cfg["filament_diameter"] / 2.0) ** 2
    vmax = cfg["max_volumetric_speed"]
    feed = 0.0
    for ln in lines:
        if ln.cmd in ("G0", "G1") and "F" in ln.words:
            feed = ln.words["F"]
        if not (ln.printing and ln.tool == tool):
            continue
        if ln.layer in dropped:
            ln.drop = True
            continue
        if ln.layer in scale_layer:
            h = layers[ln.layer][1]
            H = scale_layer[ln.layer]
            if ln.width > 0:
                factor = mm3_per_mm(ln.width, H) / mm3_per_mm(ln.width, h)
            else:
                factor = H / h
            e = ln.words["E"] * factor
            f = ln.words.get("F", feed)
            L = seg_len(ln)
            new_f = None
            if vmax > 0 and L > 0 and f > 0:
                flow = e * fil_area / (L / (f / 60.0))
                if flow > vmax:
                    new_f = f * vmax / flow
            ln.new = rewrite(ln, e, new_f)
            ln.ch = H
            if new_f is not None and "F" not in ln.words:
                # Vorschub nur fuer diese Zeile reduziert -> fuer Folgezeile wiederherstellen
                ln.new += f"\nG1 F{f:.0f}"
    return dropped


def rewrite(ln: GLine, e: float, f: float | None) -> str:
    code, _, comment = ln.raw.partition(";")
    toks = code.split()
    out = []
    for t in toks:
        if t[0] in "Ee":
            out.append(f"E{e:.5f}")
        elif t[0] in "Ff" and f is not None:
            out.append(f"F{f:.0f}")
        else:
            out.append(t)
    if f is not None and not any(t[0] in "Ff" for t in toks):
        out.append(f"F{f:.0f}")
    s = " ".join(out)
    return s + (" ;" + comment if comment else "")


def remove_empty_visits(lines, tool, res: Result):
    """Tool-Besuche ohne Druckbewegungen samt beider Werkzeugwechsel entfernen."""
    picks = [i for i, ln in enumerate(lines) if TOOL_RE.match(ln.raw.lstrip())]
    for k, p in enumerate(picks):
        if lines[p].tool != tool:
            continue
        end = picks[k + 1] if k + 1 < len(picks) else None
        if end is None or k == 0:
            continue  # Besuch am Dateiende/-anfang: nicht anfassen
        prev_tool = lines[picks[k - 1]].tool
        next_tool = lines[end].tool
        if prev_tool != next_tool or prev_tool == tool:
            continue
        if any(lines[i].printing and not lines[i].drop for i in range(p, end)):
            continue
        # Start: nach der letzten (behaltenen) Druckbewegung des vorherigen Tools
        start = p
        while start > picks[k - 1] and not (lines[start - 1].printing and not lines[start - 1].drop):
            start -= 1
        if start == picks[k - 1]:
            continue  # vorheriger Besuch hat nichts gedruckt - sicherheitshalber lassen
        e_prev = 0.0
        retract_f = 2100.0
        last_layer_z = None
        state = {}
        for i in range(start, end + 1):
            ln = lines[i]
            s = ln.raw.lstrip()
            if ln.drop:
                continue
            if i < p and ln.cmd in ("G0", "G1") and "E" in ln.words:
                e_prev += ln.words["E"]  # Rueckzug/Wipe des vorherigen Tools
                if "F" in ln.words and not ("X" in ln.words or "Y" in ln.words):
                    retract_f = ln.words["F"]
            if s.startswith(";Z:"):
                last_layer_z = float(s[3:])
            if s.startswith(STRUCTURAL_PREFIXES):
                continue  # Layer-Tags etc. bleiben erhalten
            if s.startswith(STATE_PREFIXES):
                state["fan"] = ln.raw
            ln.drop = True
        tail = []
        if abs(e_prev) > 1e-6:
            tail.append(f"G1 E{e_prev:.5f} F{retract_f:.0f} ; core_layer_combine: Rueckzug des aktiven Tools")
        if last_layer_z is not None:
            tail.append(f"G1 Z{last_layer_z:g} ; core_layer_combine: Layerhoehe")
        if "fan" in state:
            tail.append(state["fan"])
        if tail:
            lines[end].drop = True
            lines[end].new = None
            # Pick-Zeile des naechsten Tools ist entfernt -> Ersatz an ihre Stelle
            lines[end] = _replacement(lines[end], "\n".join(tail))
        res.removed_toolchanges += 2


def _replacement(old: GLine, text: str) -> GLine:
    ln = GLine("")
    ln.tool, ln.layer = old.tool, old.layer
    ln.new = text
    return ln


# --------------------------------------------------------------------------- driver
def detect_tool(lines, cfg_tool, nozzles):
    if cfg_tool >= 0:
        return cfg_tool
    used = sorted({ln.tool for ln in lines if ln.printing and ln.tool >= 0})
    if len(used) < 2:
        return -1
    if nozzles:
        return max(used, key=lambda t: nozzles[t] if t < len(nozzles) else 0)
    return used[-1]


def parse_list(val):
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [float(v) for v in val]
    out = []
    for v in str(val).replace(";", ",").split(","):
        v = v.strip().strip('"')
        try:
            out.append(float(v))
        except ValueError:
            pass
    return out


def process_text(text: str, cfg: dict, orca_cfg=None) -> tuple[str, Result]:
    res = Result()
    if MARKER in text:
        res.messages.append("bereits verarbeitet - uebersprungen")
        return text, res
    if "WIPE_TOWER_START" in text or "; CP TOOLCHANGE" in text:
        res.messages.append("Prime-Tower erkannt - bitte deaktivieren, Datei unveraendert")
        return text, res
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    orca_cfg = orca_cfg or (lambda key: None)

    nozzles = parse_list(orca_cfg("nozzle_diameter"))
    lines = [GLine(r) for r in text.split("\n")]
    layers = annotate(lines)
    tool = detect_tool(lines, int(cfg["tool"]), nozzles)
    if tool < 0:
        res.messages.append("nur ein Tool im Druck - nichts zu tun")
        return text, res
    if nozzles and tool < len(nozzles):
        lim = 0.8 * nozzles[tool]
        if cfg["max_combined_height"] > lim:
            res.messages.append(f"max_combined_height auf {lim:.2f} mm begrenzt (80 % Duese)")
            cfg["max_combined_height"] = lim
    if not cfg["filament_diameter"]:
        d = parse_list(orca_cfg("filament_diameter"))
        cfg["filament_diameter"] = d[tool] if tool < len(d) else (d[0] if d else 1.75)
    if not cfg["max_volumetric_speed"]:
        v = parse_list(orca_cfg("filament_max_volumetric_speed"))
        cfg["max_volumetric_speed"] = v[tool] if tool < len(v) else (v[0] if v else 0)

    if nozzles and tool < len(nozzles):
        widths = [ln.width for ln in lines if ln.printing and ln.tool == tool and ln.width > 0]
        if widths and min(widths) < 0.8 * nozzles[tool]:
            res.messages.append(f"WARNUNG: T{tool} druckt Linien ab {min(widths):.2f} mm Breite bei "
                                f"{nozzles[tool]} mm Duese - Linienbreiten in % angeben (z.B. 105 %)")

    groups = plan_groups(lines, layers, tool, cfg, res)
    if not groups:
        res.messages.append("keine kombinierbaren Schichten gefunden")
        return text, res
    apply_groups(lines, layers, tool, groups, cfg, res)
    remove_empty_visits(lines, tool, res)

    out = [MARKER + f" (tool T{tool}, max {cfg['max_combined_height']} mm)"]
    cur_h = None  # zuletzt ausgegebene ;HEIGHT: (fuer die Orca-G-Code-Vorschau)
    for ln in lines:
        if ln.drop and ln.new is None:
            continue
        s = ln.raw.lstrip()
        if s.startswith(";HEIGHT:"):
            try:
                cur_h = float(s[8:])
            except ValueError:
                pass
        if ln.printing and ln.layer >= 0:
            want = ln.ch if ln.ch else layers[ln.layer][1]
            if want and (cur_h is None or abs(want - cur_h) > 1e-6):
                out.append(f";HEIGHT:{want:g}")
                cur_h = want
        out.append(ln.new if ln.new is not None else ln.raw)
    res.messages.insert(0, f"T{tool}: {res.groups} Gruppen, {res.dropped_layers} Schichten "
                           f"zusammengefasst, {res.removed_toolchanges} Werkzeugwechsel entfernt")
    return "\n".join(out), res


def process_file(path_in, path_out, cfg, orca_cfg=None) -> Result:
    with open(path_in, "r", encoding="utf-8", errors="surrogateescape") as f:
        text = f.read()
    new, res = process_text(text, cfg, orca_cfg)
    if new is not text:
        with open(path_out, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(new)
    return res


# --------------------------------------------------------------------------- Orca plugin
try:
    import orca  # nur innerhalb von OrcaSlicer verfuegbar
except ImportError:
    orca = None

if orca is not None:
    class CoreLayerCombine(orca.slicing.SlicingPipelineCapabilityBase):
        def get_name(self):
            return "Core Layer Combine"

        def get_default_config(self):
            return dict(DEFAULT_CONFIG)

        def execute(self, ctx):
            if ctx.step != orca.slicing.Step.psGCodePostProcess:
                return orca.ExecutionResult.success()
            try:
                cfg = {**DEFAULT_CONFIG, **json.loads(self.get_config() or "{}")}
            except ValueError as exc:
                return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError,
                                                    f"Config ungueltig: {exc}")
            try:
                res = process_file(ctx.gcode_path, ctx.gcode_path, cfg, ctx.config_value)
            except Exception as exc:  # Datei bleibt dann unveraendert
                return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError,
                                                    f"Fehler: {exc}")
            return orca.ExecutionResult.success("; ".join(res.messages))

    @orca.plugin
    class CoreLayerCombinePlugin(orca.base):
        def register_capabilities(self):
            orca.register_capability(CoreLayerCombine)


# --------------------------------------------------------------------------- CLI
def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--config", help="JSON-Datei mit Einstellungen")
    ap.add_argument("--set", action="append", default=[], help="key=value (JSON-Wert)")
    a = ap.parse_args(argv)
    cfg = json.load(open(a.config)) if a.config else {}
    for kv in a.set:
        k, v = kv.split("=", 1)
        cfg[k] = json.loads(v)

    # Orca-Werte aus dem Config-Block am Dateiende lesen ("; key = value")
    tail = {}
    with open(a.input, encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            m = re.match(r"^; (\w+) = (.*)$", line)
            if m:
                tail[m.group(1)] = m.group(2)
    res = process_file(a.input, a.output or a.input, cfg, tail.get)
    print("\n".join(res.messages))


if __name__ == "__main__":
    main(sys.argv[1:])
