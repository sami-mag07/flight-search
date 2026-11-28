# /// script
# requires-python = ">=3.10"
# dependencies = ["fast-flights==2.2", "primp==0.12.0"]
# ///
import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import fast_flights.core as core
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData
from fast_flights.primp import Client

GOOGLE = "https://www.google.com/travel/flights"
CONSENT = {
    "SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmRlIAEaBgiAo_CmBg",
    "CONSENT": "YES+cb.20230810-00-p0.de+FX+999",
}


def parse_dates(spec):
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if ".." in part:
            start, end = (date.fromisoformat(x) for x in part.split(".."))
            while start <= end:
                out.append(start.isoformat())
                start += timedelta(days=1)
        else:
            out.append(date.fromisoformat(part).isoformat())
    return out


def parse_codes(spec):
    return [c.strip().upper() for c in spec.split(",") if c.strip()]


def tfs(legs, trip, people, stops=None):
    data = [FlightData(date=d, from_airport=a, to_airport=b) for a, b, d in legs]
    f = TFSData.from_interface(
        flight_data=data, trip=trip, passengers=Passengers(adults=people), seat="economy", max_stops=stops
    )
    return f.as_b64().decode()


def google_link(legs, people):
    if len(legs) == 1:
        trip = "one-way"
    elif legs[0][0] == legs[1][1] and legs[0][1] == legs[1][0]:
        trip = "round-trip"
    else:
        trip = "multi-city"
    return f"{GOOGLE}?tfs={tfs(legs, trip, people)}&hl=de&curr=EUR"


def client(proxy):
    kwargs = {"impersonate": "chrome_126", "timeout": 30}
    if proxy:
        kwargs["proxy"] = proxy
    return Client(**kwargs)


def ip_country(proxy):
    try:
        res = client(proxy).get("https://ipinfo.io/country")
        return res.text.strip() if res.status_code == 200 else "?"
    except Exception:
        return "?"


def euros(text):
    digits = re.sub(r"[^\d]", "", text or "")
    if "€" not in (text or "") or not digits:
        return None
    return int(digits) or None


def clock(text):
    m = re.match(r"(\d+):(\d+)\s*(AM|PM)", text or "")
    if not m:
        return text or ""
    hour = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
    return f"{hour:02d}:{m.group(2)}"


class Blocked(RuntimeError):
    pass


def search_leg(a, b, d, people, stops, proxy):
    params = {"tfs": tfs([(a, b, d)], "one-way", people, stops), "hl": "en", "tfu": "EgQIABABIgA", "curr": "EUR"}
    res = client(proxy).get(GOOGLE, params=params, cookies=CONSENT)
    if res.status_code == 429 or "unusual traffic" in res.text:
        raise Blocked("google blockt diese IP (captcha), anderes land oder spaeter")
    if res.status_code != 200:
        raise RuntimeError(f"google antwortet mit http {res.status_code}")
    try:
        result = core.parse_response(res)
    except Exception:
        result = None
    if not result or not result.flights:
        raise RuntimeError("keine fluege auf der seite (route leer oder seite laedt per javascript)")
    return result


def cmd_land(args):
    print(ip_country(args.proxy or os.environ.get("FLUG_PROXY")))


