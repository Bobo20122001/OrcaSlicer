"""Erzeugt flache Orca-Benutzerprofile (Maschine, Prozess, Filamente) aus dem
Einstellungsblock einer von Orca erzeugten G-Code-Datei.

    python gcode_to_profiles.py datei.gcode zielordner [--repo X:/Dev/OrcaSlicer]
                                [--name Basisname] [--set schluessel=wert ...]

Die Zuordnung der Optionen zu Prozess/Filament stammt aus den Listen in
src/libslic3r/Preset.cpp, die Optionstypen (Skalar/Vektor) aus
src/libslic3r/PrintConfig.cpp. Alles, was weder Prozess noch Filament ist,
landet im Maschinenprofil. Die Profile haben kein "inherits", damit sie
unabhängig von den Systemprofilen genau die Werte der Referenzdatei tragen.
"""
import argparse
import json
import os
import re

SKIP = {"print_settings_id", "printer_settings_id", "filament_settings_id", "inherits_group",
        "different_settings_to_system", "print_compatible_printers", "compatible_printers",
        "compatible_prints", "compatible_printers_condition", "compatible_prints_condition",
        "inherits", "filament_ids", "upward_compatible_machine", "plate_name"}


def read_config_block(path):
    cfg = {}
    inside = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("; CONFIG_BLOCK_START"):
                inside = True
                continue
            if line.startswith("; CONFIG_BLOCK_END"):
                break
            if inside:
                m = re.match(r"^; ([A-Za-z0-9_]+) = (.*)$", line)
                if m and m.group(1) not in cfg:
                    cfg[m.group(1)] = m.group(2)
    return cfg


def preset_lists(repo):
    src = open(os.path.join(repo, "src", "libslic3r", "Preset.cpp"), encoding="utf-8").read()

    def array(name):
        start = src.index("static std::vector<std::string> " + name)
        body = src[src.index("{", start):src.index("};", start)]
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        body = re.sub(r"//[^\n]*", "", body)
        return set(re.findall(r'"([A-Za-z0-9_]+)"', body))

    return array("s_Preset_print_options"), array("s_Preset_filament_options")


# Optionen, die PrintConfig.cpp in Schleifen oder Hilfsfunktionen anlegt.
EXTRA_TYPES = {"filament_plugin_config_overrides": "coString", "print_plugin_config_overrides": "coString",
               "printer_plugin_config_overrides": "coString", "gcode_remap_x": "coEnum",
               "gcode_remap_y": "coEnum", "gcode_remap_z": "coEnum"}


def option_types(repo):
    src = open(os.path.join(repo, "src", "libslic3r", "PrintConfig.cpp"), encoding="utf-8").read()
    types = dict(re.findall(r'this->add(?:_nullable)?\("([A-Za-z0-9_]+)",\s*(co[A-Za-z]+)\)', src))
    types.update(EXTRA_TYPES)
    return types


def guess_type(key, types):
    """Typ einer Option, auch für Optionen ohne eigene add()-Zeile."""
    if key in types:
        return types[key]
    if key.startswith("machine_max_"):
        return "coFloats"
    if key.startswith("filament_") and key[len("filament_"):] in types:
        return types[key[len("filament_"):]]  # Filament-Überschreibung einer Extruderoption
    return None


def unescape(s):
    return bytes(s, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")


def split_vector(value, typ):
    if value == "":
        return []
    if typ == "coStrings":
        if value.startswith('"'):
            return [unescape(i) for i in re.findall(r'"((?:[^"\\]|\\.)*)"', value)]
        return value.split(";")
    if typ == "coPoints":
        return [p for p in value.split(",") if p]
    return [p for p in value.split(",")]


def scalar(value, typ):
    if typ == "coString" and len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return unescape(value[1:-1])
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gcode")
    ap.add_argument("outdir")
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
    ap.add_argument("--name", default="CLC Referenz")
    ap.add_argument("--set", action="append", default=[], help="Prozess-Schlüssel=Wert überschreiben")
    a = ap.parse_args()

    cfg = read_config_block(a.gcode)
    print_keys, filament_keys = preset_lists(a.repo)
    types = option_types(a.repo)
    n_fil = len(split_vector(cfg.get("filament_diameter", "1.75"), "coFloats"))

    process = {"type": "process", "name": a.name + " Prozess", "from": "User", "inherits": "", "version": "2.5.0.0"}
    machine = {"type": "machine", "name": a.name + " Drucker", "from": "User", "inherits": "", "version": "2.5.0.0"}
    filaments = [{"type": "filament", "name": f"{a.name} Filament {i + 1}", "from": "User", "inherits": "",
                  "version": "2.5.0.0"} for i in range(n_fil)]
    unknown = []
    for key, value in cfg.items():
        if key in SKIP:
            continue
        typ = guess_type(key, types)
        if typ is None:
            unknown.append(key)
            continue
        is_vec = typ.endswith("s")
        if key in filament_keys or (key.startswith("filament_") and key not in print_keys):
            vals = split_vector(value, typ) if is_vec else [scalar(value, typ)]
            for i, fil in enumerate(filaments):
                v = vals[i] if i < len(vals) else vals[-1]
                fil[key] = [v] if is_vec else v
        elif key in print_keys or key == "print_plugin_config_overrides":
            process[key] = split_vector(value, typ) if is_vec else scalar(value, typ)
        else:
            machine[key] = split_vector(value, typ) if is_vec else scalar(value, typ)

    for kv in a.set:
        k, v = kv.split("=", 1)
        process[k] = v

    os.makedirs(a.outdir, exist_ok=True)
    out = {"machine.json": machine, "process.json": process}
    for i, fil in enumerate(filaments):
        out[f"filament{i + 1}.json"] = fil
    for name, data in out.items():
        with open(os.path.join(a.outdir, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    print(f"{len(process)} Prozess-, {len(machine)} Maschinen-, {len(filaments[0]) if filaments else 0} "
          f"Filament-Schlüssel je Slot ({n_fil} Slots); unbekannt: {len(unknown)} {unknown[:8]}")


if __name__ == "__main__":
    main()
