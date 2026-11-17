# Gymnasium Sek I: Vorgaben der Bundesländer

Referenz für spätere Erweiterungen des Stundenplan-Generators auf andere
Bundesländer. Das Programm wird zuerst für **NRW G9** verlässlich gemacht;
dieses Dokument hält fest, was die anderen Länder anders regeln und was
dafür im Programm fehlt.

- **Stand der Zahlen:** KMK-Übersichten für das Schuljahr 2025/2026
  (Stand Januar 2026), NRW- und Bayern-Vorschriften abgerufen im
  November 2026. Vor einer Umsetzung neu prüfen: G8/G9 ist in mehreren
  Ländern im Umbau.
- **Einheit:** Unterrichtsstunden zu 45 Minuten pro Woche.

## 1. Vorgaben je Land

| Land | Gymnasium | Schülerstunden pro Woche, Sek I | Lehrerstunden |
|---|---|---|---|
| BW | G9 neu ab 2025/26 (Kl. 5–6 aufwachsend), darüber G8 | G9 neu: 28, 29 in Kl. 5–6 (plus Poolstunden); G8 bisher: 199 über Kl. 5–10 | 25 (27 mit Lehrbefähigung nur Sek I) |
| BY | G9 | 30(+1/+2), 30, 30, 30, 31,5, 34 | 23–27, je nach Fächern |
| BE | G8, in der Regel ab Kl. 7 | 33–34 in Kl. 7–10 (32 in Kl. 5–6, wo angeboten) | 26 |
| BB | G8, ab Kl. 7 | 32, 32, 34, 35 | 25, ab 1.2.2026: 26 |
| HB | G8, Sek I = Kl. 5–9 | mindestens 161 über Kl. 5–9 (Kontingent) | 27 in Sek I, 25 in Sek II, 26 gemischt |
| HH | G8 | 30, 31, 34, 34, 34, 34 | keine Pflichtstunden, Faktorenmodell (Sek I im Schnitt ca. 25,1) |
| HE | G8 oder G9 je Schule | G9: 57 (5–6) + 118 (7–10) + 4–6; G8: 60 + 100 (7–9) + 5–6 | 25,5 (ab 61 Jahren: 25) |
| MV | G8, ab Kl. 7 | 32, 34, 35, 37 | 23–27, je nach Oberstufen-Einsatz |
| NI | G9 | 29, 30, 30, 30, 31, 31 | 23,5 |
| NW | G9 (G8 weiter in der APO-S I) | G9: 28–30 in Kl. 5–6, 30–33 in Kl. 7–10, gesamt 182–188 (KMK-Übersicht: 180–188); G8: 163 über Kl. 5–9 | 25,5 |
| RP | G9; G8 an Ganztagsschulen | G9: 30, 30, 30, 30, 31, 30; G8: 30, 30, 33, 34, 35 | 24 |
| SL | G9 aufwachsend seit 2023/24, G8 auslaufend | G9: 28, 28, 30, 30, 30, 32 | 26 (25 ab 8 Std. Oberstufe) |
| SN | G8 | mindestens 29, 31, 32, 33, 35, 36, dazu 7 flexible Stunden | 26 |
| ST | G8 | 30, 30, 34, 34, 34–35, 34 | 25, plus 1 Vorgriffsstunde bis 31.7.2028 |
| SH | G9, G8 möglich | G9: 55 (5–6) + 123 (7–10); G8: 63 + 105 (7–9) | 25,5 (andere Lehrkräfte 27) |
| TH | G8 | 62 (5–6), 67 (7–8), 68 (9–10), je für zwei Jahrgänge | 26 (23–26 mit Oberstufe) |

Alle Länder kennen Altersermäßigungen, Ermäßigungen bei
Schwerbehinderung und Teilzeit-Regeln. Sie verändern die Stundenzahl der
einzelnen Lehrkraft, nicht die Planung selbst.

## 2. Vier Familien

Innerhalb einer Familie unterscheiden sich die Länder fast nur in den
Zahlen der Stundentafel, nicht in der Struktur.