def cmd_suche(args):
    proxy = args.proxy or os.environ.get("FLUG_PROXY")
    detected = ip_country(proxy)
    label = (args.land or detected).upper()
    if args.land and detected != label:
        where = "laesst sich nicht pruefen" if detected == "?" else f"kommt aus {detected}"
        print(f"achtung: --land {label}, aber die IP {where}. VPN pruefen.", file=sys.stderr)
        if not args.trotzdem:
            sys.exit(2)

    legs = [("hin", a, b, d) for a in parse_codes(args.von) for b in parse_codes(args.nach) for d in parse_dates(args.hin)]
    if args.zurueck:
        legs += [("rueck", b, a, d) for a in parse_codes(args.von) for b in parse_codes(args.nach) for d in parse_dates(args.zurueck)]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run = datetime.now().isoformat(timespec="seconds")
    found = 0
    blocked = False
    with out.open("a", encoding="utf-8") as fh:
        for i, (direction, a, b, d) in enumerate(legs):
            base = {"lauf": run, "land": label, "ip_land": detected, "richtung": direction,
                    "von": a, "nach": b, "datum": d, "personen": args.personen}
            try:
                result = search_leg(a, b, d, args.personen, args.stopps, proxy)
                link = google_link([(a, b, d)], args.personen)
                rows = []
                for f in result.flights:
                    price = euros(f.price)
                    if not price or not f.name:
                        continue
                    rows.append({**base, "airline": f.name, "ab": clock(f.departure), "an": clock(f.arrival),
                                 "plus_tage": f.arrival_time_ahead.strip(), "dauer": f.duration,
                                 "stopps": f.stops, "preis": price, "niveau": result.current_price, "link": link})
                if not rows:
                    raise RuntimeError("keine preise in euro auf der seite")
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                found += len(rows)
                print(f"{label} {a}-{b} {d}: {len(rows)} fluege", file=sys.stderr, flush=True)
            except Exception as e:
                fh.write(json.dumps({**base, "fehler": str(e)[:200]}, ensure_ascii=False) + "\n")
                print(f"{label} {a}-{b} {d}: FEHLER {str(e)[:120]}", file=sys.stderr, flush=True)
                if isinstance(e, Blocked):
                    blocked = True
                    break
            if i < len(legs) - 1:
                time.sleep(args.pause)
    print(f"{found} fluege aus {len(legs)} abfragen nach {out}", file=sys.stderr)
    if blocked or found == 0:
        sys.exit(1)


def hours(duration):
    h = re.search(r"(\d+)\s*hr", duration or "")
    m = re.search(r"(\d+)\s*min", duration or "")
    return (int(h.group(1)) if h else 0) + (int(m.group(1)) if m else 0) / 60


def load_flights(path, max_hours, max_stops):
    flights = {}
    errors = []
    runs = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        runs.add(row["lauf"][:10])
        if "fehler" in row:
            errors.append(row)
            continue
        if max_hours and hours(row["dauer"]) > max_hours:
            continue
        if max_stops is not None and not (isinstance(row["stopps"], int) and row["stopps"] <= max_stops):
            continue
        key = (row["personen"], row["richtung"], row["von"], row["nach"], row["datum"], row["airline"],
               row["ab"], row["an"], row["plus_tage"], row["stopps"])
        entry = flights.setdefault(key, {**row, "laender": {}})
        old = entry["laender"].get(row["land"])
        entry["laender"][row["land"]] = row["preis"] if old is None else min(old, row["preis"])
    for entry in flights.values():
        entry["preis"] = min(entry["laender"].values())
    return list(flights.values()), errors, sorted(runs)


def bag_extra(flight, baggage):
    name = flight["airline"]
    info = baggage.get(name) or baggage.get(name.split(",")[0].strip())
    if not info:
        return None
    if info.get("inklusive"):
        return 0
    extra = info.get("aufpreis")
    return None if extra is None else extra * flight["personen"]


def price_of(flight, baggage, need_bag):
    if not need_bag:
        return flight["preis"], True
    extra = bag_extra(flight, baggage)
    return flight["preis"] + (extra or 0), extra is not None


def money(value, known):
    return f"{value} €" if known else f"{value} € + Koffer ?"


def bag_text(flight, baggage):
    extra = bag_extra(flight, baggage)
    return "?" if extra is None else "inkl." if extra == 0 else f"+{extra} €"


def describe(f):
    stops = f["stopps"]
    stops = {0: "direkt", 1: "1 Stopp"}.get(stops, f"{stops} Stopps" if isinstance(stops, int) else "Stopps ?")
    ahead = f" {f['plus_tage']}" if f["plus_tage"] else ""
    return f"{f['airline']}, {f['ab']} bis {f['an']}{ahead}, {f['dauer'].replace(' hr', ' h')}, {stops}"


def countries_text(f, lands):
    prices = f["laender"]
    if len(prices) == len(lands) and len(set(prices.values())) == 1:
        return "überall gleich"
    return ", ".join(f"{land} {prices[land]} €" if land in prices else f"{land} ?" for land in lands)


