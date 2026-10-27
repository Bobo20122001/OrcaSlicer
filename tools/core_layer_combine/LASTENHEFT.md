# Core Layer Combine – Lastenheft & Umsetzungsplan (OrcaSlicer-Fork)

Oct 27, 2026 · @Ole

## Ziel und Abgrenzung

Der Fork bekommt eine native Druckprofil-Einstellung **Core Layer Combine**: Eine dünne Außenhülle wird mit feiner Düse in dünnen Schichten gedruckt, der Kern (Innenwände + Infill) mit grober Düse in zusammengefassten dicken Schichten. Ziel ist mehr Festigkeit pro Druckzeit bei sichtbarer Oberfläche wie mit 0,4er-Düse.

**Referenzfall:** Prusa XL 5T, T0 = 1,2-mm-Düse (Kern, 0,6 mm), T2 = 0,4-mm-Düse auf Werkzeug 3 (3 Außenwände, 0,2 mm; vorher T1, gewechselt wegen Steckerproblem an Werkzeug 2), also 3 dünne Schichten je Kernschicht.

**Zielgruppe:** du und andere Nutzer am gemeinsamen Lab-Drucker, ohne Python-Postprocessing und ohne Spezialwissen.

**Im Scope**

- Einstellung im Prozessprofil (GUI), pro Objekt/Modifier überschreibbar
- Geometrie, Werkzeugzuordnung und Reihenfolge direkt im Slicer, kein G-Code-Nachbearbeiten
- Korrekte Vorschau, Zeit- und Materialschätzung
- Portable Windows-Exe von der SSD mit UI-Skalierung pro Rechner

**Nicht im Scope (v1)**

- Kombinierte Top-/Bottom-Flächen und Brücken (bleiben dünn)
- Adaptive bzw. variable Schichthöhe, Spiralvase, Druck „Objekt für Objekt“
- macOS/Linux-Builds, Bambu-Netzwerkfunktionen
- Upstream-PR (optional später, siehe NF-Anforderungen)

## Begriffe und Funktionsprinzip

Der neue Code muss im Kern nur eines leisten: **Innenwände über mehrere Schichten zusammenfassen**. Infill-Kombination und getrennte Filamente für Außen-/Innenwände gibt es in Orca bereits.

| Begriff | Bedeutung | Referenzwert |
| --- | --- | --- |
| Grundschicht h | Schichthöhe des Objekts, dünn | 0,2 mm |
| Hülle (Shell) | N\_S feine Wände außen, dünn, Hüllen-Werkzeug | N\_S = 3, T2, 0,4 mm |
| Kern (Core) | alles innerhalb der Hülle: N\_K grobe Wände + Infill | T0, 1,2 mm |
| Kombinationsfaktor k | Grundschichten je Kernschicht | k = 3 |
| Kernschicht | eine Extrusion mit Höhe k · h, gedruckt im obersten Layer der Gruppe | 0,6 mm |
| Gruppe | k aufeinanderfolgende Grundschichten mit gemeinsamer Kernschicht | Layer 2–4, 5–7, … |

**Ablauf je Gruppe:** T2 druckt die Hülle in Layer 1, 2 und 3 der Gruppe. Erst danach druckt T0 im Layer 3 den Kern mit 0,6 mm Höhe. Die Reihenfolge ist zwingend: Läge der Kern zuerst, würde T2 in den unteren Layern der Gruppe mit dem 0,6 mm hohen Kern kollidieren.

&#91;embedded content: Schichtfolge · zwei Gruppen mit k = 3\]

**Wenn 3 Layer nicht gehen:** Das Bild zeigt den Idealfall. Wo die Geometrie sich innerhalb einer Gruppe ändert, greift die Kaskade 3 → 2 → 1 (F-12): erst 0,6 mm anstreben, sonst 0,4 mm, sonst einzeln 0,2 mm.

**Was Orca heute schon kann (verifiziert im Code, Stand 27.10.2026):**

- *Infill combination* + *Max layer height* fasst Sparse-Infill über mehrere Layer zusammen. Wände bleiben dünn.
- Getrennte Filamente für *Outer walls*, *Inner walls*, *Sparse infill*, *Internal solid infill*. „Outer“ ist dabei nur die äußerste Wand.

**Was fehlt:** (1) Anzahl feiner und grober Wände getrennt einstellen (N\_S, N\_K), (2) Innenwände kombinieren und mit Kernschicht-Flow erzeugen, (3) Validierung und Vorschau dafür.

## Ist-Lösung: Python-Plugin core\_layer\_combine (v0.1.1)

Das Plugin setzt das Prinzip heute als G-Code-Nachbearbeitung um und ist die Referenz für den Fork: Orca slict alles mit 0,2 mm, beim Export fasst das Plugin die Bahnen der großen Düse über k Schichten zusammen. Es läuft als Orca-Slicing-Pipeline-Plugin im Schritt `psGCodePostProcess` (nur OrcaSlicer 2.5.0 Alpha/Nightly) oder standalone: `python core_layer_combine.py in.gcode -o out.gcode` (ohne `-o` wird die Eingabedatei überschrieben). Die Python-Plugin-API erlaubt in den früheren Schritten nur Lesezugriff, deshalb geht es nur über den fertigen G-Code.

