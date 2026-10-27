# core_layer_combine – Fehleranalyse Testdruck (Prusa XL, OrcaSlicer)

Stand: 27.10.2026 · Testdatei: `LayerCombinationTest_2.gcode` (XY-Kalibrierquadrat, 30 Schichten à 0,2 mm)

## Setup

- **Drucker:** Prusa XL 5T, Firmware 6.10.3
- **Slicer:** OrcaSlicer 2.5.0-dev mit dem Python-Plugin `core_layer_combine` (v0.1.1)
- **Düsen:**
  - T0 (Werkzeug 1) = **1,2 mm**: Innenwände, Sparse-Infill, inneres massives Infill
  - T1 (Werkzeug 2) = 0,4 mm: Außenwand, Ober- und Unterseite
  - Geplant ist ein Wechsel der 0,4er Düse auf T2 (Werkzeug 3), siehe unten.
- **Prinzip des Plugins:** Orca slict alles mit 0,2 mm. Beim Export löscht das Plugin für die große Düse die Bahnen in 2 von 3 Schichten. In der 3. Schicht druckt es dieselben Bahnen mit dreifachem Material, also 0,6 mm hoch bei gleicher Linienbreite. Der Vorschub wird auf das Volumenstromlimit begrenzt, hier 17,5 mm³/s.
- **Wichtig:** Die Orca-Vorschau zeigt den Zustand *vor* dem Plugin. Prüfen lässt sich das Ergebnis nur, wenn man die exportierte Datei wieder in Orca öffnet.

## Beobachtung

Schon in Schicht 2 nimmt der Drucker das Tool mit der 1,2er Düse auf, ohne damit zu drucken. Beim Wechsel kam außerdem der Fehler „Extruder motor is not spinning“.

## Ursache 1 – Plugin-Bug: leere Tool-Abschnitte (Hauptursache)

Beim Zusammenfassen löscht das Plugin nur die **fördernden Zeilen**, also G1 mit XY und E > 0. Alles andere aus den betroffenen T0-Abschnitten bleibt im G-Code stehen:

- Toolwechsel auf T0 (Parken und Aufnehmen)
- Verfahrwege und Absenken auf Schichthöhe
- Entrückziehen und Rückzug (`G1 E.8 F1800` / `G1 E-.64 F2100`)
- Wipe-Bewegungen. Die starten jetzt an einer anderen Stelle und fahren teils quer übers ganze Teil.

**Folge:** In jeder Dreiergruppe holt der Drucker T0, fährt herum, schiebt Filament vor und zurück und parkt wieder, ohne zu drucken. Im Testdruck waren das 9 leere Abschnitte, zuerst in Schicht 2 und 3. Erst in Schicht 4 (Z 0,8) druckt T0 wirklich.

**Richtige Logik:** Nach dem Löschen prüfen, ob ein Tool-Abschnitt noch druckt. Leere Abschnitte samt Bewegungen, E-Moves und Wipes entfernen. Toolwechsel, die dadurch überflüssig werden, ebenfalls entfernen. Den Rückzugsstand pro Tool nachführen:
- vor jedem Druck: 0, also voll gefördert
- vor jedem Toolwechsel: wie im Original, beim XL −2,0 mm Wechsel-Rückzug

## Ursache 2 – Orca-Einstellung: T0 druckt in Schicht 1

Das Plugin lässt die erste Schicht absichtlich unverändert. Orca weist die Innenwände aber in **allen** Schichten T0 zu, also auch in Schicht 1. Dort gilt die feste Erste-Schicht-Linienbreite `initial_layer_line_width = 0.4`. Die 1,2er Düse druckt damit 0,4 × 0,2 mm Linien. Es kommt kaum Material, und es sieht aus, als würde sie gar nicht drucken.

**Lösungen:**
- per Nachbearbeitung die T0-Bahnen aus Schicht 1 der 0,4er Düse geben, das macht `clc_cleanup.py`, oder
- Erste-Schicht-Linienbreite in % angeben, dann druckt T0 in Schicht 1 breite Linien. T0 kommt dann aber schon in Schicht 1 zum Einsatz.

## Was geprüft wurde und in Ordnung ist

