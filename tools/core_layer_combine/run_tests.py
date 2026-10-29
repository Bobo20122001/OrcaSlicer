"""Slict Testmodelle über die Orca-CLI und prüft die G-Codes.

    python run_tests.py --profiles profiles/reference_clc [--models testeck ...] [--out DIR] [--no-check]
    python run_tests.py --package [--datadir DIR] [--models ...] [--out DIR]

--profiles: Ordner mit flachen Profilen machine.json, process.json, filament1.json ... filamentN.json.
--package:  slict mit den Profilen des portablen Pakets. Ohne --datadir wird das Paket-Datenverzeichnis aus
            package/profiles neu gebaut (build/clc_test_datadir/pkg); mit --datadir wird ein vorhandenes
            (z. B. aus dem entpackten Zip) verwendet. Die CLI ordnet Benutzerprofile über ihren Dateipfad im
            Datenverzeichnis zu, deshalb kommen die Dateien direkt aus data/user/default.
Ergebnis je Modell: <out>/<modell>.gcode, <modell>.json (Check-Bericht), <modell>.log (CLI-Log).
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "package"))
import check_gcode  # noqa: E402

ALL_MODELS = ["testeck", "wuerfel20", "pyramide", "halter", "zugstab_1A", "duennwand"]


def ensure_system_presets(datadir):
    """Profile mit "inherits" werden gegen die Systemprofile des Datenverzeichnisses aufgelöst, die die GUI
    beim ersten Start aus resources kopiert. Für die CLI legt das Skript sie selbst an."""
    system = os.path.join(datadir, "system")
    if os.path.isfile(os.path.join(system, "Prusa.json")):
        return
    os.makedirs(system, exist_ok=True)
    for vendor in ("Prusa", "OrcaFilamentLibrary"):
        src = os.path.join(REPO, "resources", "profiles", vendor)
        shutil.copy(src + ".json", system)
        shutil.copytree(src, os.path.join(system, vendor), dirs_exist_ok=True)


def write_cli_config(datadir):
    conf = os.path.join(datadir, "OrcaSlicer.conf")
    if os.path.isfile(conf):
        return
    # Nur als installiert eingetragene Druckermodelle werden geladen; AppConfig erwartet die MD5-Schlusszeile.
    text = json.dumps({"app": {"version": "2.5.0-dev"}, "firstguide": {"finish": True},
                       "models": [{"vendor": "Prusa", "model": "Prusa XL 5T", "nozzle_diameter": "0.4"}]}, indent=4) + "\n"
    with open(conf, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "# MD5 checksum " + hashlib.md5(text.encode("utf-8")).hexdigest().upper() + "\n")


def flat_profiles(profiles):
    fils = sorted(glob.glob(os.path.join(profiles, "filament*.json")),
                  key=lambda p: int("".join(c for c in os.path.basename(p) if c.isdigit()) or 0))
    return [os.path.join(profiles, "machine.json"), os.path.join(profiles, "process.json")], fils


def package_profiles(datadir):
    text = open(os.path.join(datadir, "OrcaSlicer.conf"), encoding="utf-8").read()
    conf = json.loads(text[:text.rfind("#")])
    presets = conf["presets"]
    user = os.path.join(datadir, "user", "default")
    settings = [os.path.join(user, "machine", presets["machine"] + ".json"),
                os.path.join(user, "process", presets["print"] + ".json")]
    fils = [os.path.join(user, "filament", name + ".json") for name in presets["filaments"]]
    return settings, fils


def slice_model(exe, settings, fils, model, out_dir, datadir):
    work = os.path.join(out_dir, "_" + model)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    cmd = [exe, "--datadir", datadir, "--slice", "0", "--load-settings", ";".join(settings),
           "--load-filaments", ";".join(fils), "--outputdir", work, os.path.join(HERE, "testmodels", model + ".stl")]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=work)
    produced = glob.glob(os.path.join(work, "*.gcode"))
    if res.returncode != 0 or not produced:
        return None, f"exit {res.returncode}: {res.stderr.strip()[-400:]}", time.time() - t0
    target = os.path.join(out_dir, model + ".gcode")
    shutil.move(produced[0], target)
    for log in glob.glob(os.path.join(work, "*.log")):
        shutil.move(log, os.path.join(out_dir, model + ".log"))
    shutil.rmtree(work, ignore_errors=True)
    return target, "", time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(REPO, "build", "src", "Release", "orca-slicer.exe"))
    ap.add_argument("--profiles")
    ap.add_argument("--package", action="store_true")
    ap.add_argument("--datadir")
    ap.add_argument("--models", nargs="*", default=ALL_MODELS)
    ap.add_argument("--out")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    a.exe = os.path.abspath(a.exe)
    if a.package:
        if a.datadir:
            datadir = os.path.abspath(a.datadir)
        else:
            import build_package
            datadir = os.path.join(REPO, "build", "clc_test_datadir", "pkg")
            shutil.rmtree(datadir, ignore_errors=True)
            build_package.build_data_dir(datadir, "2.5.0-dev")
        settings, fils = package_profiles(datadir)
        name = "package"
    elif a.profiles:
        datadir = os.path.join(REPO, "build", "clc_test_datadir", "cli")
        os.makedirs(datadir, exist_ok=True)
        write_cli_config(datadir)
        settings, fils = flat_profiles(os.path.abspath(a.profiles))
        name = os.path.basename(os.path.normpath(a.profiles))
    else:
        raise SystemExit("--profiles oder --package angeben")
    ensure_system_presets(datadir)
    out = a.out or os.path.join(REPO, "build", "clc_runs", name)
    os.makedirs(out, exist_ok=True)

    failed = 0
    for model in a.models:
        path, err, secs = slice_model(a.exe, settings, fils, model, out, datadir)
        if path is None:
            print(f"== {model}: SLICEN FEHLGESCHLAGEN ({secs:.0f} s) {err}")
            failed += 1
            continue
        print(f"== {model}: {secs:.0f} s -> {path}")
        if a.no_check:
            continue
        try:
            stats = check_gcode.run_checks(path)
        except SystemExit as exc:
            print(f"   Check abgebrochen: {exc}")
            failed += 1
            continue
        ok = all(r["ok"] for r in stats["checks"])
        failed += 0 if ok else 1
        for r in stats["checks"]:
            print(f"   [{'OK ' if r['ok'] else 'FEHLER'}] {r['check']} {r['name']}" + ("" if r["ok"] else f"\n          {r['detail']}"))
        print("   " + json.dumps(check_gcode.summary(stats), ensure_ascii=False))
        with open(os.path.join(out, model + ".json"), "w", encoding="utf-8") as f:
            json.dump({"summary": check_gcode.summary(stats), "checks": stats["checks"]}, f, ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
