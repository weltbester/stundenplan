"""NRW, Gymnasium G9: Beispiel-Stundentafel und Wochenstundenrahmen.

Quelle: APO-S I NRW, Anlage 3a "Stundentafeln für die Sekundarstufe I –
Gymnasium mit neunjährigem Bildungsgang (G9)", Fassung mit dem Fach
Informatik, abgerufen im November 2026 (Link in docs/bundeslaender.md).

Die Verordnung gibt nur Kontingente vor (Kl. 5–6 und Kl. 7–10); die
Verteilung auf die Jahrgänge beschließt die Schule. Die Tafel unten ist
EINE zulässige Verteilung als Beispiel, kein Vorschlag des Landes:

- 182 Kernstunden (59 in Kl. 5–6, 123 in Kl. 7–10) und alle
  6 Ergänzungsstunden, zusammen 188.
- Wochenstunden je Jahrgang: 30, 30, 32, 32, 32, 32.
- Zweite Fremdsprache ab Kl. 7 (15 Stunden), Wahlpflicht in Kl. 9–10
  (je 3 Stunden), Informatik in Kl. 6, Chemie ab Kl. 7.
- Geschichte und Wirtschaft-Politik je 8, Erdkunde 7 Stunden;
  Biologie und Physik je 8, Chemie 7; Kunst 8, Musik 9.
"""

from config.defaults import SECOND_LANGUAGE_SUBJECT

# Jahrgang → Fach → Wochenstunden (nur Fächer mit Stunden).
# "Religion" steht für Religionslehre/Praktische Philosophie,
# "WPF" für den Wahlpflichtunterricht; beide laufen über Kopplungen.
STUNDENTAFEL_NRW_G9: dict[int, dict[str, int]] = {
    5: {
        "Deutsch":            5,
        "Mathematik":         4,
        "Englisch":           5,
        "Erdkunde":           2,
        "Wirtschaft-Politik": 2,
        "Biologie":           2,
        "Kunst":              2,
        "Musik":              2,
        "Religion":           2,
        "Sport":              4,
    },  # 30 Kernstunden
    6: {
        "Deutsch":            4,
        "Mathematik":         5,
        "Englisch":           4,
        "Geschichte":         2,
        "Biologie":           2,
        "Physik":             2,
        "Informatik":         2,
        "Kunst":              2,
        "Musik":              1,
        "Religion":           2,
        "Sport":              3,
        "Ergänzungsstunde":   1,
    },  # 29 Kernstunden + 1 Ergänzungsstunde
    7: {
        "Deutsch":            4,
        "Mathematik":         3,
        "Englisch":           4,
        SECOND_LANGUAGE_SUBJECT: 4,
        "Geschichte":         2,
        "Erdkunde":           2,
        "Biologie":           2,
        "Chemie":             2,
        "Musik":              2,
        "Religion":           2,
        "Sport":              3,
        "Ergänzungsstunde":   2,
    },  # 30 Kernstunden + 2 Ergänzungsstunden
    8: {
        "Deutsch":            3,
        "Mathematik":         4,
        "Englisch":           3,
        SECOND_LANGUAGE_SUBJECT: 4,
        "Geschichte":         2,
        "Wirtschaft-Politik": 2,
        "Physik":             2,
        "Chemie":             2,
        "Kunst":              2,
        "Musik":              2,
        "Religion":           2,
        "Sport":              3,
        "Ergänzungsstunde":   1,
    },  # 31 Kernstunden + 1 Ergänzungsstunde
    9: {
        "Deutsch":            3,
        "Mathematik":         3,
        "Englisch":           3,
        SECOND_LANGUAGE_SUBJECT: 4,
        "Erdkunde":           2,
        "Wirtschaft-Politik": 2,
        "Physik":             2,
        "Chemie":             2,
        "Kunst":              2,
        "Religion":           2,
        "Sport":              3,
        "WPF":                3,
        "Ergänzungsstunde":   1,
    },  # 31 Kernstunden + 1 Ergänzungsstunde
    10: {
        "Deutsch":            3,
        "Mathematik":         3,
        "Englisch":           3,
        SECOND_LANGUAGE_SUBJECT: 3,
        "Geschichte":         2,
        "Erdkunde":           1,
        "Wirtschaft-Politik": 2,
        "Biologie":           2,
        "Chemie":             1,
        "Physik":             2,
        "Musik":              2,
        "Religion":           2,
        "Sport":              2,
        "WPF":                3,
        "Ergänzungsstunde":   1,
    },  # 31 Kernstunden + 1 Ergänzungsstunde
}

# Jahrgang → (Minimum, Maximum) Wochenstunden laut Anlage 3a.
NRW_G9_WEEKLY_FRAME: dict[int, tuple[int, int]] = {
    5: (28, 30),
    6: (28, 30),
    7: (30, 33),
    8: (30, 33),
    9: (30, 33),
    10: (30, 33),
}