**Ablauf im Plugin**

1. **Einlesen:** Schichten über `;LAYER_CHANGE`, `;Z:` und `;HEIGHT:`, Features über `;TYPE:`, Linienbreite über `;WIDTH:`, Werkzeug über `T<n>`-Zeilen am Zeilenanfang (auch mit Parametern, z. B. `T0 S1`). Als Druckbahn zählen nur `G0`/`G1` mit X/Y und E > 0; Bögen (`G2`/`G3`) werden weder gelöscht noch skaliert. Düsendurchmesser, Filamentdurchmesser und Volumenstrom kommen als Plugin aus der Orca-Konfiguration (`ctx.config_value`), standalone aus dem Einstellungsblock am Dateiende.
2. **Werkzeug wählen:** `tool = -1` nimmt unter den druckenden Werkzeugen das mit der größten Düse; ohne Düsenangaben das mit der höchsten Nummer. Druckt nur ein Werkzeug, bleibt die Datei unverändert.
3. **Abbruchbedingungen:** Mit Prime-Tower (`WIPE_TOWER_START` oder `; CP TOOLCHANGE` im G-Code) bleibt die Datei unverändert. Ein Marker (`; core_layer_combine: processed`, wird als Zeile 1 geschrieben) verhindert doppelte Verarbeitung.
4. **Warnung Linienbreite:** Druckt das Kernwerkzeug schmaler als 80 % seiner Düse, gibt es eine Warnung (Linienbreiten müssen in % stehen, z. B. 105 %).
5. **Gruppen planen:** Gierig von unten nach oben, ab der Schicht mit Index `skip_first_layers` (0-basiert, Standard 1 = zweite Schicht). Eine Schicht ist kombinierbar, wenn das Kernwerkzeug in ihr druckt und dabei kein Feature aus `excluded_features` vorkommt (Features anderer Werkzeuge zählen nicht). Aufeinanderfolgende kombinierbare Schichten kommen in eine Gruppe, solange die Höhensumme ≤ `max_combined_height` bleibt (höchstens 80 % der Düse) und die Bahnlänge des Kernwerkzeugs zu jeder Schicht der Gruppe um höchstens `similarity_tolerance` abweicht. Die erste Schicht, die eine Bedingung verletzt, **beendet** die Gruppe; die bis dahin gesammelten Schichten werden trotzdem kombiniert, sofern es mindestens 2 sind. Eine feste Kaskade 3 → 2 → 1 gibt es nicht, Zweiergruppen entstehen nur als Rest.
6. **Umschreiben:** In den unteren Schichten einer Gruppe werden die Druckbahnen des Kernwerkzeugs gelöscht. In der obersten Schicht wird E mit dem Querschnittsverhältnis nach dem Orca-Flowmodell skaliert (Rechteck mit halbrunden Enden: h · (b − h · (1 − π/4))), die Breite bleibt gleich. Bei 1,25 mm Breite ergibt das für 0,2 → 0,6 mm den Faktor ≈ 2,79, nicht 3. Nur ohne `;WIDTH:` wird mit H / h skaliert. Überschreitet eine Bahn den Volumenstrom, wird nur ihr Vorschub gesenkt; war F modal, wird er in der Folgezeile wiederhergestellt.
7. **Vorschau-Korrektur (v0.1.1):** Vor kombinierten Bahnen wird `;HEIGHT:0.6` eingefügt, danach wieder die normale Höhe, damit die G-Code-Vorschau die echte Höhe zeigt.
8. **Leere Besuche entfernen:** Ein Besuch des Kernwerkzeugs ohne verbleibende Druckbahn wird vollständig entfernt: ab der letzten Druckbahn des vorherigen Werkzeugs alle Zeilen bis einschließlich des Rückwechsels (Toolwechsel, Verfahrwege, Ent-/Rückzüge, Wipes), außer Layer- und Objekt-Markierungen. Ersetzt wird das durch den aufsummierten Rückzug des vorherigen Werkzeugs, die Layerhöhe und den letzten Lüfterbefehl. Das geschieht **nur**, wenn (a) es nicht der erste Werkzeugwechsel der Datei ist, (b) davor und danach dasselbe Werkzeug aktiv ist (A → Kern → A) und (c) der vorherige Besuch gedruckt hat. Alle anderen leeren Besuche bleiben unverändert stehen (im Testteil 30 → 16 Wechsel).

**Parameter**

| Schlüssel | Standard | Bedeutung |
| --- | --- | --- |
| `tool` | -1 | Kernwerkzeug; -1 = größte Düse |
| `max_combined_height` | 0,6 mm | Höhe der dicken Schicht; wird auf 80 % der Düse begrenzt, wenn der Düsendurchmesser bekannt ist |
| `skip_first_layers` | 1 | erste Schichten nie zusammenfassen |
| `similarity_tolerance` | 0,25 | max. Schwankung der Bahnlänge in einer Gruppe |
| `excluded_features` | Bridge, Internal Bridge, Overhang wall, Support, Support interface, Support transition, Ironing, Prime tower, Skirt, Brim | Gruppen mit diesen Features bleiben unverändert |
| `max_volumetric_speed` | 0 = aus Filamentprofil | Volumenstromgrenze in mm³/s (Test: 17,5); fehlt der Wert im Profil, keine Begrenzung |
| `filament_diameter` | 0 = aus Orca, Fallback 1,75 | für die Volumenstromrechnung |