| Familie | Länder | Gemeinsamkeiten |
|---|---|---|
| A: G9, Kl. 5–10 | NI, RP, SL, SH, HE (G9), NW (G9) | 28–33 Std./Woche, 176–188 über die Sek I, passt in ein 5×7-Raster |
| B: G8, Kl. 5–10, nie umgestellt | SN, ST, TH | 29–36 Std./Woche, 196–203 über die Sek I |
| C: G8, Gymnasium ab Kl. 7 | BE, BB, MV | 32–37 Std./Woche, 132–138 über Kl. 7–10 |
| D: G8-Form in G9-Ländern | NW, RP, HE, SH, HB (SL auslaufend) | Sek I endet nach Kl. 9, 30–35 Std./Woche, 159–168 über Kl. 5–9 |

- Engstes Paar insgesamt: NI und RP (beide 181 Stunden, fast gleiche
  Verteilung je Jahrgang).
- Engstes G8-Paar: ST und TH (196–197 Stunden über Kl. 5–10).
- Lehrerstunden in Familie A: NW, HE, SH je 25,5; NI 23,5; RP 24; SL 26.
- Lehrerstunden in Familie B: faktisch 26 in allen drei Ländern.

Ohne Familie:

- **Bayern:** G9 mit ähnlicher Summe (187,5), aber sechs
  Ausbildungsrichtungen, 2. Fremdsprache ab Kl. 6, 3. Fremdsprache ab
  Kl. 8 (sprachlicher Zweig), 34 Stunden in Kl. 10.
- **Baden-Württemberg:** im Umbau; die neuen Tafeln für die höheren
  Klassen stehen noch nicht in der KMK-Übersicht.
- **Hamburg:** Zahlen wie Familie B (197 über Kl. 5–10), aber keine
  festen Lehrerstunden.

## 3. Regeln mit Einfluss auf den Stundenplan

**Kontingentstundentafeln.** NW, BW, HB, HE, RP und SH geben Summen über
mehrere Jahrgänge vor; die Schule legt die Verteilung je Jahrgang fest.

**NRW, Tagesablauf (BASS 12-63 Nr. 3):**

- Fünf-Tage-Woche als Regel; mit Zustimmung des Schulträgers Unterricht
  an höchstens zwei Samstagen im Monat.
- Sek I: höchstens 360 Minuten Unterricht pro Tag, am Vormittag
  höchstens 300 Minuten (315 mit Beschluss der Schulkonferenz und
  Zustimmung des Schulträgers).
- Mittagspause 60 Minuten, um bis zu 15 Minuten kürzbar.
- Ohne Ganztag: verpflichtender Nachmittagsunterricht an höchstens einem
  Nachmittag (Kl. 5–7) bzw. zwei Nachmittagen (Kl. 8–9).
- Mit Ganztag: mindestens ein Nachmittag pro Woche bleibt frei.
- Die 45-Minuten-Einheit darf nicht gekürzt werden; andere Zeiteinheiten
  beschließt die Schulkonferenz.
- Keine Vorschrift zu Doppelstunden oder zur Verteilung eines Fachs über
  die Woche.

**NRW, Stundentafel G9 (APO-S I, Anlage 3a):** 182 Kernstunden (59 in
Kl. 5–6, 123 in Kl. 7–10) plus 0–6 Ergänzungsstunden, gesamt 182–188;
Informatik mit 2 Stunden in Kl. 5–6 (oder nur Kl. 6); 2. Fremdsprache in
der Regel ab Kl. 7 (möglich ab Kl. 5), Wahlpflichtunterricht in
Kl. 9–10, Fach "Wirtschaft-Politik", "Religionslehre/Praktische
Philosophie". Mindeststunden über die Sek I: Geschichte und
Wirtschaft-Politik je 8, Erdkunde 7, Biologie, Chemie, Physik je 7,
Kunst und Musik je 7; Chemie in der Regel ab Kl. 7. Eine dritte
Fremdsprache im Wahlpflichtbereich braucht 8 Stunden (2 davon
Ergänzungsstunden). Die Schulkonferenz kann bis zu zwei Kernstunden
zwischen den Kontingenten verschieben.

Die ältere, als "auslaufend" gekennzeichnete Fassung ohne Informatik
hatte 180 Kernstunden (57 + 123) plus 0–8 Ergänzungsstunden. Welche
Fassung für welchen Jahrgang gilt, ist vor einem Echteinsatz zu prüfen.
Die eingebaute Beispielverteilung (`config/nrw_g9.py`, Tabelle im
README) folgt der Fassung mit Informatik.

