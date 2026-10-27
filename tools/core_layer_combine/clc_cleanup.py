#!/usr/bin/env python3
"""Nachbearbeitung fuer core_layer_combine-Ausgabe (Prusa XL / OrcaSlicer).

1. Leere Tool-Abschnitte entfernen: Bahnen, die das Plugin geloescht hat, hinterlassen
   Verfahrwege, Ent-/Rueckzuege und Wipes ohne Druck. Diese Bewegungen fliegen raus.
2. Erste Schicht: Was die grosse Duese in Schicht 1 mit schmalen Linien druckt
   (Erste-Schicht-Linienbreite), uebernimmt die kleine Duese. Die zugehoerigen
   Toolwechsel entfallen.
3. Rueckzugsstand pro Tool wird nachgefuehrt und an jedem Druckbeginn bzw. vor jedem
   Toolwechsel auf den Originalwert korrigiert.

python clc_cleanup.py in.gcode -o out.gcode [--big 0] [--small 1]
"""
import argparse, re

MOVE = re.compile(r'^G[0-3]\b')
TLINE = re.compile(r'^T(\d+)\b')
PARAM = re.compile(r'([XYZEF])([-+]?[\d.]+)')


def code(l):
    return l.split(';')[0].strip()


EONLY = re.compile(r'^G1\s+E([-+]?[\d.]+)(\s+F[\d.]+)?\s*(;.*)?$')


def compensate(out, dd):
    """Ausgleich dd in die letzte reine E-Bewegung einrechnen (nur Verfahrwege/M-Codes dazwischen)."""
    for k in range(len(out) - 1, -1, -1):
        c = code(out[k])
        if not c or c.startswith('M') or c.startswith('G17'):
            continue
        m = EONLY.match(out[k].strip())
        if m:
            e = float(m.group(1)) + dd
            if abs(e) < 1e-4:
                del out[k]
            else:
                out[k] = f'G1 E{e:.5f} F{1800 if e > 0 else 2100}'
            return
        d = dict((a, float(b)) for a, b in PARAM.findall(c)) if MOVE.match(c) else None
        if d is not None and 'E' not in d:
            continue  # Verfahrweg / F-only
        break
    out.append(f'G1 E{dd:.5f} F{1800 if dd > 0 else 2100}')


def parse(lines):
    """Pro Zeile: tool, layer, wipe, ext (Druckbewegung), e (E-Wert), block-id (Toolwechsel)."""
    info = []
    tool = None; layer = -1; wipe = False; blk = None; nblk = 0; z = 0.0
    tc_start = None
    for i, l in enumerate(lines):
        s = code(l)
        if l.startswith(';LAYER_CHANGE'):
            layer += 1
        if l.startswith('; filament end gcode') and layer >= 0:
            blk = nblk; nblk += 1
        d = dict((k, float(v)) for k, v in PARAM.findall(s)) if MOVE.match(s) else {}
        m = TLINE.match(s)
        if m:
            tool_new = int(m.group(1))
        if l.startswith(';WIPE_START'):
            wipe = True
        ext = bool(d) and ('X' in d or 'Y' in d) and d.get('E', 0) > 0 and not wipe
        info.append(dict(tool=tool, layer=layer, wipe=wipe, ext=ext, e=d.get('E', 0.0),
                         move=bool(MOVE.match(s)), blk=blk, d=d))
        if 'Z' in d:
            z = d['Z']
        info[-1]['z'] = z
        if m:
            tool = tool_new
            info[-1]['tool_after'] = tool
        if l.startswith(';WIPE_END'):
            wipe = False
        if blk is not None and ('Override pressure advance' in l):
            blk = None
    return info