**Nötiges Orca-Setup heute:** Orca kann nur die äußerste Wand einem eigenen Werkzeug geben. Deshalb wird das Teil im CAD in Schale (ca. 1,2 mm) und Kern geteilt und als ein Objekt mit zwei Teilen geladen: Schale auf die 0,4er-Düse mit 3 Wänden und 0 % Infill, Kern auf die 1,2er-Düse mit 1–2 Wänden. Alles mit 0,2 mm Schichthöhe, Linienbreiten in % (oder am Kern-Teil 1,25 mm), Prime-Tower aus, Arc Fitting aus (das Plugin verarbeitet keine `G2`/`G3`-Bögen). Wandgenerator **Klassisch**, weil Arachne bei 0,42 mm neben 1,25 mm Zusatzbahnen an Ecken erzeugt.

Die Plugin-README beschreibt stattdessen das einfachere Setup ohne CAD-Teilung: eine STL, 3 Wände, über *Filament für Features* nur die äußerste Wand und Ober-/Unterseite auf die 0,4er-Düse, Innenwände und Infill auf die 1,2er-Düse. Damit gibt es nur **eine** feine Außenwand statt drei. Der Plugin-Code funktioniert mit beiden Varianten, weil er nur nach Werkzeug unterscheidet. Die README nennt noch T1 für die 0,4er-Düse.

**Bekannte Schwächen (Testdruck 27.10.2026)**

- **Leere Werkzeugabschnitte:** In den unteren Schichten einer Gruppe löscht v0.1.1 nur die fördernden Zeilen. Den ganzen Besuch entfernt Schritt 8 nur unter den dort genannten Bedingungen; in allen anderen Fällen bleiben Toolwechsel, Anfahrt, Vor-/Rückzug (`G1 E.8` / `G1 E-.64`) und Wipes stehen. Der Drucker holt die 1,2er-Düse, fährt herum und parkt ohne zu drucken (9 leere Abschnitte, erstmals in Schicht 2). Die Wipes starten an falscher Stelle und fahren teils quer übers Teil. Welche Bedingung in diesen Fällen nicht erfüllt war, ist noch nicht an der Testdatei geprüft.
- **Schicht 1:** Orca gibt die Innenwände auch in Schicht 1 der 1,2er-Düse, dort aber mit `initial_layer_line_width = 0.4`. Ergebnis: 0,4 × 0,2-mm-Linien aus der 1,2er-Düse, kaum Förderung.
- **Workaround `clc_cleanup.py`** auf die Plugin-Ausgabe (`--big 0 --small 2`): entfernt die Bewegungen leerer Abschnitte und verwaiste Wipes, gibt den **ersten** Besuch der 1,2er-Düse in Schicht 1 (Linien ≤ 0,6 mm, `--first-layer-max-width`) an die kleine Düse und ersetzt dessen beide Toolwechsel durch Z-Anheben + Lüfterbefehl. Rückzugsabweichungen werden in den letzten reinen E-Move eingerechnet; findet sich keiner, wird ein neuer eingefügt (fest F1800/F2100). Toolwechsel-Blöcke erkennt das Skript an Texten aus dem XL-Template (`; filament end gcode`, `Override pressure advance`). Ergebnis: 25 → 23 Wechsel, 1,2er-Düse erst ab Ende Schicht 3.
- **Orca-Vorschau** zeigt den Zustand vor dem Plugin. Prüfen nur durch erneutes Öffnen der exportierten Datei. Zeit- und Materialangaben stimmen danach nicht mehr.
- **Ungeprüft:** ob die Standarddüse 17,5 mm³/s PLA bei 215 °C schafft.

**Geprüft und in Ordnung:** Rückzugsbilanz je Werkzeug, Querschnitt der dicken Bahnen ca. 0,63 mm² (≈ 1,2 × 0,6 mm), Volumenstromgrenze, keine Bewegung unter bereits gedruckter Höhe, Toolwechsel nutzen unverändert das Orca-XL-Template.

**Was der Fork besser machen muss:** Zusammenfassen im Slicer statt im G-Code (echte Vorschau, Zeit und Material), keine CAD-Teilung (Innenwände per Einstellung aufs Kernwerkzeug), keine leeren Werkzeugbesuche ab Erzeugung, eigene Behandlung von Schicht 1. Das sind F-16, F-36 bis F-39 und die Einstellungen weiter unten.

**Für Claude Code:** `core_layer_combine.zip` (Plugin + README), `clc_cleanup.py` und `core_layer_combine_Fehleranalyse.md` liegen im Repo unter `tools/core_layer_combine/`.

## Funktionale Anforderungen

Muss = Abnahmebedingung für v1, Soll = v1 wenn machbar, Kann = später. Optionsnamen sind Vorschläge.

