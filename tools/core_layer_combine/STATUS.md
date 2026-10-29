# Core Layer Combine – Status

Stand 29.10.2026, Branch `feature/core-layer-combine`, gepusht nach `origin` (Fork Bobo20122001/OrcaSlicer).
Auftrag: selbstständig bis alle Muss-Anforderungen nachgewiesen sind und ein portables Paket als
GitHub-Release `v1.0-clc` vorliegt (Auftrag vom 29.10.2026, Regeln siehe unten).

## Arbeitsumgebung (für Wiedereinstieg nach Kontext-Kompaktierung)

- Python: `X:\Dev\OrcaSlicer\deps\build\OrcaSlicer_dep\usr\local\libpython\python.exe -I` (kein System-Python, nichts installieren).
  Bei Ausgaben mit Umlauten `PYTHONIOENCODING=utf-8` setzen.
- Build: `build_win.bat -s --no-configure -j 8` in cmd nach vcvars64 (siehe CLAUDE.local.md). Nach neuen Quelldateien ohne `--no-configure`.
- Vanilla-Vergleichsbuild: Worktree `build\vanilla` (Upstream `b7ecf1b295`), Exe `build\vanilla\build\src\Release\orca-slicer.exe`.
- Tests:
  - `run_tests.py --profiles profiles/reference_clc` – slict alle Testmodelle mit CLC und prüft mit `check_gcode.py`
  - `run_tests.py --profiles profiles/nf01 --out build/clc_runs/nf01_fork --no-check` und Vanilla nach `nf01_vanilla`,
    dann `check_gcode.py <fork> --nf01 <vanilla>` – NF-01
  - `check_gcode.py <gcode> --compare reference/Testeck_CLC3_optimiert.gcode` – Referenzvergleich
  - `roundtrip_3mf.py --profiles profiles/reference_clc` – F-44
- Profile: `profiles/gcode_to_profiles.py` erzeugt flache Profile aus dem Einstellungsblock eines G-Codes.
  `reference_clc` = Referenz-Testeck-Einstellungen + CLC (N_S = 1, N_K = 2 wie in der Referenz), `nf01` = ohne CLC,
  Brückenbreite absolut (Vanilla lehnt 100 % bei Mischdüsen ab, siehe Entscheidung 10).
- Fehlt im Repo: `clc_combine.py` und `xl_tower_cleanup.py` lagen nicht in Downloads. Gearbeitet wird mit der Notiz
  `reference/prime-tower-optimierung-xl.md` und dem Referenz-G-Code.

## Meilensteine

| Meilenstein | Stand | Commits |
|---|---|---|
| M1 Plan | erledigt, [PLAN.md](PLAN.md) | `4a5fa52c6e` |
| M2 Einstellungen | erledigt | `1cf22a1149`, `3c9cfeda96`, `4233a4431b` |
| Test-Infrastruktur | erledigt | `1c3bc0b5e8` |
| M3 Wände, Gruppen, Kern | erledigt | `b746abe4b5` |
| M4 Infill, Reihenfolge, Werkzeuge, Validierung | erledigt (Turmfaltung als Verbesserung offen) | `b746abe4b5`, `d034cbb823` |
| UI-Skalierung G-01..G-07 | erledigt (G-06 Kann: nicht umgesetzt) | `98a39d7e38` |
| Turm-Leerfahrten (eigene Option, Standard aus) | erledigt: `wipe_tower_fast_travel` | `9f623a9313` |
| Paket + Release | erledigt: Release `v1.0-clc` (Pre-Release) | siehe unten |

## Anforderungen – Nachweise

Grundlage der Nachweise: `run_tests.py --profiles profiles/reference_clc` auf allen 6 Testmodellen
(Testeck, Würfel 20, Pyramide, Halter, Zugstab 1A, Dünnwand), alle Checks 1–5 bestanden (29.10.2026).

