# Prime-Tower-Leerfahrten am Prusa XL (WipeTower2 / type2) – Befund & Fork-Ansatzpunkte

Testdatei: rectangular_6__0.2mm_PLA (50 Schichten, 50 Toolchanges T0=1,2 / T1=0,4), 28.10.2026.
Post-Processor `xl_tower_cleanup.py` spart ca. 3,4 min (~7 %), Extrusionen bitgleich verifiziert.

## Unnötige Bewegungen je Toolchange
| Was | Quelle (Orca main) | Abschalten im Slicer |
|---|---|---|
| Altes Tool fährt nach dem Ramming mit F2400 zum Boxanfang zurück | WipeTower2.cpp `toolchange_Unload()`, `writer.travel(pos, 2400.f)` nach „; Ramming end" | `filament_multitool_ramming = 0` (entfällt mit Ramming) |
| Retract + Trocken-Spirale F600/F240 nach Pickup („BBS gap wall ironing") | WipeTower2.cpp `toolchange_Wipe()`, Block `m_use_gap_wall …` | `prime_tower_skip_points = 0` bzw. `filament_tower_ironing_area = 0` (nur die Spirale) |
| Umweg-Routing ums Turm-BBox (inkl. Brim) zur Wandöffnung | GCode.cpp `WipeTowerIntegration::generate_path_to_wipe_tower()` + Aufrufer | hängt an skip_points; im Fork: Direktfahrt für Toolchanger |
| Doppelte Positionierung nach Pickup (Restore-Pos + Turm-Start) | GCode.cpp append_tcr / „Move to start pos" | – |
| Leerfahrten im Turm mit Druck-F (Writer `travel(x,y,f=0)` = modal) bzw. 7200 | WipeTower2.cpp `WipeTowerWriter2::travel` Default | im Fork: Default = travel_speed |

## Weitere Befunde
- CLC-Plugin war in der Datei aktiv konfiguriert, hat aber nichts kombiniert (T0 druckt jede 0,2er Schicht).
- Bestätigt (28.10.): Ohne Prime Tower kombiniert CLC korrekt, mit Prime Tower nicht → Plugin/Fork muss mit Turm zusammenspielen.
- T0 ist volumenstrombegrenzt (17,5 mm³/s → ~77 mm/s bei 1,2×0,2) → Schichtkombination bringt für T0 keine Druckzeit, nur weniger Toolchanges ab Faktor ≥3.
- `thick_internal_bridges = 1` mit 1,2er Düse: Brückenschicht 1,13 mm² Querschnitt, ~3,7 min für eine Schicht.
- Bodenschicht mit T1 (0,4) bei 25 mm/s: ~9 min = größter Einzelposten.
- Unload-Linie des alten Tools ist im Turm tragend (stützt den Box-Perimeter der nächsten Schicht) → nicht per Post-Processing löschen.

## CLC + Prime Tower – Zielbild
- Turm folgt ToolOrdering: T0 darf nur auf der jeweils obersten Schicht eines Kombi-Blocks in `LayerTools::extruders` stehen, dann plant `WipeTower2::plan_toolchange` automatisch nur dort Toolchanges.
- Reihenfolge je Block (Faktor n): T1 druckt Schichten k…k+n−1, auf k+n−1 Wechsel T1→T0 (Kern n×h), auf k+n Wechsel T0→T1 → 2 Toolchanges pro n Schichten.
- Schichten dazwischen = Sparse-Turmschichten; Orca main kann sie falten (`wipe_tower_sparse_layers_combination`, `combine_sparse_wipe_tower_layers()` in WipeTower.cpp, Flag `combined_away`). Toolchange-Schichten werden dabei nie gefaltet.

## Prototyp als Post-Processing: `clc_combine.py` (28.10.)
- Kombiniert T0-Kern (nur Schichten mit Inner wall + Sparse infill, hier L4–L44) in 3er-Blöcken (erster Block 2 Schichten, Rest nicht teilbar); Pfade der Block-Top-Schicht, E × Höhenverhältnis (volumenerhaltend), F auf 17,5 mm³/s gedeckelt.
- Turm: Schichten nur bei Toolchanges; Höhe = Abstand zur letzten Turmschicht. Ergebnis je Block: T1-Turmschicht 0,2 mm (Blockanfang, T0→T1) + T0-Turmschicht 0,4 mm (Block-Top, T1→T0). Exakt 0,6 wie der Kern geht nicht, weil die 0,4er-Düse max. 0,3 mm Schicht kann (max_layer_height im Profil).
- In den dicken T0-Turmschichten druckt T0 den Unload-Streifen (statt T1-Ramming bei 0,4 mm Höhe); T1 parkt direkt vom Objekt.
- Ergebnis Testeck: Toolchanges 50 → 36, Schätzung 48,2 → 41,9 min (inkl. `xl_tower_cleanup.py`), Objekt-E T1 identisch, T0 −0,3 %.

## Drucktest 29.10.2026
- `Testeck_CLC3_optimiert.gcode` (Ausgabe von `clc_combine.py` + `xl_tower_cleanup.py`, mit Prime Tower) hat am Prusa XL einwandfrei gedruckt. Diese Datei ist die Referenz für das Verhalten des Forks mit Prime Tower.