### Einstellungen

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-01 | Schalter `core_layer_combine` (bool, Standard aus) in Prozess → Stärke, direkt bei „Infill combination“ | Muss |
| F-02 | `core_layer_height` in mm oder % der Kern-Düse, in v1 eine gemeinsame Höhe für Kernwände und Kern-Infill; k = abgerundet (Wert / h), v1: k = 2 oder 3; getrennte Höhen siehe F-24 | Muss |
| F-03a | `shell_wall_loops` = N\_S: Anzahl **feiner** Wände (Hülle, dünne Layer), N\_S ≥ 1 | Muss |
| F-03b | `core_wall_loops` = N\_K: Anzahl **grober** Wände (Kern, Kernschicht), N\_K ≥ 0; bei 0 grenzt der Kern-Infill direkt an die Hülle | Muss |
| F-03c | Bei aktivem Feature ersetzt N\_S + N\_K die normale Wandanzahl `wall_loops`; das Feld wird ausgegraut und zeigt die Summe | Muss |
| F-04 | Keine neuen Filament-Optionen: Hülle = Outer-wall-Filament, Kernwände = Inner-wall-Filament, Kern-Infill = Sparse/Internal-solid-Filament | Muss |
| F-05 | Linienbreiten in % beziehen sich auf die Düse des jeweils zugeordneten Werkzeugs | Muss |
| F-06 | `core_shell_overlap` in % der Kern-Linienbreite (Überlappung Kern → Hülle) | Soll |
| F-07 | Alle Optionen pro Objekt und per Modifier überschreibbar (Region-Config), also auch N\_S und N\_K je Bauteilbereich | Soll |
| F-08 | Sichtbarkeit wie bei Infill combination: Unteroptionen nur aktiv, wenn Schalter an | Soll |

### Geometrie

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-10 | Hülle je Grundschicht unverändert erzeugen (Classic und Arachne), N\_S Wände | Muss |
| F-11 | Kernfläche je Grundschicht = Innenkontur der Hülle | Muss |
| F-12 | Kaskade je Gruppe: zuerst 3 Layer kombinieren (0,6 mm), vom Rest 2 Layer (0,4 mm), was übrig bleibt einzeln (0,2 mm); Details unter der Tabelle. Schnittmengen je Stufe, Logik analog `combine_infill()` | Muss |
| F-13 | Restfläche, die weder zu dritt noch zu zweit kombinierbar ist (k = 1, z. B. an steilen Absätzen), wird je Grundschicht dünn gedruckt, mit Hüllen-Werkzeug | Muss |
| F-14 | In der kombinierten Fläche: N\_K Kernwände + Infill als Extrusion mit Höhe k · h | Muss |
| F-15 | Top-/Bottom-Solid, Brücken, Überhänge und Support-Kontakt werden nicht kombiniert | Muss |
| F-16 | Erster Layer und Raft nie kombiniert, Gruppen beginnen ab Layer 2. Layer 1 läuft komplett mit dem Hüllen-Werkzeug | Muss |
| F-17 | Gruppengrenzen sind variabel und werden nach F-22 optimiert, nicht stur ab Layer 2 abgezählt | Muss |
| F-18 | Kerninseln unter einer Flächenschwelle werden dünn gedruckt | Soll |
| F-19 | Infill-Muster bleibt über Kernschichten konsistent (Rotation je Kernschicht, nicht je Grundschicht) | Soll |
| F-20 | Internal solid infill im Kern ebenfalls kombinierbar | Kann |
| F-21 | Kernwände mit k = 4 (0,8 mm), Kaskade 4 → 3 → 2 → 1 | Kann |
| F-22 | Gruppenbildung global optimiert: dynamische Programmierung über alle Layer, Kosten = Kernfläche × Druckdurchgänge + Strafe je zusätzlichem Werkzeugwechsel | Muss |
| F-23 | Gruppengrenzen je Insel getrennt optimiert | Kann |
| F-24 | Kernwände und Kern-Infill mit getrennten Höhen (k\_I Vielfaches von k\_W); in v1 eine gemeinsame Höhe, intern schon getrennt geführt | Kann |

**Kaskade im Detail (F-12),** für eine Gruppe aus den Layern A, B, C (von unten nach oben):

1. **Stufe 3:** Fläche, die in A, B und C Kern ist → eine Extrusion 0,6 mm, gedruckt in C.
2. **Stufe 2, oberes Paar zuerst:** vom Rest die Fläche, die in B und C Kern ist → 0,4 mm, gedruckt in C. So bleibt T0 im selben Layer wie Stufe 3, es entsteht kein zusätzlicher Werkzeugwechsel.
3. **Stufe 2, unteres Paar:** vom Rest die Fläche, die in A und B Kern ist → 0,4 mm, gedruckt in B. Das kostet 2 zusätzliche Werkzeugwechsel in dieser Gruppe.
4. **Stufe 1:** alles Übrige einzeln in 0,2 mm, mit dem Hüllen-Werkzeug (F-13).

