# Core Layer Combine – Status

Stand 27.10.2026, Branch `feature/core-layer-combine` (nur lokal, nicht gepusht).

## Erledigt

| Meilenstein | Ergebnis | Commit |
|---|---|---|
| Unterlagen | Lastenheft, Plugin v0.1.1, `clc_cleanup.py`, Fehleranalyse im Repo | `6ef6986e1e` |
| M1 | Architekturvorschlag gegen den Code geprüft, Plan mit Dateien, Funktionen und IDs: [PLAN.md](PLAN.md) | `4a5fa52c6e` |
| M2 (libslic3r) | Optionen `core_layer_combine`, `core_layer_height`, `shell_wall_loops`, `core_wall_loops` (F-01, F-02, F-03a, F-03b): Definition, Preset-Liste, Invalidierung → `posPerimeters`, Regionen-Kompatibilität (F-07) | `1cf22a1149` |
| M2 (GUI) | Prozess → Stärke → Erweitert direkt unter „Infill combination“; Objekt-/Modifier-Liste (F-07); Unteroptionen ausgeblendet, solange der Schalter aus ist (F-08); bei aktivem Feature `wall_loops` ausgegraut und = N_S + N_K (F-03c) | `3c9cfeda96` |

Noch **keine Slicing-Logik**: Mit eingeschaltetem Feature slict Orca wie bisher, nur mit `wall_loops` = Summe.

## Prüfung

- Inkrementeller Build `build_win.bat -s --no-configure -j 8`: 0 Fehler, 13 min.
- Exe gestartet mit eigenem Datadir `build\clc_test_datadir\data`: Hauptfenster offen, reagiert, keine Abstürze, im Log nur zwei bekannte `calc_exclude_triangles`-Meldungen. Da alle Prozess-Tabs beim Start aufgebaut werden und ein unbekannter Optionsname dort sofort scheitern würde, ist das ein indirekter Nachweis, dass die vier Zeilen angelegt sind.
- **Nicht geprüft: Sichtprüfung der Zeilen in der GUI.** Ohne Bildschirmzugriff konnte ich nicht in Prozess → Stärke (Expertenmodus) klicken. Bitte einmal ansehen (siehe offene Fragen).
- Prüfweg über die Kommandozeile geht nicht: Orcas CLI nimmt keine Druckoptionen als Argumente an (auch `--infill_combination` → „Invalid option“), `--help-fff` ist im Code auskommentiert.

## Probleme unterwegs

1. **Build-Versuch 1 abgebrochen:** `C1060 Kein verfügbarer Speicher mehr im Heap` in `Format\AMF.cpp`. Ursache: Die Änderung an `PrintConfig.hpp` erzwingt fast einen Vollbuild, und 16 parallele `cl.exe` mit vorkompiliertem Header passen nicht in 32 GB. Lösung: `-j 8`. Steht jetzt in `CLAUDE.local.md`. Log von Versuch 1: `build_slicer_try1.log`.
2. **Smart App Control ist auf diesem PC aktiv** (`VerifiedAndReputablePolicyState = 1`). Beim ersten Start meldete das Programm `OrcaSlicer.dll was not loaded, error=4551`; das CodeIntegrity-Protokoll zeigt Blockaden für die unsignierte `TKGeomBase.dll`. Spätere Starts liefen ohne Blockade. Ich habe an der Einstellung nichts geändert (Sicherheitseinstellung). Relevant für NF-05 (portable Exe auf Lab-PCs), siehe offene Fragen.

## Entscheidungen (ohne Rückfrage getroffen)

Ausführlich mit Begründung in [PLAN.md](PLAN.md), Abschnitt 5. Kurz:

1. Kernwände werden **zweistufig neu erzeugt** (Hülle je Layer mit N_S Wänden, Kernwände in `combine_core()` auf der kombinierten Fläche bei k · h), nicht aus fertigen Loops herausgeschnitten.
2. Werkzeugtrennung Hülle/Kern über **`inset_idx`** (`is_core_wall()`), keine neue Extrusionsrolle.
3. Top-/Bottom-Zonen für F-15 bestimmt `combine_core()` selbst aus den Nachbar-`lslices`, weil die Surface-Typen erst danach entstehen.
4. F-03c über den **gespeicherten Wert**: `wall_loops` wird auf N_S + N_K gesetzt und bleibt beim Abschalten als normale Wandanzahl stehen.
5. Standardwerte: `core_layer_height` 0,6 mm, `shell_wall_loops` 3, `core_wall_loops` **1**.
6. `core_layer_height` als **mm oder %** der Kern-Düse (wie `infill_combination_max_layer_height`).
7. Optionsnamen wie im Lastenheft vorgeschlagen; GUI-Texte englisch im Quelltext, deutsche Übersetzung (NF-07) kommt später gesammelt.
8. Einordnung in der GUI unter Stärke → **Erweitert** neben „Infill combination“ (F-01), Sichtbarkeit nur im Expertenmodus wie die Nachbaroption.
9. Die Referenzunterlagen in `tools/core_layer_combine/` sind mit committet, damit Plan und Code auf dieselbe Fassung verweisen.

## Offene Fragen an dich

1. **Sichtprüfung GUI:** Erscheinen die vier Zeilen unter Prozess → Stärke → Erweitert (Expertenmodus), verschwinden sie beim Ausschalten, und wird „Wall loops“ ausgegraut mit der Summe? Start: `build\src\Release\orca-slicer.exe`.
2. **N_K-Standard:** 1 oder 2 Kernwände? Das README-Setup nutzte 2, die CAD-Variante 1–2.
3. **Solid-Infill im Kernbereich nahe Top/Bottom (F-15):** Es bleibt dünn – aber mit welchem Werkzeug? Nach F-04 wäre es das Internal-solid-Filament, also die 1,2er-Düse mit 0,2 mm Schichthöhe. Alternative: wie F-13 mit dem Hüllen-Werkzeug. Hängt mit der offenen Entscheidung zu F-13 im Lastenheft zusammen.
4. **Smart App Control und NF-05:** Selbst gebaute, unsignierte Exe/DLLs können auf Windows-11-PCs mit aktiver Smart App Control blockiert werden. Ist das auf dem Lab-PC eingeschaltet? Falls ja, braucht die portable Exe eine Signatur oder eine Ausnahme durch die IT.
5. **Abschalten des Features:** Soll `wall_loops` dann auf einen früheren Wert zurückspringen? Aktuell bleibt die Summe stehen (einfach und vorhersehbar, aber ein Nutzer sieht evtl. plötzlich 4 Wände).

## Nächste Schritte

1. Deine Sichtprüfung der GUI (Frage 1), danach ggf. Korrekturen an Platzierung oder Texten.
2. **M3 – Wände** nach [PLAN.md](PLAN.md), Abschnitt 3:
   - `src/libslic3r/CoreLayerCombine.hpp/.cpp` anlegen und in `src/libslic3r/CMakeLists.txt` eintragen (braucht einmal CMake-Konfiguration, also `build_win.bat -s -j 8` ohne `--no-configure`).
   - `LayerRegion::make_perimeters()`: Hülle mit N_S Wänden und Hüllen-Flow (Düse des Outer-wall-Filaments).
   - `combine_core()` mit Schalenzonen, DP (F-22) und Kaskade (F-12), Kernwände bei k · h.
   - `is_core_wall()` an den 3 Stellen in `GCode.cpp` und `GCode/ToolOrdering.cpp`.
3. `tools/core_layer_combine/check_gcode.py` für die automatischen G-Code-Checks aus dem Testplan, dazu ein XL-5T-Testprofil mit 1,2-mm-T0 (gibt es in den Prusa-Profilen nicht).
4. Deutsche Übersetzung der vier Optionen (NF-07) und Tooltips gegen NF-08 prüfen.