def build_tables(flights, baggage, need_bag, top, lands):
    multi_land = len(lands) > 1
    tables = []
    shown = []
    cost = lambda f: price_of(f, baggage, need_bag)

    for direction, title in (("hin", "Hinflug"), ("rueck", "Rückflug")):
        own = [f for f in flights if f["richtung"] == direction]
        if not own:
            continue
        routes = sorted({f"{f['von']}-{f['nach']}" for f in own})
        day_rows = []
        for d in sorted({f["datum"] for f in own}):
            cells = []
            for r in routes:
                options = [f for f in own if f["datum"] == d and f"{f['von']}-{f['nach']}" == r]
                cells.append(money(*min((cost(f) for f in options), key=lambda c: c[0])) if options else "")
            day_rows.append([d] + cells)
        tables.append((f"{title}: günstigster Preis pro Tag", ["Datum"] + routes, day_rows))

        best = sorted(own, key=lambda f: cost(f)[0])[:top]
        shown += best
        head = ["Preis mit Koffer", "Ticket", "Koffer"] if need_bag else ["Preis"]
        head += ["Datum", "Strecke", "Flug"] + (["Preis je Land"] if multi_land else []) + ["Link"]
        rows = []
        for f in best:
            row = [money(*cost(f))]
            if need_bag:
                row += [f"{f['preis']} €", bag_text(f, baggage)]
            row += [f["datum"], f"{f['von']}-{f['nach']}", describe(f)]
            if multi_land:
                row.append(countries_text(f, lands))
            row.append(("Google Flights", f["link"]))
            rows.append(row)
        tables.append((f"{title}: die günstigsten", head, rows))

    cheapest = {}
    for f in sorted(flights, key=lambda f: cost(f)[0]):
        cheapest.setdefault((f["richtung"], f["datum"], f["von"], f["nach"]), f)
    outs = [f for k, f in cheapest.items() if k[0] == "hin"]
    backs = [f for k, f in cheapest.items() if k[0] == "rueck"]
    combos = []
    for o in outs:
        for b in backs:
            if b["datum"] > o["datum"]:
                (po, ko), (pb, kb) = cost(o), cost(b)
                combos.append((po + pb, ko and kb, o, b))
    combos.sort(key=lambda c: c[0])
    if combos:
        rows = []
        for price, known, o, b in combos[:top]:
            shown += [o, b]
            legs = [(o["von"], o["nach"], o["datum"]), (b["von"], b["nach"], b["datum"])]
            rows.append([money(price, known), f"{o['datum']} {o['von']}-{o['nach']}", describe(o),
                         f"{b['datum']} {b['von']}-{b['nach']}", describe(b),
                         ("Hin", o["link"]), ("Zurück", b["link"]),
                         ("Als Paket", google_link(legs, o["personen"]))])
        head = ["Summe mit Koffer" if need_bag else "Summe", "Hin", "Hinflug", "Zurück", "Rückflug",
                "Link hin", "Link zurück", "Link Paket"]
        tables.append(("Hin und zurück: günstigste Kombis", head, rows))

    unknown = sorted({f["airline"] for f in shown if need_bag and bag_extra(f, baggage) is None})
    return tables, unknown


def cell_md(c):
    if isinstance(c, tuple):
        return f"[{c[0]}]({c[1]})"
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", str(c)).replace("|", "/")


def cell_html(c):
    if isinstance(c, tuple):
        return f'<a href="{html.escape(c[1])}" target="_blank" rel="noopener">{html.escape(c[0])}</a>'
    return html.escape(str(c))


def to_markdown(tables, notes):
    parts = []
    for title, head, rows in tables:
        parts.append(f"### {title}\n")
        parts.append("| " + " | ".join(head) + " |")
        parts.append("|" + "---|" * len(head))
        for r in rows:
            parts.append("| " + " | ".join(cell_md(c) for c in r) + " |")
        parts.append("")
    parts += notes
    return "\n".join(parts)