Jede Stufe nutzt dieselbe Schnittmengen- und Abstandslogik wie `combine_infill()`. Flächen unter der Mindestfläche (F-18) fallen eine Stufe tiefer. Option `core_avoid_extra_toolchanges` (Soll): Stufe 2 mit unterem Paar wird stattdessen einzeln gedruckt, wenn dir Druckzeit durch Werkzeugwechsel wichtiger ist.

**F-21 (Kann, nach v1): k\_W = 4, also 0,8-mm-Kernwände. Getrenntes 0,8-mm-Infill siehe F-24.** Die Kaskade wird verallgemeinert auf 4 → 3 → 2 → 1, Gruppen und Teilgruppen nach derselben Optimierung (F-22). 0,8 mm sind 67 % der 1,2-mm-Düse und liegen damit unter der Warnschwelle von V-02. Voraussetzung: Die max. Schichthöhe von T0 im Druckerprofil ist auf mindestens 0,8 mm gesetzt (V-01). Damit der Ausbau später klein bleibt, wird die Kaskade schon in v1 für beliebiges k programmiert und nur in der GUI auf 2–3 begrenzt.

**F-22 (Muss): Gruppenbildung global optimiert.** Ziel ist, dass im ganzen Bauteil möglichst wenig Kernfläche in dünnen oder Teilschichten gedruckt wird – weder „von unten abzählen“ noch „von oben“, sondern die beste Aufteilung des Layerstapels.

- **Verfahren:** dynamische Programmierung über die Layer eines Objekts. Für jede mögliche Gruppe (Startlayer, Größe 1 bis k\_max) werden Kosten berechnet, die DP wählt die Aufteilung mit den kleinsten Gesamtkosten. Das ist für diese Problemstellung exakt optimal, nicht nur eine Heuristik.
- **Kosten einer Gruppe:** Kernfläche × Anzahl Druckdurchgänge, die sie braucht (0,6 mm = 1 Durchgang für 3 Layer, Einzellayer = 1 Durchgang je Layer), plus Strafkosten je zusätzlichem Werkzeugwechsel. Die Gewichtung wird als Experten-Option `core_toolchange_penalty` einstellbar.
- **Innerhalb einer Gruppe** entscheidet dieselbe Kostenfunktion, ob B+C oder A+B als Paar Vorrang hat; bei Gleichstand das obere Paar.
- **Aufwand:** Layeranzahl × k\_max Gruppenbewertungen mit je wenigen Polygon-Schnittmengen; NF-04 (+25 % Slicing-Zeit) gilt weiter.
- **Grenze von v1:** Die Gruppengrenzen gelten für alle Inseln eines Objekts gleich. Getrennte Optimierung je Insel (z. B. zwei Säulen mit Top-Flächen auf verschiedenen Höhen) ist F-23 (Kann).
- **Abnahme:** Auf allen Testmodellen nie mehr Kernflächen-Durchgänge als mit dem festen 3er-Raster, beim Halter mit Absatz messbar weniger.

**F-24 (Kann, nach v1): Kernwände und Kern-Infill getrennt kombiniert.** In v1 werden Wände und Infill gleich zusammengefasst (F-02). Intern werden k\_W und k\_I aber schon getrennt geführt, damit der Ausbau klein bleibt. Später zwei Höhen: k\_W für die groben Wände, k\_I für das Infill. Beispiel: Wände 0,4 mm (k\_W = 2) für guten Verbund mit der Hülle, Infill 0,8 mm (k\_I = 4) für Druckzeit.

- **Vielfachen-Regel:** k\_I ist ein ganzzahliges Vielfaches von k\_W (0,4/0,8 und 0,6/0,6 erlaubt, 0,4/0,6 nicht). So enden Infill- und Wandgruppen auf denselben Layern, und T0 druckt nur dort.
- **Optimierung zweistufig:** F-22 optimiert zuerst die Wandgruppen. Danach fasst eine zweite DP ganze Wandgruppen zu Infill-Gruppen zusammen, mit derselben Kaskade (geht 0,8 nicht, dann 0,4).
- **Validierung:** k\_I kein Vielfaches von k\_W → Abrunden auf das nächste Vielfache mit Hinweis. k\_I < k\_W → Fehler.
- **Verhältnis zu Orca:** Die bestehende Infill combination wird bei aktivem Feature durch k\_I ersetzt (siehe V-09).

