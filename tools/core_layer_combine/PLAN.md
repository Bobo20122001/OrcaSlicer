# Core Layer Combine – Implementierungsplan (M1)

Stand 27.10.2026, geprüft gegen Upstream `b7ecf1b295` auf `feature/core-layer-combine`.
Grundlage: [LASTENHEFT.md](LASTENHEFT.md). Zeilennummern sind Momentaufnahmen, maßgeblich sind die Funktionsnamen.

## 1. Prüfung des Architekturvorschlags

Vorschlag aus dem Lastenheft: neuer Schritt `combine_core()` direkt nach `make_perimeters()`, der die Kernwände in den unteren Layern durch Void ersetzt und im obersten Layer Kernwände mit Flow für k · h erzeugt; Infill danach über den bestehenden Kombinationsmechanismus.

**Ergebnis: im Grundsatz tragfähig, aber mit fünf Korrekturen.**

| # | Befund im Code | Folge für den Entwurf |
|---|---|---|
| A | `PrintObject::make_perimeters()` erzeugt die Wände **pro Layer parallel** (`Layer::make_perimeters()` → `LayerRegion::make_perimeters()` → `PerimeterGenerator::process_classic/arachne()`). Ein Layer kennt dabei nur Nachbar-`lslices`, keine Gruppen. | `combine_core()` muss ein **serieller Schritt nach der Parallelschleife** sein, noch vor `set_done(posPerimeters)`. Passt zum Vorschlag. |
| B | Der Generator erzeugt alle `wall_loops` Wände in einem Durchgang. Kernwände nachträglich aus fertigen Loops herauszuschneiden zerlegt Loops und bricht Nahtplatzierung und Reihenfolge. | Nicht „Kernwände durch Void ersetzen“, sondern **zweistufig erzeugen**: pro Layer nur die N_S Hüllenwände (Generator mit `wall_loops = N_S`), Kernwände in `combine_core()` **neu** auf der kombinierten Kernfläche C mit einem zweiten Generator-Aufruf bei Höhe k · h. |
| C | `PrintRegion::flow(frPerimeter)` nimmt die Düse des **Inner-wall-Filaments**. Alle Innenwände (auch die 2. und 3. Hüllenwand) bekämen damit die 1,2er-Breite. | Hüllen-Innenwände brauchen einen eigenen Flow: Breite `inner_wall_line_width`, aber Düse des **Outer-wall-Filaments** (F-05). Übergabe in `LayerRegion::make_perimeters()` statt `this->flow(frPerimeter)`. |
| D | Werkzeugtrennung läuft über `is_inner_wall()` (`ExtrusionEntity.hpp`: `inset_idx > 0`). Benutzt in `region_filament()` und Layer-Werkzeugliste (`GCode/ToolOrdering.cpp`) sowie `split_mixed_perimeters` (`GCode.cpp`, `process_layer`). Hüllenwände 2..N_S würden damit zum Kernwerkzeug. | Neue Funktion `is_core_wall(entity, region_config)`: bei aktivem Feature `inset_idx >= shell_wall_loops`, sonst wie `is_inner_wall`. An den 3 Aufrufstellen ersetzen (je ein Einzeiler, NF-02). Kernwände bekommen beim Erzeugen `inset_idx += N_S` und Rolle `erPerimeter` (der äußerste Kern-Loop käme sonst als `erExternalPerimeter`). |
| E | Oberflächentypen (Top/Bottom/Solid, Brücken) entstehen erst in `prepare_infill()` (`detect_surfaces_type`, `discover_*_shells`, `process_external_surfaces`), also **nach** `combine_core()`. `combine_infill()` läuft am Ende von `prepare_infill()` und kennt sie. | `combine_core()` kann F-15 nicht über Surface-Typen prüfen. Er bestimmt die **Schalenzonen selbst** aus `lslices` der Nachbarlayer (Top: Fläche, die in den nächsten `top_shell_layers` Layern nicht vollständig bedeckt ist; Bottom analog) und nimmt sie aus C heraus. Das Infill wird in einem **zweiten Schritt** `combine_core_infill()` an der Stelle von `combine_infill()` mit den in `combine_core()` festgelegten Gruppen kombiniert (nicht mit der freien Höhenlogik von `combine_infill()`). |

Weitere Feststellungen:

- `combine_infill()` ist die richtige Vorlage für Schnittmenge, Clearance-Offset, `thickness`/`thickness_layers` und `stInternalVoid` (F-12). Die Gruppenwahl dort ist aber ein stures Raster ab Layer 1 – für F-17/F-22 nicht verwendbar, nur die Geometrielogik.
- `Fill.cpp` nutzt `surface.thickness` bereits für den Flow (`layerm.flow(role, surface.thickness)`) und `thickness_layers` für die Musterrotation. F-19 und F-40 für das Infill sind damit weitgehend vorhanden.
- Die G-Code-Ausgabe schreibt `;HEIGHT`/`;WIDTH` aus der Pfadhöhe. Haben die Kernwand-Pfade Höhe k · h, folgen Vorschau, Zeit und Material (F-40, F-42, F-43) ohne Zusatzcode. Muss in M3 verifiziert werden.
- `fill_surfaces` werden in `prepare_infill()` aus `slices` ∩ `fill_expolygons` **neu aufgebaut** (`LayerRegion::slices_to_fill_surfaces_clipped()`). Was `combine_core()` übergeben will, muss deshalb über `fill_expolygons` laufen, nicht über `fill_surfaces`.
- `Layer::make_perimeters()` fasst Regionen mit gleichen Wandparametern zusammen (`is_perimeter_compatible()` in `Layer.cpp`). Die neuen Optionen müssen dort mit verglichen werden, sonst übernimmt eine Region die Einstellung der anderen (F-07).

## 2. Zielarchitektur

```
make_perimeters()
  ├─ parallel je Layer: Layer::make_perimeters()
  │     └─ bei CLC: Generator mit wall_loops = N_S, Hüllen-Flow (Befund C)
  │        Ergebnis je LayerRegion: Hüllenwände + core_area (Innenkontur der Hülle, F-10/F-11)
  └─ NEU seriell: combine_core()                       [CoreLayerCombine.cpp]
        1. Schalenzonen je Layer aus lslices (Befund E, F-15, F-16)
        2. Gruppen per DP (F-17, F-22), Kaskade je Gruppe (F-12, F-13, F-18)
        3. je Stufe: Fläche C, Kernwände per Generator bei k·h (F-14, F-40), inset_idx += N_S
           im obersten Layer der Stufe anhängen (F-30)
        4. fill_expolygons je Layer setzen: C-Inneres nur im obersten Layer,
           in den unteren Layern C mit Clearance ausgespart
        5. Gruppenplan am PrintObject speichern
prepare_infill()
  └─ an Stelle von combine_infill(): bei CLC combine_core_infill()   [CoreLayerCombine.cpp]
        setzt thickness / thickness_layers der Kern-Infillflächen nach Gruppenplan,
        stInternalVoid in den unteren Layern (F-12, F-19, V-09)
G-Code
  └─ is_core_wall() statt is_inner_wall() an 3 Stellen (Befund D, F-04, F-37)
     Werkzeugreihenfolge im obersten Gruppenlayer: Hülle vor Kern (F-30, F-31) – ToolOrdering
```

Neue Dateien (NF-02): `src/libslic3r/CoreLayerCombine.hpp/.cpp` mit `combine_core()`, `combine_core_infill()`, DP und Hilfsfunktionen; in `src/libslic3r/CMakeLists.txt` eintragen. In Upstream-Dateien nur Aufrufe und Optionen.

## 3. Arbeitspakete

### M2 – Einstellungen (ohne Slicing-Logik)

| Paket | Dateien / Funktionen | IDs |
|---|---|---|
| Optionen `core_layer_combine` (bool, aus), `core_layer_height` (FloatOrPercent, Standard 0,6 mm), `shell_wall_loops` (Int, ≥ 1, Standard 3), `core_wall_loops` (Int, ≥ 0, Standard 1) | `PrintConfig.cpp` (`PrintConfigDef::init_fff_params`, neben `infill_combination`), `PrintConfig.hpp` (`PrintRegionConfig`), `Preset.cpp` (`s_Preset_print_options`) | F-01, F-02, F-03a, F-03b |
| Invalidierung: alle vier → `posPerimeters` (kaskadiert nach `posPrepareInfill`) | `PrintObject::invalidate_state_by_config_options()` | F-44 |
| GUI: Zeilen in der Gruppe mit `infill_combination` | `Tab.cpp` (`TabPrint::build`) | F-01 |
| Sichtbarkeit, Summe in `wall_loops`, `wall_loops` ausgegraut | `ConfigManipulation.cpp` (`toggle_print_fff_options`, `update_print_fff_config`) | F-03c, F-08 |
| Modifier/Objekt-Einstellungen | `GUI_Factories.cpp` (Optionsliste „Strength“) | F-07 |
| Regionen-Kompatibilität | `Layer.cpp` `is_perimeter_compatible()` | F-07 |

### M3 – Wände
1. `LayerRegion::make_perimeters()`: bei CLC Kopie der Region-Config mit `wall_loops = N_S` und Hüllen-Flow (Befunde B, C). Layer 0 und Raft: alle N_S + N_K Wände als Hülle (F-16).
2. `CoreLayerCombine.cpp`: `core_area` je Layer, Schalenzonen, DP, Kaskade, Kernwände erzeugen.
3. `is_core_wall()` in `ExtrusionEntity.hpp` + 3 Aufrufstellen (Befund D).
4. Prüfung: `check_gcode.py` (Lastenheft, Testplan Punkte 1–4) auf Würfel und Kegel.