| ID | Prio | Stand | Nachweis |
|---|---|---|---|
| F-01 | Muss | ✅ | Option `core_layer_combine` in Stärke → Erweitert; Sichtprüfung offen (Für Ole) |
| F-02 | Muss | ✅ | `core_layer_height` mm/% der Kern-Düse, k = floor(H/h); Testeck: Kern nur 0,6 mm |
| F-03a/b | Muss | ✅ | `shell_wall_loops`, `core_wall_loops` |
| F-03c | Muss | ✅ | `wall_loops` ausgegraut, intern N_S + N_K (Entscheidung fest vorgegeben) |
| F-04 | Muss | ✅ | Werkzeugwahl in `region_filament()`; Check 1/2 |
| F-05 | Muss | ✅ | dünne Flächen und Hüllenwände mit Düse des zugeordneten Filaments (`clc_flow`) |
| F-06 | Soll | ✅ | `core_shell_overlap` (Standard 15 %) |
| F-07 | Soll | ✅ | Optionen in Objekt-/Modifier-Liste, Regionen-Kompatibilität; Sichtprüfung offen |
| F-08 | Soll | ✅ | Unteroptionen ausgeblendet, wenn Schalter aus |
| F-10/F-11 | Muss | ✅ | Hülle je Layer mit N_S Wänden (Classic/Arachne), Kern = Innenkontur |
| F-12 | Muss | ✅ | Kaskade in `Planner::cascade()`; Würfel/Halter zeigen 0,4-mm-Stufen |
| F-13 | Muss | ✅ | Restflächen dünn mit Hüllen-Werkzeug (Check 1: Kern nie dünn) |
| F-14 | Muss | ✅ | Kernwände + Infill mit k · h |
| F-15 | Muss | ✅ | Schalenzonen aus Nachbar-`lslices`; Top/Bottom/Brücken dünn mit Hülle |
| F-16 | Muss | ✅ | Layer 1 komplett Hülle (Check 1) |
| F-17/F-22 | Muss | ✅ | DP mit Wechselstrafe; Abnahme siehe unten |
| F-18 | Soll | ✅ | Mindestfläche = max(minimum_sparse_infill_area, (3 · Kernbreite)²) |
| F-19 | Soll | ✅ (Code) | Fill rotiert über `thickness_layers` je Kernschicht (bestehende Orca-Logik) |
| F-30/F-31 | Muss/Soll | ✅ | Kern zuletzt im Layer (`clc_print_core_last`), Check 2 |
| F-32 | Muss | ✅ | Check 3: höchstens 4 TC je Gruppe; Testeck 28 TC bei 14 Gruppen |
| F-33 | Muss | ✅ (mit Einschränkung) | Turm folgt der Werkzeugliste, TC nur an Gruppengrenzen; Sparse-Schicht zwischen den Wechseln wird nicht gefaltet (47 statt 36 Turmschichten, aber 40 % weniger Turmmaterial). Siehe offene Punkte |
| F-36 | Muss | ✅ | Check 3: keine leeren Besuche |
| F-37 | Muss | ✅ | keine festen Werkzeugnummern; Referenz nutzt T1, Paket T2 |
| F-38 | Muss | ✅ | Check 4: Retract-Bilanz |
| F-40 | Muss | ✅ | Check 4: Volumen je mm ± 5 %, `;HEIGHT` = k · h |
| F-41 | Muss | ✅ | Check 5: Spitze 17,5 mm³/s = Grenze, keine Überschreitung |
| F-42 | Muss | ✅ (G-Code) | `;HEIGHT:0.6` an allen Kernbahnen; Vorschau-Sichtprüfung offen (Für Ole) |
| F-43 | Muss | ✅ | Filamentangaben im Header = Summe der Extrusionen (T0 4195 mm ↔ 10 090 mm³), Zeit 42:06 |
| F-44 | Muss | ✅ | `roundtrip_3mf.py`: 7/7 Optionen im 3MF, G-Code nach Laden identisch |
| F-45 | Soll | ✅ | Optionen stehen im Einstellungsblock des G-Codes; Fork-Version offen (NF-06) |
| F-50 | Muss | ✅ (geändert) | Kernnaht wandert je Layer (Goldener Schnitt), ≥ 5 mm von der Hüllennaht; siehe Änderungsvorschlag 2 |
| F-51 | Muss | ✅ | Validierung: zwei Werkzeuge ohne Prime Tower → Fehler |
| V-01..V-09, V-12 | – | ✅ (Code) | `clc_validate()`; V-03/V-06 als Fehler statt Warnung (Änderungsvorschlag 3) |
| NF-01 | Muss | ✅ | 6/6 Modelle: Fork mit Feature aus = Vanilla (0 Zeilen Abweichung außer Header/neue Optionen) |
| NF-06 | Soll | ✅ | Titel „… - OrcaSlicer CLC 1.0“ (im Paket-Start bestätigt), G-Code-Header `(CLC 1.0)` |
| NF-02 | Muss | ✅ | Logik in `CoreLayerCombine.cpp/.hpp`, Hooks in Upstream-Dateien 3–26 Zeilen |
| G-01..G-05, G-07 | Muss/Soll | ✅ (Code) | Einstellungen > Allgemein > „UI scale“; Faktor auf DPI und Schriftgröße; Schlüssel `ui_scale_<Computername>`; Wirkung visuell offen (Für Ole). G-06 (Kann) nicht umgesetzt |
| NF-05 | Muss | ✅ | Zip entpackt, `Start.bat` startet ohne Assistent mit „Prusa XL 5T CLC“ / „0.2mm CLC“ / „PLA @XL CLC“; CLI-Slicen aller 6 Modelle mit Exe und Profilen aus dem Zip besteht alle Checks. Test auf Lab-PC offen |
| NF-08 | Muss | ✅ | Tooltips je Option, LIESMICH.txt (1 Seite) im Paket; Laientest offen |