- Rückzüge pro Tool gehen auf. Einzige Abweichung ist das Druckende, wie im Original.
- Kombinierte Bahnen haben den richtigen Querschnitt: ca. 0,63 mm² ≈ 1,2 × 0,6 mm.
- Der Volumenstrom ist auf 17,5 mm³/s begrenzt.
- Keine Bewegung unterhalb bereits gedruckter Höhe, also kein Kollisionsrisiko.
- Toolwechsel nutzen unverändert das Orca-XL-Template.

**Offen:** Ob die Standard-Düse am XL 17,5 mm³/s PLA bei 215 °C schafft, ist nicht geprüft. Klackert der Extruder ab Schicht 4, den maximalen Volumenstrom im Filamentprofil von T0 senken.

## Workaround: `clc_cleanup.py`

Eigenständiges Nachbearbeitungs-Skript, das auf die Plugin-Ausgabe angewendet wird:

```
python clc_cleanup.py in.gcode -o out.gcode [--big 0] [--small 1]
```

- `--big`: Tool mit der großen Düse, Standard 0
- `--small`: Tool mit der kleinen Düse, Standard 1. Bei der 0,4er Düse auf Werkzeug 3: `--small 2`

**Was das Skript macht:**
1. Leere Tool-Abschnitte entfernen: Bewegungen, verwaiste Wipes und leere Wipe-Markierungen.
2. T0-Arbeit in Schicht 1 mit Linien ≤ 0,6 mm der kleinen Düse geben und beide Toolwechsel entfernen. Der Lüfterbefehl bleibt erhalten, Z wird für den Verfahrweg angehoben.
3. Rückzugsausgleich: Abweichungen in den letzten E-Move einrechnen statt neue Ent-/Rückzüge einzufügen.

**Ergebnis beim Testdruck:** Toolwechsel 25 → 23. T0 kommt erst am Ende von Schicht 3 und druckt dann direkt die erste 0,6-mm-Schicht.

**Ziel:** Diese Logik ins Plugin `core_layer_combine` einbauen, damit kein zweites Skript nötig ist. Dafür muss der aktuelle Plugin-Code, also `core_layer_combine.zip`, ins Projekt.

## Tool-Umbelegung T1 → T2 (0,4er auf Werkzeug 3)

Die bereinigte Datei wurde nachträglich von T1 auf T2 umgestellt. Getauscht wurden:
- T-Befehle, M104/M109/M104.1 und `M862.1`
- die Heizung des ungenutzten Werkzeugs: jetzt Werkzeug 2 aus statt Werkzeug 3
- Metadaten: Filamentverbrauch, Filamenttyp, Farben und `; filament: 1,3`

**Besser für künftige Teile:** In Orca das 0,4er Filament direkt Extruder 3 zuweisen, statt den G-Code umzubauen.

## Nebenbefund – „Extruder motor is not spinning“ (#17536)

**Hat nichts mit dem G-Code zu tun.** Der Fehler trat schon vorher mit anderen Dateien und an anderen Werkzeugen auf.

- **Ursache laut Prusa:** Problem an der Steckverbindung zwischen Hauptkabel und Dwarf-Board. Die alte Steckerabdeckung hielt den Stecker zu stramm. Die Abdeckungen wurden schon vor langer Zeit abgebaut. Jetzt sitzt der Stecker ungesichert und kann bei Toolwechseln wackeln.
- **Firmware:** 6.10.3 ist aktuell, daran liegt es nicht.
- **Maßnahme:** Neue, verschraubte Abdeckung montieren. Anleitung: „How to replace the main cable connector cover (XL)“. Die Teile gibt es auf Printables unter „XL printable parts“ (Modell 449554).
  - neu drucken pro Werkzeug: `dwarf-cover-connector`, `dwarf-cover-base`
  - einmal für alle Werkzeuge: `dwarf-cover-connector jig` (Montagelehre)
  - wiederverwenden: `dwarf-cover-back`, `dwarf-cover-door`
  - Kleinteile pro Werkzeug: 3× M3x10, 2× M3nN (Sechskantmutter), 4× M3nS (Vierkantmutter)
  - Material: lieber PETG, weil der Connector beim Einsetzen der Mutter ca. 5 mm aufgebogen wird
- **Vor dem Einbau:** Stecker auf Abrieb und verbogene Pins prüfen und mit Isopropanol reinigen.
- **Bleibt der Fehler:** Prusa-Support kontaktieren (Ersatzkabel).