### Reihenfolge und Werkzeuge

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-30 | Kernschicht wird im obersten Layer der Gruppe gedruckt, nach den Hüllen aller k Layer | Muss |
| F-31 | Im obersten Layer: erst Hülle, dann Kern | Soll |
| F-32 | Normal 2 Werkzeugwechsel je Gruppe, höchstens 4, wenn Stufe 2 mit unterem Paar vorkommt | Muss |
| F-33 | Prime Tower und Purge funktionieren mit Gruppen (Tower wächst jede Grundschicht) | Muss |
| F-34 | Kern-Werkzeug wird über die bestehende Vorheiz-/Standby-Logik rechtzeitig aufgeheizt | Soll |
| F-35 | Funktioniert auch mit nur einem Werkzeug (z. B. 0,6er-Düse: außen 0,2, Kern 0,4) | Soll |
| F-36 | Ein Werkzeug wird nur aufgenommen, wenn es im Layer druckt; leere Abschnitte erzeugen weder Toolwechsel noch Anfahrt, Prime/Retract oder Wipe | Muss |
| F-37 | Keine fest verdrahteten Werkzeugnummern, alles folgt der Filamentzuordnung | Muss |
| F-38 | Retract-Zustand je Werkzeug konsistent: beim Drucken voll gefördert, beim Parken zurückgezogen | Muss |
| F-39 | Düsenprüfung im Start-G-Code (M862.1) passt zu den Düsen je Werkzeug | Soll |
| F-50 | Startpunkte nach einem Toolwechsel wandern von Schicht zu Schicht; Kern- und Hüllen-Werkzeug starten mindestens 5 mm auseinander | Muss |
| F-51 | Kern-Werkzeug wird nach jedem Aufnehmen gereinigt, bevor es aufs Teil geht (Prime Tower oder Purge-Linie, Menge einstellbar) | Muss |

**Lehren aus dem Plugin-Test vom 27.10.2026:** Der Druck brach ab, weil das Plugin in den Layern ohne Kerndruck nur die Förderbewegungen gelöscht hatte. Toolwechsel, Anfahrt, Vor-/Rückzug und Wipe für T0 blieben stehen. Außerdem druckte die 1,2er-Düse in Layer 1 mit 0,4 mm Linienbreite und förderte dabei kaum. Daraus folgen F-16 (Layer 1) und F-36 bis F-39 in der Tabelle oben.

**Zweiter Testdruck (Kleckse nach Toolwechsel, Layer Shift):** Vor-/Rückzug und Querschnitte im G-Code stimmen. Aber alle 18 Druckstarts nach einem Toolwechsel liegen in derselben Ecke (1,2er bei X/Y 222,2, 0,4er bei 220,2). Ohne Prime Tower landet das, was die geparkte Düse auslässt, jedes Mal dort und türmt sich auf. Z-Hop wirkt laut Filamentprofil nur unter 1,5 mm, darüber fährt die Düse ohne Anheben gegen den Haufen. Daraus folgen F-50, F-51 und V-12.

### G-Code, Vorschau, Projekt

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-40 | Flow der Kernextrusion aus Höhe k · h und Kern-Linienbreite, korrekte `;HEIGHT`/`;WIDTH`-Kommentare | Muss |
| F-41 | Max. Volumenstrom des Kern-Filaments wird eingehalten (Geschwindigkeit wird gedrosselt) | Muss |
| F-42 | Vorschau zeigt Kernextrusionen mit 0,6 bzw. 0,4 mm in Schichthöhen- und Werkzeug-Ansicht | Muss |
| F-43 | Druckzeit und Filamentverbrauch je Werkzeug korrekt | Muss |
| F-44 | Einstellungen werden in Presets und 3MF-Projekten gespeichert und geladen | Muss |
| F-45 | G-Code-Header enthält Feature-Einstellungen und Fork-Version | Soll |
| F-46 | Eigene Extrusionsrolle „Core“ für eigene Geschwindigkeit/Farbe in der Vorschau | Kann |

### Bedienoberfläche: UI-Skalierung

Orca folgt heute nur der Windows-Skalierung des jeweiligen Monitors, eine eigene Zoom-Einstellung gibt es nicht. Weil dieselbe SSD an Laptop und PC hängt, muss der Wert pro Rechner gelten, nicht pro Datadir.

| ID | Anforderung | Prio |
| --- | --- | --- |
| G-01 | Einstellung „UI-Skalierung“ unter Einstellungen: Auto (= Windows) oder 70–150 % in 10-%-Schritten | Muss |
| G-02 | Wert wird im Datadir auf der SSD gespeichert, aber je Computername getrennt (Laptop 80 %, PC 120 % mit derselben SSD) | Muss |
| G-03 | Skaliert Schrift, Abstände, Icons und die Einstellungs-Sidebar | Muss |
| G-04 | ImGui-Elemente im 3D-Fenster (Gizmos, Slider, Legende) skalieren mit | Soll |
| G-05 | Wirkt nach Neustart; live ohne Neustart | Muss / Kann |
| G-06 | Startparameter `--ui-scale 80` in `Start.bat` überschreibt den gespeicherten Wert | Kann |
| G-07 | Auto = exakt das bisherige Verhalten | Muss |

Bis das fertig ist, hilft am Laptop: Windows-Einstellungen → Anzeige → Skalierung eine Stufe herunter (z. B. 125 % → 100 %).

## Validierung und Fehlerfälle

Fehler blockieren das Slicen mit klarer Meldung, Warnungen erscheinen im Slicing-Hinweisfeld, das Slicen läuft weiter.

