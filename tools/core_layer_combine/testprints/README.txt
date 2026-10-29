Testdrucke fuer OrcaSlicer CLC (Prusa XL 5T)
=============================================

Alle G-Codes sind mit den Paket-Profilen erzeugt: Drucker "Prusa XL 5T CLC" (T0 = 1,2-mm-Duese,
T2 = 0,4-mm-Duese auf Werkzeug 3), Prozess "0.2mm CLC", PLA. Prime Tower an.
Vor dem Druck: Duesen pruefen (Werkzeug 1 = 1,2 mm, Werkzeug 3 = 0,4 mm) und die Dwarf-Stecker-
abdeckung erneuern (Fehler #17536), sonst sind Abbrueche nicht eindeutig zuzuordnen.

Reihenfolge und worauf achten
-----------------------------
1. CLC_testeck.gcode  (Quader 100 x 50 x 10, entspricht Testeck_CLC3_optimiert.gcode)
   - Vergleich mit dem gedruckten Referenzteil vom 29.10.: Oberflaeche, Masse, Druckzeit.
     Schaetzung 1 h 0 min bei 28 Werkzeugwechseln (Referenz: 36). Die Paket-Profile drucken
     3 feine Aussenwaende statt 1 wie die Referenz, deshalb laenger als deren ca. 42 min.
   - Erste Schicht komplett mit Werkzeug 3 (0,4 mm). Werkzeug 1 erst in Schicht 7 (Z 1,4),
     dann 0,6 mm hoch.
   - Nach jedem Wechsel: kein Klecks am Teil, Werkzeug 1 startet jedes Mal an einer anderen Stelle.
   - Kein Anfahren an hoeheren Stellen: Z-Hop ist bis zur vollen Hoehe aktiv.

2. CLC_wuerfel20.gcode  (Wuerfel 20 mm)
   - Nach dem Druck mittig aufsaegen: Verbund Huelle/Kern, Luecken zwischen den 0,4er-Waenden
     und den dicken Kernbahnen, Ueberextrusion an den Kernschichten (alle 0,6 mm).
   - Aussenmass 20,0 +/- 0,1 mm (Messschieber, beide Richtungen).

3. CLC_halter.gcode  (Halter mit Absatz, zwei Bohrungen, Top-Flaeche mitten im Teil)
   - Top-Flaeche auf Z = 6 mm geschlossen und glatt (duenn mit 0,4 mm gedruckt).
   - Bohrungen frei, keine Kernbahnen in den Bohrungswaenden sichtbar.

4. CLC_zugstab_1A.gcode  (Zugstab ISO 527-2 Typ 1A, liegend)
   - Fuer den Zugversuch 5 Stueck drucken (Mindestanzahl nach ISO 527-1), dazu je 5 Vanilla
     (0,4/0,2) und 5 mit dem Python-Plugin. Gemessen: Zugfestigkeit, Druckzeit, Masse.

Bei Problemen bitte notieren: Datei, Schicht (Display), Werkzeug, Foto. Die Pruefskripte im Repo
(tools/core_layer_combine/check_gcode.py) zeigen fuer jede Datei Werkzeugwechsel, Kernhoehen und
Volumen; Ergebnisse stehen in STATUS.md.
