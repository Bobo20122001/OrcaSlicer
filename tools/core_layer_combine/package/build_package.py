"""Baut das portable Paket OrcaSlicer-CLC-v<version>-win64.zip.

    python build_package.py [--version 1.0] [--app build/OrcaSlicer] [--out build/package]

Voraussetzung: build_win.bat -s -i -j 8 (Installationsordner build/OrcaSlicer).
Inhalt des Pakets:
  app/        kompletter Programmordner
  data/       vorkonfiguriertes Datenverzeichnis: Drucker "Prusa XL 5T CLC", Prozess "0.2mm CLC",
              Filamente "PLA @XL CLC 1.2mm" / "PLA @XL CLC 0.4mm"; kein Einrichtungsassistent
  Start.bat   startet app/orca-slicer.exe mit --datadir data
  LIESMICH.txt, testprints/ (G-Codes + README)
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PROFILES = os.path.join(HERE, "profiles")

START_BAT = '@echo off\r\nstart "" "%~dp0app\\orca-slicer.exe" --datadir "%~dp0data"\r\n'


def write_app_config(data_dir, machine, process, filaments, version):
    conf = {
        "app": {
            "version": version,
            "language": "de_DE",
            "user_mode": "advanced",
            "default_page": "1",
            "show_splash_screen": True,
        },
        "firstguide": {"finish": True},
        "models": [{"vendor": "Prusa", "model": "Prusa XL 5T", "nozzle_diameter": "0.4"}],
        "filaments": ["Generic PLA @Prusa XL"],
        "presets": {"machine": machine, "print": process, "filaments": filaments},
        # Process and filaments are remembered per printer (PresetBundle::load_selections()).
        "orca_presets": [dict({"machine": machine, "process": process, "filament": filaments[0]},
                              **{f"filament_{i:02d}": name for i, name in enumerate(filaments[1:], 1)})],
    }
    text = json.dumps(conf, indent=4, ensure_ascii=False) + "\n"
    # Same checksum line as AppConfig::save(), so Orca reads the file as untouched.
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest().upper()
    with open(os.path.join(data_dir, "OrcaSlicer.conf"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "# MD5 checksum " + md5 + "\n")


def build_data_dir(data_dir, orca_version):
    os.makedirs(data_dir, exist_ok=True)
    names = {}
    for kind, folder in (("machine", "machine"), ("process", "process"), ("filament", "filament")):
        target = os.path.join(data_dir, "user", "default", folder)
        os.makedirs(target, exist_ok=True)
        for path in sorted(glob.glob(os.path.join(PROFILES, f"{kind}*.json"))):
            preset = json.load(open(path, encoding="utf-8"))
            name = preset["name"]
            names.setdefault(kind, [])
            if name in names[kind]:
                continue
            names[kind].append(name)
            with open(os.path.join(target, name + ".json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(preset, f, indent=4, ensure_ascii=False)
    fil = names["filament"]
    # T0 = 1,2-mm-Kern, alle anderen Werkzeuge mit dem 0,4-mm-Profil
    filaments = [fil[0]] + [fil[1]] * 4
    write_app_config(data_dir, names["machine"][0], names["process"][0], filaments, orca_version)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--app", default=os.path.join(REPO, "build", "OrcaSlicer"))
    ap.add_argument("--out", default=os.path.join(REPO, "build", "package"))
    ap.add_argument("--orca-version", default="2.5.0-dev")
    a = ap.parse_args()

    name = f"OrcaSlicer-CLC-v{a.version}-win64"
    stage = os.path.join(a.out, name)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    if not os.path.isfile(os.path.join(a.app, "orca-slicer.exe")):
        raise SystemExit(f"Kein Installationsordner unter {a.app} – erst build_win.bat -s -i -j 8")
    shutil.copytree(a.app, os.path.join(stage, "app"))
    build_data_dir(os.path.join(stage, "data"), a.orca_version)
    with open(os.path.join(stage, "Start.bat"), "w", encoding="ascii", newline="") as f:
        f.write(START_BAT)
    shutil.copy(os.path.join(HERE, "LIESMICH.txt"), os.path.join(stage, "LIESMICH.txt"))
    prints = os.path.join(HERE, "..", "testprints")
    if os.path.isdir(prints):
        shutil.copytree(prints, os.path.join(stage, "testprints"))

    zip_path = os.path.join(a.out, name + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.join(name, os.path.relpath(full, stage)))
    print(f"{zip_path}: {os.path.getsize(zip_path) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
