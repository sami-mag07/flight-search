# Flugsuche: Anleitung für den Agenten

Du suchst für den Nutzer die günstigsten Flüge. Dein Werkzeug ist `uv run flug.py` in diesem Ordner. Für Websuche (Flughäfen, Gepäckregeln) nimmst du searchify: das MCP-Tool `passages`, oder ohne MCP `uvx --from "searchify[rerank]" searchify passages "<frage>" -k 5`.

## 1. Interview

Lies zuerst die Nachricht des Nutzers. Frag dann nur, was fehlt, alles in einer einzigen Rückfrage (AskUserQuestion, wenn es das gibt):

1. Von wo (Stadt reicht)
2. Wohin
3. Hinflug: Datum und wie flexibel (zum Beispiel 2 Tage früher oder später)
4. Rückflug: Datum und Spielraum, oder nur Hinflug
5. Wie viele Personen

Gepäck fragst du nur, wenn die Nachricht nichts dazu sagt: nur Handgepäck, 1 Koffer (23 kg) pro Person oder mehr.

Ohne Rückfrage annehmen und im Plan nennen: Economy, Umsteigen erlaubt, Nachbarflughäfen bis etwa 3 Stunden Zug oder Auto kommen mit rein.

Vor dem Start zeigst du den Plan in drei Zeilen: Flughäfen, Tage, Länder. Dazu die Dauer: Abfragen mal Länder mal etwa 3 Sekunden.

## 2. Flughäfen

Städte werden zu IATA-Codes (Berlin BER, Lissabon LIS). Nachbarflughäfen nimmst du dazu, wenn sie realistisch erreichbar sind (für Berlin etwa LEJ, PRG, HAM; im Zweifel per searchify prüfen). Höchstens 4 Flughäfen pro Seite, sonst wird die Suche zu lang.

## 3. Suche aus dem eigenen Land

```
uv run flug.py suche --von BER,LEJ --nach LIS,OPO --hin 2027-01-14..2027-01-17 --zurueck 2027-01-21..2027-01-23 --personen 2 --out ergebnisse/lissabon.jsonl
```

- Daten: einzeln mit Komma (`2027-01-14,2027-01-16`) oder als Bereich (`2027-01-14..2027-01-17`).
- `--stopps 0` nur, wenn der Nutzer Direktflüge will.
- Mehr als 40 Abfragen lässt du im Hintergrund laufen.
- Eine Datei pro Suche und Personenzahl. `tabelle` bricht ab, wenn eine Datei verschiedene Personenzahlen mischt.
- Exit-Code 1 heißt: Captcha oder kein einziger Flug gefunden. Dann nicht sofort wiederholen, sondern die Fehlerzeilen in der Datei lesen.

## 4. Länderrunden über VPN

Standardländer zusätzlich zum eigenen: US, GB, TR, BR, TH. Jede Runde schreibt in dieselbe Datei, mit `--land <CODE>`. Das Skript prüft die echte IP. Exit-Code 2 heißt, das VPN steht noch nicht oder das Land stimmt nicht: 5 Sekunden warten, einmal neu versuchen, sonst das Land überspringen. Exit-Code 1 nach einem Captcha heißt: das Land sofort überspringen. `--trotzdem` nur, wenn der Nutzer das ausdrücklich will.

Sag dem Nutzer vor dem ersten Wechsel, dass der VPN-Wechsel die Verbindung kurz unterbricht, auch deine eigene.

Welcher Weg, in dieser Reihenfolge:

1. **Mullvad** (`mullvad status` funktioniert): Status vom Anfang merken. Pro Land `mullvad relay set location <code klein>`, dann `mullvad connect`, warten bis `mullvad status` "Connected" zeigt (höchstens 30 Sekunden), dann suchen. Welche Länder es gibt, zeigt `mullvad relay list`. Am Ende den Status vom Anfang wiederherstellen.
2. **Proxy** (der Nutzer gibt eine SOCKS5- oder HTTP-Adresse, oder `FLUG_PROXY` steht in `.env`): `--proxy <adresse> --land <CODE>`. Mit `.env`: `uv run --env-file .env flug.py ...`.
3. **Tor** (`tor --version` funktioniert): `tor --SocksPort 9150 --ExitNodes "{us}" --StrictNodes 1` im Hintergrund starten, dann `--proxy socks5h://127.0.0.1:9150 --land US`. Pro Land neu starten, am Ende beenden. Google zeigt Tor-Adressen oft ein Captcha; dann das Land überspringen.
4. **Andere VPN-App**: Den Nutzer bitten, das Land in seiner App umzustellen und "weiter" zu schreiben. Dann `--land <CODE>`.

Will der Nutzer keine Länderrunden, lässt du sie weg und schreibst das ins Ergebnis.

## 5. Gepäck

Nur, wenn der Nutzer Koffer mitnimmt.

1. `uv run flug.py tabelle ergebnisse/<datei>.jsonl` laufen lassen und die Airlines in den Tabellen notieren.
2. Pro Airline die Gepäckregel suchen, am besten auf der Seite der Airline selbst: `searchify passages "<Airline> Economy aufgegebenes Gepäck 23 kg Preis"`.
3. In `ergebnisse/gepaeck.json` eintragen, Namen genau so wie in der Tabelle:

```json
{
  "easyJet": {"inklusive": false, "aufpreis": 45, "quelle": "https://..."},
  "Tap Air Portugal": {"inklusive": true, "quelle": "https://..."}
}
```

- `aufpreis` ist Euro pro Person und Flug für das gewünschte Gepäck.
- Bei Namen wie "Lufthansa, Tap Air Portugal" zählt der erste Name, außer es gibt einen eigenen Eintrag für den ganzen Namen.
- Nur mit Quelle eintragen. Ohne Beleg weglassen, dann steht in der Tabelle "+ Koffer ?". Nie raten.

Wiederholen, bis in den obersten Zeilen kein "?" mehr steht, oder im Ergebnis sagen, wo es offen bleibt.

## 6. Ergebnis zeigen

```
uv run flug.py tabelle ergebnisse/<datei>.jsonl --gepaeck ergebnisse/gepaeck.json --titel "Berlin nach Lissabon, Januar"
```

- Die Markdown-Tabellen in den Chat übernehmen und `ergebnisse/board.html` öffnen (Mac `open`, Linux `xdg-open`, Windows `start`).
- Erste Zeile der Antwort: die günstigste Kombi mit Preis (mit Koffer, falls gefragt), Daten, Airlines und Link.
- Danach die Tabellen. Sag, ob ein Land günstiger war (Spalte "Preis je Land") oder alles gleich war.
- Hinweis an den Nutzer: Der Link "Als Paket" zeigt den echten Hin- und Rückflug. Der kann billiger sein als die Summe der Einzelflüge, darum die oberen ein bis zwei Kombis dort gegenprüfen.

## Regeln

- Nichts buchen, keine Zahlungs- oder Personendaten eingeben.
- Preise nur aus den Ergebnissen von flug.py oder aus belegten Quellen nennen.
- Pause zwischen Abfragen nicht unter 2 Sekunden. Bei Captcha das Land überspringen, nicht wiederholen.
- `ergebnisse/` bleibt lokal und wird nicht committet.