def simulate_states(lines, info):
    st = {}
    pre = []
    for l, f in zip(lines, info):
        t = f['tool']
        pre.append(dict(st))
        if f['move'] and t is not None and f['e'] and not f['ext']:
            st[t] = st.get(t, 0) + f['e']
        if 'tool_after' in f:
            st.setdefault(f['tool_after'], st.get(f['tool_after'], 0))
    return pre


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--big', type=int, default=0); ap.add_argument('--small', type=int, default=1)
    ap.add_argument('--first-layer-max-width', type=float, default=0.6)
    a = ap.parse_args()
    lines = open(a.inp, encoding='utf-8').read().split('\n')
    info = parse(lines)

    # Startzustand der Tools: Purge im Start-G-Code zieht jedes Tool um 1,2 mm zurueck.
    # Wir messen ihn aus der Originaldatei: Zustand = Summe aller E-only/Wipe-Werte ab Purge.
    # Einfacher: Simulation ab Dateianfang, Purge-Extrusion zaehlt als Druck (ext) -> nur Rueckzuege zaehlen.
    pre = simulate_states(lines, info)
    # Normieren: Zustand am ersten Druck eines Tools in den Schichten = 0 (voll gefoerdert)
    flc = next(i for i, l in enumerate(lines) if l.startswith(';LAYER_CHANGE'))
    off = {}
    for i in range(flc, len(lines)):
        t = info[i]['tool']
        if info[i]['ext'] and t not in off:
            off[t] = pre[i].get(t, 0)
    pre = [{t: v - off.get(t, 0) for t, v in p.items()} for p in pre]

    # --- Abschnitte (runs) bilden: zusammenhaengende Zeilen gleichen Tools zwischen Toolwechseln/Schichtwechseln
    runs = []; cur = None
    first_layer_line = next(i for i, l in enumerate(lines) if l.startswith(';LAYER_CHANGE'))
    for i, f in enumerate(info):
        if i < first_layer_line:
            continue
        key = (f['layer'], f['tool'], f['blk'])
        if f['blk'] is not None:
            cur = None; continue
        if cur is None or lines[i].startswith(';LAYER_CHANGE') or cur['tool'] != f['tool']:
            cur = dict(tool=f['tool'], layer=f['layer'], start=i, end=i, ext=0, widths=set())
            runs.append(cur)
        cur['end'] = i
        if f['ext']:
            cur['ext'] += 1
    w = None
    for r in runs:
        for i in range(r['start'], r['end'] + 1):
            if lines[i].startswith(';WIDTH:'):
                w = float(lines[i][7:])
            if info[i]['ext']:
                r['widths'].add(w)

    drop = set(); retool = {}; replace_blk = {}
    blocks = {}
    for i, f in enumerate(info):
        if f['blk'] is not None:
            blocks.setdefault(f['blk'], []).append(i)

    def blk_target(b):
        for i in blocks[b]:
            if 'tool_after' in info[i]:
                return info[i]['tool_after']

    # --- 2. Erste Schicht umhaengen
    n_first = 0
    for b, idx in sorted(blocks.items()):
        if info[idx[0]]['layer'] != 0 or blk_target(b) != a.big:
            continue
        # naechster Block, der von big weg wechselt
        nb = next((c for c in sorted(blocks) if c > b and blk_target(c) != a.big), None)
        if nb is None:
            break
        lo, hi = idx[-1] + 1, blocks[nb][0]
        rs = [r for r in runs if lo <= r['start'] < hi]
        ext_layers = {r['layer'] for r in rs if r['ext']}
        ws = set().union(*[r['widths'] for r in rs]) if rs else set()
        if ext_layers <= {0} and ws and max(ws) <= a.first_layer_max_width:
            for i in range(lo, hi):
                retool[i] = a.small
            replace_blk[b] = 'lift'; replace_blk[nb] = 'lift'
            n_first += 1
        break

    # --- 1. leere Abschnitte (nicht der letzte Abschnitt = End-G-Code)
    n_empty = 0
    for r in runs[:-1]:
        if r['ext'] == 0 and r['tool'] is not None:
            has_motion = any(info[i]['move'] for i in range(r['start'], r['end'] + 1))
            if not has_motion:
                continue
            for i in range(r['start'], r['end'] + 1):
                if info[i]['move']:
                    drop.add(i)
            n_empty += 1

    # --- Ausgabe mit Rueckzugsnachfuehrung
    out = []; st = {}
    for t, v in pre[first_layer_line].items():
        st[t] = v
    tool = info[first_layer_line]['tool']
    last_was_ext = False; in_wipe_drop = False
    i = 0
    out.extend(lines[:first_layer_line])
    i = first_layer_line
    while i < len(lines):
        l = lines[i]; f = info[i]
        b = f['blk']
        if b is not None and b in replace_blk:
            # ganzen Block ersetzen: nur Luefter behalten, Z anheben
            idx = blocks[b]
            out.append(f'; clc_cleanup: Toolwechsel entfernt ({lines[[j for j in idx if "Change Tool" in lines[j]][0]].strip("; ")})')
            out.append(f'G1 Z{info[idx[0]]["z"] + 0.6:.3f} F720 ; anheben fuer Verfahrweg')
            for j in idx:
                if code(lines[j]).startswith('M106') or code(lines[j]).startswith('M107'):
                    out.append(lines[j])
            i = idx[-1] + 1
            continue
        if b is not None and i == blocks[b][0]:
            # Checkpoint: auslaufendes Tool muss Originalrueckzug haben
            want = pre[i].get(tool, 0)
            have = st.get(tool, 0)
            if abs(want - have) > 1e-4:
                dd = want - have
                compensate(out, dd)
                st[tool] = want
        if 'tool_after' in f and b is not None:
            out.append(l); tool = f['tool_after']; st.setdefault(tool, pre[i].get(tool, 0))
            i += 1; continue
        if i in drop:
            i += 1; continue
        # verwaiste Wipes (kein Druck direkt davor) verwerfen
        if l.startswith(';WIPE_START') and not last_was_ext and b is None:
            j = i
            while not lines[j].startswith(';WIPE_END'):
                j += 1
            i = j + 1; continue
        t = retool.get(i, f['tool']) if b is None else tool
        if f['ext'] and b is None:
            want = 0.0
            have = st.get(t, 0)
            if abs(want - have) > 1e-4:
                dd = want - have
                compensate(out, dd)
                st[t] = want
            last_was_ext = True
        elif f['move']:
            if f['e'] and not f['ext']:
                st[t] = st.get(t, 0) + f['e']
            if f['e'] == 0 and ('X' in f['d'] or 'Y' in f['d']):
                last_was_ext = False
        out.append(l)
        i += 1

    clean = []
    for l in out:
        if l.startswith(';WIPE_END') and clean and clean[-1].startswith(';WIPE_START'):
            clean.pop(); continue
        clean.append(l)
    out = clean
    if lines and lines[0].startswith('; core_layer_combine'):
        out.insert(1, f'; clc_cleanup: {n_empty} leere Abschnitte bereinigt, '
                      f'{2 * n_first} Toolwechsel in Schicht 1 entfernt')
    open(a.out, 'w', encoding='utf-8').write('\n'.join(out))
    print(f'leere Abschnitte: {n_empty}, erste Schicht umgehaengt: {n_first}')


if __name__ == '__main__':
    main()