### M4 – Infill, Reihenfolge, Werkzeuge
1. `combine_core_infill()` statt `combine_infill()` bei CLC (V-09 Hinweis).
2. Restflächen (F-13) mit Hüllen-Werkzeug: Region-Filament für Restinfill überschreiben – Hook in `region_filament()` (`ToolOrdering.cpp`), das laut Kommentar Tool-Ordering und G-Code-Export gemeinsam nutzen.
3. Layer 1 komplett Hüllen-Werkzeug (F-16): ebenfalls über `region_filament()` mit Layer-Index.
4. Reihenfolge Hülle → Kern im obersten Gruppenlayer (F-30/F-31), leere Besuche ausschließen (F-36): `ToolOrdering::collect_extruders()`, Reihenfolge in `reorder_extruders`/`LayerTools`.
5. Prime Tower (F-33), Startpunkt-Versatz (F-50), Reinigung nach Aufnahme (F-51).
6. Validierung V-01…V-12: `PrintObject`/`Print::validate()` bzw. Slicing-Warnungen.

### M5/M6 – laut Lastenheft (Druck, Zugversuch, UI-Skalierung G-xx, Doku NF-08).

## 4. Gruppenbildung (F-22) – Skizze

- Eingabe je Layer i ≥ 1 (Layer 0 und Raft ausgeschlossen, F-16): kombinierbare Kernfläche `K_i` = `core_area_i` ohne Schalenzonen, Brücken-/Überhangbereiche (aus `lower_slices`) und Support-Kontakt.
- Gruppe (s, n), n = 1…k_max: Kosten = Σ Kernfläche × Durchgänge nach Kaskade + `core_toolchange_penalty` × zusätzliche Wechsel. Stufe n = Fläche in allen n Layern = Schnittmenge der `K`.
- DP über i: `best[i] = min_n best[i−n] + cost(i−n+1, n)`. Aufwand Layer × k_max Schnittmengen (k_max ≤ 4); Schnittmengen inkrementell wiederverwenden (NF-04).
- Kaskade in der Gruppe (A, B, C): Stufe 3 = A∩B∩C, dann B∩C (oberes Paar), dann A∩B, Rest einzeln (F-12). Flächen unter der Mindestfläche fallen eine Stufe tiefer (F-18).
- In v1 gilt der Plan für alle Inseln eines Objekts gemeinsam; k_W und k_I intern getrennt geführt (F-24 vorbereitet), GUI auf k = 2–3 begrenzt.

## 5. Entscheidungen in M1 (ohne Rückfrage getroffen)

1. **Wände zweistufig neu erzeugen statt herausschneiden** (Befund B). Begründung: Loops bleiben geschlossen, Naht-, Scarf- und Reihenfolgelogik des Generators bleiben nutzbar.
2. **Werkzeugzuordnung über `inset_idx`** statt neuer Extrusionsrolle. Begründung: eine neue Rolle (F-46, Kann) berührt Dutzende `switch`-Stellen; `inset_idx` ist bereits für genau diesen Zweck da (Kommentar an `is_inner_wall`).
3. **Schalenzonen aus `lslices` statt aus Surface-Typen** (Befund E). Folge: `combine_core()` bestimmt Top/Bottom-Bereiche leicht konservativer als `discover_horizontal_shells()`; abweichende Flächen werden einfach nicht kombiniert (nie falsch, höchstens weniger optimal).
4. **F-03c über den gespeicherten Wert:** Bei aktivem Feature schreibt die GUI `wall_loops = N_S + N_K` und graut das Feld aus. Begründung: Profile, 3MF und CLI sehen einen konsistenten Wert; beim Abschalten bleibt die Summe als normale Wandanzahl stehen.
5. **Standardwerte:** `core_layer_height` = 0,6 mm, `shell_wall_loops` = 3, `core_wall_loops` = 1. Der Referenzfall des Lastenhefts nennt für N_K keinen Wert; README-Setup nutzte 2 dicke Wände, die CAD-Variante 1–2.
6. **`core_layer_height` als FloatOrPercent** (Prozent der Kern-Düse, F-02), Grenzen wie `infill_combination_max_layer_height`.

## 6. Risiken

- Zwei Generator-Aufrufe pro Gruppe erhöhen die Slicing-Zeit (NF-04); Kernwände nur im obersten Layer jeder Stufe erzeugen.
- Arachne auf der Kernfläche: der Kernrand ist durch die Hülle bereits geglättet; Klassisch und Arachne müssen beide getestet werden (F-10).
- `ToolOrdering` optimiert die Extruder-Reihenfolge je Layer auf wenige Wechsel; F-30 verlangt eine feste Reihenfolge. Möglicher Konflikt mit Upstream-Logik für Flush-Optimierung → in M4 klären.
- Gemischte Filament-Slots (`resolve_mixed`) und Multi-Material-Segmentierung: bei CLC vorerst nicht unterstützen (Warnung).
