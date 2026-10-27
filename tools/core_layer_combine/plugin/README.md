# Core Layer Combine (OrcaSlicer-Plugin) v0.1.1

Dünne Außenwand mit der 0,4er Düse (0,2 mm Schicht), dicke Innenwände und Infill mit der
1,2er Düse (0,6 mm Schicht), aus einer einzigen STL. Orca slicet alles mit 0,2 mm. Beim Export
fasst das Plugin die Bahnen der großen Düse über mehrere Schichten zusammen (mehr Material, gleiche Breite) und
entfernt Werkzeugwechsel, die dadurch leer werden.

## Voraussetzungen
- OrcaSlicer 2.5.0 Alpha oder Nightly (Python-Plugin-System)
- Prime-Tower **aus** (sonst lässt das Plugin die Datei unverändert)

## Installation
1. Orca: *Hilfe → Konfigurationsordner anzeigen*, darin Ordner `orca_plugins` anlegen
2. Diesen Ordner `core_layer_combine` dort hineinkopieren
3. Orca neu starten, Menü **Plugins**: „Core Layer Combine“ muss geladen sein (sonst Tab *Diagnostics*)
4. Prozess → **Sonstiges → Slicing Pipeline Plugin** → „Core Layer Combine“ auswählen (Erweitert-Modus)

## Orca-Einstellungen
- Drucker (Beispiel-Setup): Extruder 1 = T0 ganz links Düse 1,2 / Extruder 2 = T1 Düse 0,4; gleiches Filament.
  Das Plugin erkennt das Tool mit der größeren Düse automatisch.
- Multimaterial → Filament für Features:
  Äußere Wand, Ober-/Unterseite → T1 (0,4er) · Innere Wand, Sparse-Infill, inneres massives Infill → T0 (1,2er)
- Linienbreiten: Äußere Wand / Ober-/Unterseite 0,42 mm · Innere Wand / Infill / massives Infill 1,25 mm
- Wände: 3 (= 1 dünn außen + 2 dick innen), Schichthöhe 0,2 mm, Prime-Tower aus

## Plugin-Einstellungen (Plugins → Config)
| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `tool` | -1 | kombiniertes Tool; -1 = größte Düse |
| `max_combined_height` | 0.6 | max. Höhe der dicken Schicht (max. 80 % Düse) |
| `skip_first_layers` | 1 | erste Schichten nie anfassen |
| `similarity_tolerance` | 0.25 | max. Unterschied der Bahnlänge der großen Düse innerhalb einer Gruppe |
| `excluded_features` | Brücken, Überhänge, Support … | Gruppen mit diesen Features bleiben unverändert |
| `max_volumetric_speed` | 0 | mm³/s-Grenze; 0 = aus Filamentprofil, Vorschub wird ggf. reduziert |

## Prüfen
- Erste Zeile der exportierten Datei: `; core_layer_combine: processed (tool T0, max 0.6 mm)`
- Exportierte `.gcode` wieder in Orca öffnen → Vorschau *Schichthöhe*/*Werkzeug*
- Die normale Slice-Vorschau zeigt das Ergebnis nicht (Plugin läuft erst beim Export)

Standalone: `python core_layer_combine.py datei.gcode -o neu.gcode [--set max_combined_height=0.6]`