**F-22-Abnahme** (Log `Core layer combine: ... core passes`):

| Modell | DP, Strafe 0 | Raster 3 | DP, Strafe 100 (Gruppen) | Raster (Gruppen) |
|---|---|---|---|---|
| Halter | 28 277 mm² | 28 967 mm² | 28 277 (31) | 28 967 (30) |
| Pyramide | 23 625 | 23 625 | 24 508 (34) | 23 625 (42) |
| Würfel 20 | 11 479 | 11 849 | 11 479 (31) | 11 849 (30) |
| Testeck, Zugstab, Dünnwand | gleich | gleich | gleich | gleich |

Mit Strafe 0 nie mehr Durchgänge als das Raster, beim Halter −2,4 % → Abnahme erfüllt. Mit der Standard-Strafe
tauscht die DP bei der Pyramide 3,7 % mehr Durchgänge gegen 16 Toolchanges weniger (Gesamtkosten 31 308 < 32 025).

**Referenzvergleich Testeck** (`reference_clc` gegen `Testeck_CLC3_optimiert.gcode`):

| | Fork | Referenz (gedruckt) | Vanilla |
|---|---|---|---|
| Toolchanges | **28** | 36 | 50 |
| Kernhöhen T0 | nur 0,6 mm | 0,2 / 0,4 / 0,6 / 1,2 mm | 0,2 mm |
| Objektvolumen T0 / T1 | 9 414 / 9 234 mm³ | 18 828 / 3 046 mm³ | 16 280 / 3 046 mm³ |
| Turmschichten | 47 | 36 | 49 |
| Turmvolumen | 1 981 mm³ | 3 333 mm³ | 3 326 mm³ |
| Geschätzte Druckzeit | 42:06 | 41,9 min laut Notiz (Header veraltet: 50:06) | 48:50 |

T1 druckt mehr, weil Solid-Infill nahe Top/Bottom jetzt mit dem Hüllen-Werkzeug läuft (feste Entscheidung zu F-15).
Die Referenz skaliert den Kernfluss pauschal (+5,5 % gegenüber dem Orca-Flowmodell) und druckt T0 auch dünn.

## Entscheidungen

1. Kernwände werden zweistufig erzeugt: Hülle je Layer mit N_S Wänden, Kernwände je kombiniertem Stück neu bei k · h.
2. Werkzeugtrennung über `inset_idx`: Kernwände `>= N_S`, Kern-Infill/-Lückenfüllung mit `CLC_CORE_FILL_TAG`.
3. Schalenzonen (F-15) aus Nachbar-`lslices` mit max(Schichtanzahl, Dicke/h) Layern.
4. Die Füllflächen bleiben bis nach der Surface-Klassifizierung vollständig; danach werden die unteren Layer zu
   `stInternalVoid` (wie `combine_infill()`). Sonst macht „ensure vertical shell thickness“ den Kern massiv.
5. Standardwerte: `core_layer_height` 0,6 mm, `shell_wall_loops` 3, `core_wall_loops` 2 (fest vorgegeben),
   `core_shell_overlap` 15 %, `core_avoid_extra_toolchanges` an, `core_toolchange_penalty` 100 mm² (Experte).
6. Solid-Infill im Kern nahe Top/Bottom und Restflächen: Hüllen-Werkzeug in Grundschichthöhe (fest vorgegeben).
7. `wall_loops` wird nicht überschrieben, nur ausgegraut (fest vorgegeben).
8. Prime Tower ist bei zwei Werkzeugen Pflicht (Validierungsfehler), erfüllt F-51.
9. Infill combination wird für CLC-Regionen abgeschaltet (V-09), Hinweis als Warnung.
10. Config-Prüfung der Brückenbreite in % bei Mischdüsen korrigiert (Upstream-Fehler: 100 % war nie gültig);
    `Print::validate()` prüft ohnehin je Werkzeug gegen dessen Düse. Kein Einfluss auf G-Code (NF-01 bestätigt).
11. F-50 als Seam-Versatz der Kernwände in `GCode::extrude_loop` (Goldener Schnitt über die Layer-ID, ≥ 5 mm).

## Änderungsvorschläge Lastenheft