def to_html(tables, notes, title):
    body = []
    for t, head, rows in tables:
        body.append(f"<h2>{html.escape(t)}</h2><div class=scroll><table><thead><tr>")
        body.append("".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr></thead><tbody>")
        for r in rows:
            body.append("<tr>" + "".join(f"<td>{cell_html(c)}</td>" for c in r) + "</tr>")
        body.append("</tbody></table></div>")
    body.append("".join(f"<p>{html.escape(n)}</p>" for n in notes))
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{color-scheme:light dark;--bg:#f4f2ee;--fg:#16161a;--mute:#6b6862;--line:#d9d5ce;--link:#1e6f8f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14141a;--fg:#ecebe8;--mute:#9a978f;--line:#2e2e36;--link:#7cc4e0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:40px 20px 80px}}
h1{{font-size:28px;margin:0 0 8px}}
h2{{font-size:19px;margin:48px 0 12px}}
.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:9px 12px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mute);font-weight:600}}
td:first-child{{font-weight:700;white-space:nowrap}}
a{{color:var(--link)}}
p{{color:var(--mute);max-width:70ch}}
</style></head><body><main><h1>{html.escape(title)}</h1>
{''.join(body)}
</main></body></html>"""


def cmd_tabelle(args):
    flights, errors, runs = load_flights(args.datei, args.max_stunden, args.max_stopps)
    if not flights:
        sys.exit(f"keine fluege in {args.datei}" + (f", {len(errors)} fehler" if errors else ""))
    baggage = json.loads(Path(args.gepaeck).read_text(encoding="utf-8")) if args.gepaeck else {}
    need_bag = bool(args.gepaeck)
    people = sorted({f["personen"] for f in flights})
    if len(people) > 1:
        sys.exit(f"{args.datei} mischt laeufe fuer {people} personen, bitte pro personenzahl eine eigene datei")
    lands = sorted({land for f in flights for land in f["laender"]})
    tables, unknown = build_tables(flights, baggage, need_bag, args.top, lands)

    span = runs[0] if runs[0] == runs[-1] else f"{runs[0]} bis {runs[-1]}"
    who = "1 Person" if people[0] == 1 else f"{people[0]} Personen zusammen"
    notes = [f"Abfragen vom {span}, Länder: {', '.join(lands)}. Preise in Euro für {who}, Grundtarif laut Google Flights."]
    if unknown:
        notes.append(f"Koffer unklar bei: {' / '.join(unknown)}. Dort zählt nur der Ticketpreis.")
    if errors:
        failed = sorted({f"{e['land']} {e['von']}-{e['nach']} {e['datum']}" for e in errors})
        notes.append(f"Ohne Ergebnis ({len(errors)}): {', '.join(failed[:12])}" + (" ..." if len(failed) > 12 else ""))

    print(to_markdown(tables, notes))
    board = Path(args.board)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(to_html(tables, notes, args.titel), encoding="utf-8")
    print(f"\nboard: {board.resolve()}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(prog="flug.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("land")
    s.add_argument("--proxy")
    s.set_defaults(fn=cmd_land)

    s = sub.add_parser("suche")
    s.add_argument("--von", required=True)
    s.add_argument("--nach", required=True)
    s.add_argument("--hin", required=True)
    s.add_argument("--zurueck")
    s.add_argument("--personen", type=int, default=1)
    s.add_argument("--stopps", type=int)
    s.add_argument("--land")
    s.add_argument("--proxy")
    s.add_argument("--pause", type=float, default=2.0)
    s.add_argument("--out", default="ergebnisse/suche.jsonl")
    s.add_argument("--trotzdem", action="store_true")
    s.set_defaults(fn=cmd_suche)

    s = sub.add_parser("tabelle")
    s.add_argument("datei", nargs="?", default="ergebnisse/suche.jsonl")
    s.add_argument("--gepaeck")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--max-stunden", type=float)
    s.add_argument("--max-stopps", type=int)
    s.add_argument("--board", default="ergebnisse/board.html")
    s.add_argument("--titel", default="Flugsuche")
    s.set_defaults(fn=cmd_tabelle)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
