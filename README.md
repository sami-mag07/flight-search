# Flugsuche

Ein Agent fragt kurz nach Strecke, Daten und Gepäck, durchsucht Google Flights für jeden Tag und jeden Flughafen, wiederholt die Suche über VPN aus mehreren Ländern und zeigt die günstigsten Flüge als Tabelle mit Links.

## Einrichten

Einmal, etwa 5 Minuten.

1. **uv** installieren (startet das Skript samt Abhängigkeiten):
   Mac und Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`,
   Windows `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. **Claude Code** installieren: https://claude.com/claude-code. Andere Agents gehen auch, sie lesen `AGENTS.md`.
3. **Repo holen:**
   ```
   git clone https://github.com/sami-mag07/flugsuche
   cd flugsuche
   ```
4. **Searchify** einbinden, die Websuche für den Agenten (kostenlos, kein API-Key): https://github.com/sami-mag07/searchify
   ```
   claude mcp add searchify -- uvx --from "searchify[mcp,rerank]" searchify-mcp
   ```
5. **Test:** `uv run flug.py land` gibt das Land deiner IP aus, zum Beispiel `DE`.

VPN ist optional, siehe unten.

## Benutzen

Im Ordner `claude` starten und schreiben, was du suchst:

> Such mir Flüge von Berlin nach Lissabon, hin 15. oder 16. Januar, zurück 22. Januar, ein Koffer.

Dann passiert das:

1. **Interview.** Der Agent fragt nur, was fehlt: von wo, wohin, wann, wie flexibel, wie viele Personen. Steht nichts zum Gepäck in deiner Nachricht, fragt er danach.
2. **Suche.** Jeder Tag in deinem Spielraum, jeder passende Flughafen (auch Nachbarflughäfen), Hin- und Rückflug einzeln.
3. **Länder.** Dieselbe Suche noch einmal über VPN aus US, GB, TR, BR und TH.
4. **Gepäck.** Für die Airlines in den Ergebnissen sucht der Agent per Searchify, ob ein Koffer drin ist und was er sonst kostet, und rechnet ihn in den Preis.
5. **Ergebnis.** Tabellen im Chat und als Seite `ergebnisse/board.html`:
   - günstigster Preis pro Tag und Strecke
   - die günstigsten Hin- und Rückflüge mit Uhrzeit, Dauer, Stopps, Koffer und Preis je Land
   - die günstigsten Kombis aus Hin und zurück
   - bei jedem Flug der Link zu Google Flights

## VPN und Länder

| Weg | Kosten | Wie |
|---|---|---|
| Mullvad | 5 € im Monat | Der Agent wechselt die Länder selbst über `mullvad`. Mullvad-App installieren und einloggen. |
| Andere VPN-App | je nach Anbieter | Der Agent sagt dir das Land, du stellst es in der App um und schreibst "weiter". |
| Eigener Server | kostenlos, wenn du einen hast | `ssh -f -N -D 1080 user@server`, dann `FLUG_PROXY` in `.env` (Vorlage `.env.example`). |
| Tor | kostenlos | `brew install tor` oder `apt install tor`. Google zeigt Tor oft ein Captcha. |

Das Skript prüft vor jeder Runde, aus welchem Land die IP wirklich kommt, und bricht ab, wenn das VPN nicht steht.

Ehrlich dazu: Ein Test vom 25.11.2026 mit 2 IP-Ländern, 8 Marktländern, mehreren Währungen und Handy-Profilen ergab bei Google Flights überall denselben Preis. Die Länderrunde ist ein Gegencheck. Unterschiede gibt es, wenn überhaupt, eher direkt bei Airlines und Buchungsportalen.

## Ohne Agent

```
uv run flug.py suche --von BER --nach LIS,OPO --hin 2027-01-15..2027-01-16 --zurueck 2027-01-22 --out ergebnisse/lissabon.jsonl
uv run flug.py suche --von BER --nach LIS,OPO --hin 2027-01-15..2027-01-16 --zurueck 2027-01-22 --land US --out ergebnisse/lissabon.jsonl
uv run flug.py tabelle ergebnisse/lissabon.jsonl --gepaeck ergebnisse/gepaeck.json
```

| Option | Bedeutung |
|---|---|
| `--von`, `--nach` | IATA-Codes, mehrere mit Komma |
| `--hin`, `--zurueck` | Daten mit Komma oder als Bereich `2027-01-15..2027-01-18` |
| `--personen` | Erwachsene, Preise gelten dann für alle zusammen |
| `--stopps 0` | nur Direktflüge |
| `--land`, `--proxy` | Länderrunde, siehe oben |
| `--gepaeck` | Kofferpreise pro Airline, Format in `CLAUDE.md` |
| `--top`, `--max-stunden`, `--max-stopps` | Tabelle kürzen oder filtern |

## Was die Zahlen heißen

- Preise sind der Grundtarif in Economy für alle Personen zusammen, ohne aufgegebenes Gepäck. Mit `--gepaeck` kommt der Koffer dazu; wo er unklar ist, steht "+ Koffer ?".
- Hin und zurück sind zwei Einzelflüge, zusammengezählt. Google liefert Rundflüge ohne Browser nicht mehr aus. Der Link "Als Paket" öffnet den echten Hin- und Rückflug, der kann billiger sein.
- Ein Link öffnet die Strecke an dem Tag in Google Flights. Den Flug wählst du dort über Airline und Uhrzeit aus der Tabelle.
- Zu viele Abfragen am Stück beantwortet Google mit einem Captcha. Das Skript wartet deshalb 2 Sekunden zwischen den Abfragen.
- Gebucht wird nichts.