1. **F-33 (umgesetzt mit Zustimmung vom 29.10.):** Turm folgt der Werkzeugliste statt „wächst jede Grundschicht“.
2. **F-50:** Wandern der Startpunkte nur für das Kern-Werkzeug fordern. Die Hülle behält die Naht-Einstellung des
   Nutzers (sichtbare Oberfläche); ihr Start nach dem Wechsel liegt hinter der Reinigung auf dem Prime Tower, der
   mit F-51 Pflicht ist – die Kleckse aus dem zweiten Testdruck entstanden ohne Turm. Abstand Kern ↔ Hülle ≥ 5 mm
   bleibt gefordert und ist umgesetzt.
3. **V-03 und V-06 als Fehler statt „Warnung, Feature inaktiv“:** Ein stilles Abschalten pro Objekt würde die
   Werkzeugzuordnung (Hülle/Kern) inkonsistent machen; ein klarer Fehler mit Hinweis ist für Lab-Nutzer eindeutiger.
4. **F-22-Abnahme:** „nie mehr Kernflächen-Durchgänge als das Raster“ gilt für `core_toolchange_penalty = 0`.
   Mit Strafe > 0 ist der Maßstab die Gesamtkostenfunktion aus F-22 (Durchgänge + Wechselstrafe); dort ist die DP
   nie schlechter als das Raster (nachgewiesen auf allen 6 Modellen).

## Abschluss 29.10.2026

- Release: `v1.0-clc` (Pre-Release) auf github.com/Bobo20122001/OrcaSlicer mit `OrcaSlicer-CLC-v1.0-win64.zip` (226,6 MB).
- Paket-Test: Zip in leeren Ordner entpackt, `Start.bat` gestartet: Fenster „Unbenannt - OrcaSlicer CLC 1.0“,
  reagiert, kein Einrichtungsassistent, Log: Drucker „Prusa XL 5T CLC“, Prozess „0.2mm CLC“, Filament
  „PLA @XL CLC 1.2mm“ ausgewählt, keine Code-Integrity-Blockade. Danach per CLI mit Exe und Datenverzeichnis aus dem
  Zip alle 6 Testmodelle gesliced: alle Checks bestanden (Testeck 28 Toolchanges, Kern nur 0,4/0,6 mm).
- Regression vor dem Release: `reference_clc` 6/6 bestanden, Paket 6/6 bestanden, NF-01 6/6 ohne Abweichung,
  3MF-Rundlauf identisch.
- Kein Laufwerk D:\ vorhanden – Entpacken nach D:\OrcaFork entfällt.
- Paket-Entscheidungen: Turmdrehung 0° (die 90° des Prusa-Profils ragen an der Standardposition über das Bett),
  Sprache Deutsch, Modus „Erweitert“, Z-Hop ohne Höhengrenze (`retract_lift_below` 0, V-12), max. Schichthöhe T0 0,8 mm.
- Verbleibend: Drucktests (testprints/README.txt), GUI-Sichtprüfungen („Für Ole zu prüfen“), Turmfaltung F-33,
  G-06, NF-07 (deutsche Übersetzung der neuen Optionen; die Oberfläche ist sonst deutsch).

## Blocker

– keine –

## Offene Punkte / nächste Schritte

1. Drucktests nach `testprints/README.txt` (Testeck, Würfel aufsägen, Halter, 5 Zugstäbe).
2. F-33 Turmfaltung: Sparse-Turmschicht zwischen zwei Wechselschichten in die folgende Kern-Wechselschicht falten
   (wie Prototyp). Erst nach Drucktests, weil es das Ramming/Unload im Turm berührt.
3. NF-07: deutsche Übersetzung der neuen Optionen (`localization/i18n/de`), G-06 `--ui-scale` (Kann).
4. Fehlende Skripte `clc_combine.py` / `xl_tower_cleanup.py` ins Repo legen, falls der Vergleich vertieft werden soll.

## Für Ole zu prüfen

1. GUI: Prozess → Stärke → Erweitert (Expertenmodus): 7 CLC-Zeilen, ausgeblendet bei Schalter aus, „Wall loops“ ausgegraut bei Schalter an.
2. Vorschau nach dem Slicen (F-42): Ansicht „Schichthöhe“ zeigt Kernbahnen mit 0,6 mm, Ansicht „Werkzeug“ Kern = T0.
3. Objekt-/Modifier-Einstellungen: CLC-Optionen über „Einstellung hinzufügen → Stärke“ verfügbar (F-07).
4. UI-Skalierung: Einstellungen > Allgemein > „UI scale“ z. B. 80 %, Neustart: Schrift, Abstände, Icons und Sidebar kleiner?
   Am zweiten PC mit derselben SSD bleibt dort „Auto“ (G-02)?
5. Lab-PC: Paket per `Start.bat` starten (Smart App Control / SmartScreen, siehe LIESMICH.txt).