| ID | Bedingung | Reaktion |
| --- | --- | --- |
| V-01 | Kernschichthöhe > max. Schichthöhe des Kern-Extruders | Fehler |
| V-02 | Kernschichthöhe > 75 % der Kern-Düse | Warnung |
| V-03 | k < 2 (Kernschicht ≤ Grundschicht) | Warnung, Feature für das Objekt inaktiv |
| V-04 | Kernschichthöhe kein ganzzahliges Vielfaches von h | Hinweis mit tatsächlicher Höhe k · h |
| V-05 | N\_S < 1 (keine feine Außenwand) | Fehler |
| V-06 | Adaptive/variable Schichthöhe, Spiralvase oder „Objekt für Objekt“ aktiv | Warnung, Feature für das Objekt inaktiv |
| V-07 | Kern- und Hüllen-Werkzeug haben unterschiedliche Filamenttypen (z. B. PETG/PLA) | Warnung (Haftung) |
| V-08 | Kern-Linienbreite < Kern-Düse | Warnung |
| V-09 | Infill combination zusätzlich aktiv | Core Layer Combine hat Vorrang, Hinweis |
| V-12 | Z-Hop-Obergrenze (retract\_lift\_below) liegt unter der Objekthöhe | Warnung |

## Nicht-funktionale Anforderungen

| ID | Anforderung | Prüfung | Prio |
| --- | --- | --- | --- |
| NF-01 | Feature aus → G-Code identisch zum Vanilla-Build desselben Upstream-Commits (bis auf Header/Version) | Diff von 3 Testmodellen | Muss |
| NF-02 | Eigene Logik in eigener Datei (z. B. `CoreLayerCombine.cpp/.hpp`), in Upstream-Dateien nur kurze Hooks | Review des Diffs | Muss |
| NF-03 | Rebase auf neuen Upstream-Stand in unter einer Stunde (wenige, kleine Konfliktstellen) | erster Rebase nach 4 Wochen | Soll |
| NF-04 | Slicing-Zeit mit Feature höchstens +25 % gegenüber Feature aus | Testmodell „Halter“ | Soll |
| NF-05 | Portable Exe läuft per `Start.bat` mit `--datadir` von der SSD auf jedem Windows-PC | Test auf Lab-PC | Muss |
| NF-06 | Fork ist im Programm erkennbar (Name/Version im Titel, z. B. „OrcaSlicer CLC 0.1“) | Sichtprüfung | Soll |
| NF-07 | Alle UI-Texte über `L("…")`, deutsche Übersetzung ergänzt | Sprache DE | Soll |
| NF-08 | Tooltips erklären jede Option in 1–2 Sätzen; eine Seite Kurzanleitung für Lab-Nutzer | Laie richtet Druck ohne Hilfe ein | Muss |
| NF-09 | Code-Stil und Strukturen wie Upstream, damit ein PR möglich bleibt | Review | Kann |

## Codeeinstiegspunkte

Geprüft am Upstream-Commit `e28af4e5` (27.10.2026). Zeilennummern verschieben sich mit jedem Upstream-Stand, Funktionsnamen bleiben.

| Datei | Stelle | Relevanz |
| --- | --- | --- |
| `src/libslic3r/PrintConfig.cpp/.hpp` | `infill_combination`, `infill_combination_max_layer_height`, `outer_wall_filament_id`, `inner_wall_filament_id`, `wall_loops` | Vorlage für neue Optionen (F-01 bis F-06) |
| `src/libslic3r/Preset.cpp` | Liste der Prozess-Optionen (bei `infill_combination`) | neue Optionen in Presets aufnehmen |
| `src/libslic3r/PrintObject.cpp` | `combine_infill()` | Vorlage für F-12: Schnittmenge über k Layer, `thickness`/`thickness_layers`, `stInternalVoid` in den unteren Layern |
| `src/libslic3r/PrintObject.cpp` | `make_perimeters()`, `prepare_infill()`, `infill()`, Invalidierung bei `infill_combination` | Hook-Punkte und Neuberechnung bei Änderung |
| `src/libslic3r/PerimeterGenerator.cpp` | Wanderzeugung Classic/Arachne | Hülle mit N\_S Wänden, Kernwände mit Kern-Flow |
| `src/libslic3r/Fill/Fill.cpp` | Nutzung von `thickness_layers` | Musterkonsistenz F-19 |
| `src/libslic3r/GCode.cpp` | `split_mixed_perimeters` (Outer/Inner-Wand nach Filament trennen) | Werkzeugtrennung Hülle/Kern |
| `src/libslic3r/GCode/ToolOrdering.cpp` | Extruder je Rolle (Inner/Outer wall, Infill) | Reihenfolge und Werkzeugwechsel F-30 bis F-32 |
| `src/slic3r/GUI/Tab.cpp` | Gruppe mit `infill_combination` | Optionen in der GUI |
| `src/slic3r/GUI/ConfigManipulation.cpp` | `toggle_line("infill_combination_max_layer_height", …)` | Ein-/Ausblenden F-08, Validierung |
| `src/slic3r/GUI/GUI_Factories.cpp` | Optionen für Objekt-Einstellungen | Modifier-Unterstützung F-07 |
| `resources/profiles/Prusa/machine/Prusa XL 5T*.json` | XL-5T-Profile bis 0,8 mm Düse | für T0 = 1,2 mm eigenes Druckerprofil nötig |