**NRW, Lehrerstunden (VO zu § 93 Abs. 2 SchulG):** 25,5 am Gymnasium; aus
schulischen Gründen bis zu sechs Monate um bis zu sechs Stunden über-
oder unterschreitbar, Ausgleich im Schuljahr. Altersermäßigung: 1 Stunde
ab 55, 3 Stunden ab 60 (Vollzeit).

**Bayern (GSO, Anlage 1):** Fächer wie Natur und Technik, Wirtschaft und
Recht, Politik und Gesellschaft, Geographie; Profilstunden;
Intensivierungsstunden, auch in kleineren Gruppen; ein Modul mit 0,5
Wochenstunden als Blockveranstaltung; Epochenunterricht in Pflichtfächern
zulässig; Kunst und Musik in Kl. 8–9 im jährlichen Wechsel möglich.

**KMK:** mindestens 265 Jahreswochenstunden von Kl. 5 bis zum Abitur.

## 4. Stand des Programms (November 2026)

Die Einstellung `bundesland` steuert nur eine Warnung (den
Wochenstundenrahmen für NRW); keine Regel des Solvers hängt davon ab.
Alles andere Landesspezifische muss über die Eingabedaten kommen.

| Anforderung | Stand | Anmerkung |
|---|---|---|
| Unterrichtsverteilung vor der Planung festgelegt | Ja | Blatt "Unterrichtsverteilung". Ermäßigungen, Hamburger Faktoren und bayerische Fachregeln sind damit schon vor dem Solver entschieden. |
| Stundenzahl je Lehrkraft, Teilzeit | Ja | Soll-Deputat je Lehrkraft, auch halbe Stunden (25,5 oder 23,5); der Plan selbst hat ganze Stunden, die Abweichung vom Soll wird ausgewiesen. |
| Stundentafel je Jahrgang | Ja | Über das Excel-Blatt "Stundentafel". |
| Eingebaute Standard-Stundentafel | Ja (NRW G9) | Beispielverteilung nach Anlage 3a: 30, 30, 32, 32, 32, 32 (Summe 188). Die Testdaten aus `generate` nutzen noch die alte Tafel, die keinem Land entspricht. |
| G8 und G9 in verschiedenen Jahrgängen einer Schule | Ja | Jeder Jahrgang hat eine eigene Zeile. |
| G8- und G9-Klassen im selben Jahrgang | Nein | Der Import kennt eine Tafel je Jahrgang (das Datenmodell je Klasse könnte es). |
| Schulen mit Kl. 7–10 oder 5–9 | Ungetestet | Konfigurierbar; die eingebaute Tafel deckt nur 5–10 ab. |
| Fächer aller Länder | Ja | Freie Fächerliste im Excel-Blatt "Fächer" (Kürzel, Fachraum, Doppelstunde je Fach). |
| Wochen über 35 Stunden | Nein | Eine 8. Stunde ist konfigurierbar, aber keine Regel für Mittagspause, Nachmittage je Klasse oder Minuten pro Tag. |
| Religion/Ethik, Wahlpflicht | Ja | Kopplungen. |
| Sprachen-Schienen | Ja | Kopplungstyp `band` mit "Fach der Stundentafel" (z.B. Französisch/Latein für "2. Fremdsprache"). Getestet mit kleinen Datensätzen; der Test in Schulgröße folgt mit den NRW-Testdaten. |
| Zweige, geteilte Gruppen | Ungetestet | Vermutlich als Kopplung abbildbar. |
| Halbe Stunden, Epochenunterricht, A/B-Wochen | Nein | Nur ganze Wochenstunden. |
| Andere Stundenlängen als 45 Minuten | Teilweise | Zeiten konfigurierbar; die Schule rechnet ihre Tafel selbst um. |
| Samstagsunterricht | Teilweise | 6-Tage-Woche geht; "zwei Samstage im Monat" nicht. |
| Höchstens eine Stunde oder ein Doppelblock je Fach und Tag (C15) | Eigene Regel | Kein Land schreibt sie vor; abschaltbar mit `solver.subject_day_limit: false`. |
| Wochenstundenrahmen je Jahrgang | Nur NRW G9 | Warnung im Machbarkeits-Check; andere Länder brauchen nur ihre Zahlen (`models/weekly_frame_check.py`). |
| Lehrkräfte mit Sek-II-Anteil | Teilweise | Nur über Sperrzeiten und ein geringeres Sek-I-Soll; die Testdaten im Profil `nrw-g9` bilden das so nach. |

