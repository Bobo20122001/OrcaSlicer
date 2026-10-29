"""Slict Testmodelle über die Orca-CLI und prüft die G-Codes.

    python run_tests.py --exe build/src/Release/orca-slicer.exe --profiles profiles/reference_clc
                        [--models testeck wuerfel20 ...] [--out build/clc_runs/name] [--no-check]

Ein Profilordner enthält machine.json, process.json und filament1.json ... filamentN.json.
Ergebnis je Modell: <out>/<modell>.gcode, <modell>.json (Check-Bericht), Konsolenausgabe.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import check_gcode  # noqa: E402

ALL_MODELS = ["testeck", "wuerfel20", "pyramide", "halter", "zugstab_1A", "duennwand"]


def slice_model(exe, profiles, model, out_dir, datadir):
    files = sorted(glob.glob(os.path.join(profiles, "filament*.json")), key=lambda p: int("".join(c for c in os.path.basename(p) if c.isdigit()) or 0))
    work = os.path.join(out_dir, "_" + model)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    cmd = [exe, "--datadir", datadir, "--slice", "0",
           "--load-settings", os.path.join(profiles, "machine.json") + ";" + os.path.join(profiles, "process.json"),
           "--load-filaments", ";".join(files),
           "--outputdir", work, os.path.join(HERE, "testmodels", model + ".stl")]
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
    ap.add_argument("--profiles", required=True)
    ap.add_argument("--models", nargs="*", default=ALL_MODELS)
    ap.add_argument("--out")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    a.profiles = os.path.abspath(a.profiles)
    a.exe = os.path.abspath(a.exe)
    name = os.path.basename(os.path.normpath(a.profiles))
    out = a.out or os.path.join(REPO, "build", "clc_runs", name)
    os.makedirs(out, exist_ok=True)
    datadir = os.path.join(REPO, "build", "clc_test_datadir", "cli")
    os.makedirs(datadir, exist_ok=True)
    failed = 0
    for model in a.models:
        path, err, secs = slice_model(a.exe, a.profiles, model, out, datadir)
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