**Architekturvorschlag:** ein neuer Schritt `combine_core()` direkt nach `make_perimeters()`. Er schneidet die Kernflächen je Gruppe, ersetzt in den unteren Layern die Kernwände durch Void und erzeugt im obersten Layer Kernwände mit Flow für k · h. Das Infill läuft danach über den bestehenden Kombinationsmechanismus mit k als festem Faktor. Claude Code soll diesen Vorschlag in M1 gegen den Code prüfen, bevor etwas geändert wird.

**UI-Skalierung:** Der DPI-Wert entsteht zentral in `get_dpi_for_window()` (`src/slic3r/GUI/GUI_Utils.cpp`), daraus berechnet `DPIAware` Schrift und `em_unit` (`GUI_Utils.hpp`). Ein Benutzerfaktor an dieser Stelle skaliert fast die ganze wx-Oberfläche. Die Option kommt nach `src/slic3r/GUI/Preferences.cpp`, gespeichert in der App-Config mit dem Computernamen im Schlüssel. ImGui im 3D-Fenster braucht einen eigenen Faktor.

## Umsetzungsplan

M0 liefert ohne eine Zeile Code schon einen Vergleichsdruck mit Orca-Bordmitteln. Jeder weitere Meilenstein ist ein eigener Claude-Code-Auftrag mit kleinen Commits auf `feature/core-layer-combine` und endet erst, wenn sein Gate erfüllt ist.

&#91;embedded content: Umsetzungsplan · M0 bis M6 mit Abnahmekriterien\]

M3 und M4 laufen in kurzen Schleifen: Änderung, Build, `check_gcode.py`, Korrektur. Gedruckt wird erst in M5, vorher reicht die Vorschau.

## Testplan

Jede Änderung wird an fünf Testmodellen per G-Code-Prüfskript gecheckt, gedruckt wird erst ab M5.

### Testmodelle

| Modell | Prüft vor allem |
| --- | --- |
| Würfel 20 mm | Grundfall, konstante Geometrie, F-12/F-14/F-30 |
| Kegel bzw. Pyramide | Kaskade 3 → 2 → 1 an Schrägen, F-13 |
| Halter mit Absatz, Bohrungen und Top-Fläche mitten im Teil | Inseln, Solid-Bereiche, unvollständige Gruppen, F-15/F-17/F-18 |
| Zugstab ISO 527-2 Typ 1A, liegend | Festigkeit, Referenz zum Plugin |
| Dünnwandiges Teil (Wandstärke ≈ Hülle) | Grenzfälle V-05, F-18 |

### Automatische G-Code-Checks (Python-Skript im Repo unter `tools/core_layer_combine/check_gcode.py`)

1. Alle Extrusionen von T0 haben `;HEIGHT` = 0,6 mm (nur im obersten Layer einer Gruppe) oder 0,4 mm (Stufe 2, im zweiten oder obersten Layer).
2. Keine T0-Extrusion einer Gruppe steht im G-Code vor einer Extrusion des Hüllen-Werkzeugs (T2) derselben Gruppe.
3. Höchstens 2 Werkzeugwechsel je Gruppe, 4 bei Stufe 2 mit unterem Paar. Auf jeden Werkzeugwechsel folgt mindestens eine Extrusion dieses Werkzeugs (F-36), und die Startpunkte danach liegen nicht immer an derselben Stelle (F-50).
4. Extrudiertes Volumen je mm passt zu Breite × Höhe (± 5 %), und die Retract-Bilanz je Werkzeug geht auf (F-38).
5. Feature aus: Diff gegen Vanilla-Build leer (NF-01).
6. Layerzuordnung stimmt mit der Ausgabe deines Python-Plugins überein.

### Druck- und Festigkeitstests

- Sichtprüfung und ein aufgesägter Würfel: Verbund Hülle/Kern, Lücken, Überextrusion.
- Maßhaltigkeit außen ± 0,1 mm gegenüber Vanilla-Druck.
- Zugversuch mit je 5 Proben (Mindestanzahl nach ISO 527-1) in drei Varianten: Vanilla 0,4/0,2 · Core Layer Combine · Python-Plugin. Gemessen werden Zugfestigkeit, Druckzeit und Masse.

**Vor M5:** Dwarf-Steckerabdeckung am XL erneuern. Der Fehler #17536 „Extruder motor is not spinning“ kommt vom Stecker am Werkzeugkopf, nicht vom G-Code. Bleibt er bestehen, sind Testabbrüche nicht eindeutig zuzuordnen.

## Offene Entscheidungen

- [ ] Restflächen (F-13) mit Hüllen-Werkzeug T2 dünn drucken oder mit T0 in Grundschichthöhe?
- [ ] Deckt sich das Funktionsprinzip mit deinem Python-Plugin (Reihenfolge, Restflächen, Infill-Behandlung)?
- [ ] Steht für die Zugversuche eine Prüfmaschine im Lab bzw. am Lehrstuhl zur Verfügung?
- [ ] Optionsnamen final festlegen (`core_layer_combine`, `core_layer_height`, `shell_wall_loops`, `core_shell_overlap`)
- [ ] Später Upstream-PR anstreben (dann NF-09 auf Muss)?