Nicht bestätigt: der Kommentar im Solver, 7 Springstunden pro Woche seien
ein rechtlicher Richtwert für Lehrkräfte. Dafür wurde keine Quelle
gefunden.

## 5. Was eine Erweiterung je Familie braucht

Voraussetzung für alle: freie Fächerliste, halbe Lehrerstunden, C15
abschaltbar (alle drei umgesetzt).

| Ziel | Zusätzlich nötig |
|---|---|
| Familie A (NI, RP, SL, SH, HE-G9) | Nur Daten: Stundentafel und Lehrerstunden des Landes. |
| Familie D (G8-Form, Kl. 5–9) | Daten und ein Test mit Jahrgängen 5–9. Bei 34–35 Stunden bleibt im 5×7-Raster kaum Luft; sonst wie B. Prüfen, ob Kl. 10 als Einführungsphase im Klassenverband läuft. |
| Familie B (SN, ST, TH), Hamburg | Lange Tage: Mittagspause, Höchstzahl Stunden bzw. Minuten pro Tag, Nachmittage je Klasse. |
| Familie C (BE, BB, MV) | Wie B, dazu Test mit Jahrgängen 7–10. |
| Bayern | Wie B, dazu Zweige und Sprachen-Schienen als Kopplungen, halbe Wochenstunden bzw. Blockmodule, Intensivierungsgruppen. |
| G8- und G9-Züge im selben Jahrgang (HE, BW) | Stundentafel je Klasse statt je Jahrgang im Import. |

Grundsätze für die Umsetzung:

1. Keine Landesregel im Solver-Code. Stundentafeln und Lehrerstunden
   bleiben Daten; Regeln wie Nachmittagsgrenzen werden Einstellungen.
2. Je Land ein Benchmark-Datensatz aus der echten Stundentafel, bevor
   eine Regel als erfüllt gilt.
3. Erst umsetzen, wenn eine konkrete Schule aus der Familie die
   Ergebnisse prüfen kann.

## Quellen

- [KMK: Schulorganisatorische Vorgaben (Übersichtsseite)](https://www.kmk.org/downloads-dokumente/statistik/schulstatistik/schulorganisatorische-vorgaben.html)
- [KMK: Pflichtstunden der Lehrkräfte 2025/2026](https://www.kmk.org/fileadmin/Dateien/pdf/Statistik/Dokumentationen/Pflichtstunden_der_LehrerInnen_2025_2026.pdf)
- [KMK: Wochenpflichtstunden der Schülerinnen und Schüler 2025/2026](https://www.kmk.org/fileadmin/Dateien/pdf/Statistik/Dokumentationen/Wochenpflichtstunden_der_SchuelerInnen_2025_2026.pdf)
- [NRW: Verordnung zu § 93 Abs. 2 Schulgesetz](https://recht.nrw.de/lrgv/rechtsverordnung/01082026-verordnung-zur-ausfuehrung-des-ss-93-abs-2-schulgesetz-vo-zu-ss-93/)
- [NRW: Stundentafel Gymnasium G9, Anlage 3a (Fassung mit Informatik)](https://recht.nrw.de/system/files/BHA/26521-42935-sgv_223_20121102_1_anlage3a.pdf)
- [NRW: Stundentafel Gymnasium G9, Anlage 3a (auslaufende Fassung)](https://www.schulministerium.nrw/system/files/media/document/file/Stundentafel_SI_G9_Anlage_3a_auslaufend.pdf)
- [NRW: Stundentafel Gymnasium G8](https://www.schulministerium.nrw/sites/default/files/documents/Stundentafel.pdf)
- [NRW: Runderlass Unterrichtsbeginn, Verteilung der Wochenstunden, Fünf-Tage-Woche (BASS 12-63 Nr. 3)](https://bass.schule.nrw/15325.htm)
- [Bayern: GSO Anlage 1, Stundentafeln Jahrgangsstufen 5 bis 11](https://www.gesetze-bayern.de/Content/Document/BayGSO-ANL_1)
