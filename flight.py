# /// script
# requires-python = ">=3.10"
# dependencies = ["fast-flights==2.2", "primp==0.12.0"]
# ///
import argparse
import hashlib
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
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
PORTALS = {
    "US": ("kayak.com", "skyscanner.com"),
    "GB": ("kayak.co.uk", "skyscanner.net"),
    "DE": ("kayak.de", "skyscanner.de"),
    "AT": ("kayak.at", "skyscanner.at"),
    "CH": ("kayak.ch", "skyscanner.ch"),
    "FR": ("kayak.fr", "skyscanner.fr"),
    "ES": ("kayak.es", "skyscanner.es"),
    "IT": ("kayak.it", "skyscanner.it"),
    "NL": ("kayak.nl", "skyscanner.nl"),
    "PT": ("kayak.pt", "skyscanner.pt"),
    "PL": ("kayak.pl", "skyscanner.pl"),
    "TR": ("kayak.com.tr", "skyscanner.com.tr"),
    "BR": ("kayak.com.br", "skyscanner.com.br"),
    "IN": ("kayak.co.in", "skyscanner.co.in"),
    "TH": ("kayak.co.th", "skyscanner.co.th"),
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


def tfs(legs, trip, adults, stops=None):
    data = [FlightData(date=d, from_airport=a, to_airport=b) for a, b, d in legs]
    f = TFSData.from_interface(
        flight_data=data, trip=trip, passengers=Passengers(adults=adults), seat="economy", max_stops=stops
    )
    return f.as_b64().decode()


def google_link(legs, adults):
    if len(legs) == 1:
        trip = "one-way"
    elif legs[0][0] == legs[1][1] and legs[0][1] == legs[1][0]:
        trip = "round-trip"
    else:
        trip = "multi-city"
    return f"{GOOGLE}?tfs={tfs(legs, trip, adults)}&hl=en&curr=EUR"


def client(proxy=None):
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


def search_leg(a, b, d, adults, stops, proxy):
    params = {"tfs": tfs([(a, b, d)], "one-way", adults, stops), "hl": "en", "tfu": "EgQIABABIgA", "curr": "EUR"}
    res = client(proxy).get(GOOGLE, params=params, cookies=CONSENT)
    if res.status_code == 429 or "unusual traffic" in res.text:
        raise Blocked("google blocks this IP (captcha), try another country or later")
    if res.status_code != 200:
        raise RuntimeError(f"google answered http {res.status_code}")
    try:
        result = core.parse_response(res)
    except Exception:
        result = None
    if not result or not result.flights:
        raise RuntimeError("no flights on the page (empty route or page loads by javascript)")
    return result


def cmd_country(args):
    print(ip_country(args.proxy or os.environ.get("FLIGHT_PROXY")))


def cmd_search(args):
    proxy = args.proxy or os.environ.get("FLIGHT_PROXY")
    detected = ip_country(proxy)
    label = (args.country or detected).upper()
    if args.country and detected != label:
        where = "cannot be checked" if detected == "?" else f"is in {detected}"
        print(f"warning: --country {label}, but the IP {where}. check the VPN.", file=sys.stderr)
        if not args.force:
            sys.exit(2)

    origins, destinations = parse_codes(args.origin), parse_codes(args.to)
    legs = [("out", a, b, d) for a in origins for b in destinations for d in parse_dates(args.depart)]
    if args.ret:
        legs += [("back", b, a, d) for a in origins for b in destinations for d in parse_dates(args.ret)]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run = datetime.now().isoformat(timespec="seconds")
    found = 0
    blocked = False
    with out.open("a", encoding="utf-8") as fh:
        for i, (direction, a, b, d) in enumerate(legs):
            base = {"run": run, "country": label, "ip_country": detected, "direction": direction,
                    "origin": a, "destination": b, "date": d, "adults": args.adults}
            try:
                result = search_leg(a, b, d, args.adults, args.stops, proxy)
                link = google_link([(a, b, d)], args.adults)
                rows = []
                for f in result.flights:
                    price = euros(f.price)
                    if not price or not f.name:
                        continue
                    rows.append({**base, "airline": f.name, "depart": clock(f.departure), "arrive": clock(f.arrival),
                                 "days_ahead": f.arrival_time_ahead.strip(), "duration": f.duration,
                                 "stops": f.stops, "price": price, "level": result.current_price, "link": link})
                if not rows:
                    raise RuntimeError("no prices in euro on the page")
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                found += len(rows)
                print(f"{label} {a}-{b} {d}: {len(rows)} flights", file=sys.stderr, flush=True)
            except Exception as e:
                fh.write(json.dumps({**base, "error": str(e)[:200]}, ensure_ascii=False) + "\n")
                print(f"{label} {a}-{b} {d}: ERROR {str(e)[:120]}", file=sys.stderr, flush=True)
                if isinstance(e, Blocked):
                    blocked = True
                    break
            if i < len(legs) - 1:
                time.sleep(args.pause)
    print(f"{found} flights from {len(legs)} queries in {out}", file=sys.stderr)
    if blocked or found == 0:
        sys.exit(1)


def hours(duration):
    h = re.search(r"(\d+)\s*hr", duration or "")
    m = re.search(r"(\d+)\s*min", duration or "")
    return (int(h.group(1)) if h else 0) + (int(m.group(1)) if m else 0) / 60


def flight_id(key):
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:10]


def load_flights(path, max_hours=None, max_stops=None):
    flights = {}
    errors = []
    runs = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        runs.add(row["run"][:10])
        if "error" in row:
            errors.append(row)
            continue
        if max_hours and hours(row["duration"]) > max_hours:
            continue
        if max_stops is not None and not (isinstance(row["stops"], int) and row["stops"] <= max_stops):
            continue
        key = (row["adults"], row["direction"], row["origin"], row["destination"], row["date"], row["airline"],
               row["depart"], row["arrive"], row["days_ahead"], row["stops"])
        entry = flights.setdefault(key, {**row, "id": flight_id(key), "countries": {}})
        old = entry["countries"].get(row["country"])
        entry["countries"][row["country"]] = row["price"] if old is None else min(old, row["price"])
    for entry in flights.values():
        entry["price"] = min(entry["countries"].values())
    return list(flights.values()), errors, sorted(runs)


def bag_fee(flight, baggage):
    name = flight["airline"]
    info = baggage.get(name) or baggage.get(name.split(",")[0].strip())
    if not info:
        return None
    if info.get("included"):
        return 0
    fee = info.get("fee")
    return None if fee is None else fee * flight["adults"]


def price_of(flight, baggage, need_bag):
    if not need_bag:
        return flight["price"], True
    fee = bag_fee(flight, baggage)
    return flight["price"] + (fee or 0), fee is not None


def money(value, known):
    return f"€{value}" if known else f"€{value} + bag ?"


def bag_text(flight, baggage):
    fee = bag_fee(flight, baggage)
    return "?" if fee is None else "included" if fee == 0 else f"+€{fee}"


def describe(f):
    stops = f["stops"]
    stops = {0: "nonstop", 1: "1 stop"}.get(stops, f"{stops} stops" if isinstance(stops, int) else "stops ?")
    ahead = f" {f['days_ahead']}" if f["days_ahead"] else ""
    return f"{f['airline']}, {f['depart']} to {f['arrive']}{ahead}, {f['duration'].replace(' hr', ' h')}, {stops}"


def countries_text(f, lands):
    prices = f["countries"]
    if len(prices) == len(lands) and len(set(prices.values())) == 1:
        return "same everywhere"
    return ", ".join(f"{land} €{prices[land]}" if land in prices else f"{land} ?" for land in lands)


def best_combos(flights, cost):
    cheapest = {}
    for f in sorted(flights, key=lambda f: cost(f)[0]):
        cheapest.setdefault((f["direction"], f["date"], f["origin"], f["destination"]), f)
    outs = [f for k, f in cheapest.items() if k[0] == "out"]
    backs = [f for k, f in cheapest.items() if k[0] == "back"]
    combos = []
    for o in outs:
        for b in backs:
            if b["date"] > o["date"]:
                (po, ko), (pb, kb) = cost(o), cost(b)
                combos.append((po + pb, ko and kb, o, b))
    return sorted(combos, key=lambda c: c[0])


def build_tables(flights, baggage, need_bag, top, lands):
    tables = []
    shown = []
    cost = lambda f: price_of(f, baggage, need_bag)
    multi = len(lands) > 1

    for direction, title in (("out", "Outbound"), ("back", "Return")):
        own = [f for f in flights if f["direction"] == direction]
        if not own:
            continue
        routes = sorted({f"{f['origin']}-{f['destination']}" for f in own})
        day_rows = []
        for d in sorted({f["date"] for f in own}):
            cells = []
            for r in routes:
                options = [f for f in own if f["date"] == d and f"{f['origin']}-{f['destination']}" == r]
                cells.append(money(*min((cost(f) for f in options), key=lambda c: c[0])) if options else "")
            day_rows.append([d] + cells)
        tables.append((f"{title}: cheapest price per day", ["Date"] + routes, day_rows))

        best = sorted(own, key=lambda f: cost(f)[0])[:top]
        shown += best
        head = ["With bag", "Ticket", "Bag"] if need_bag else ["Price"]
        head += ["Date", "Route", "Flight", "ID"] + (["By country"] if multi else []) + ["Link"]
        rows = []
        for f in best:
            row = [money(*cost(f))]
            if need_bag:
                row += [f"€{f['price']}", bag_text(f, baggage)]
            row += [f["date"], f"{f['origin']}-{f['destination']}", describe(f), f["id"]]
            if multi:
                row.append(countries_text(f, lands))
            row.append(("Google Flights", f["link"]))
            rows.append(row)
        tables.append((f"{title}: cheapest flights", head, rows))

    combos = best_combos(flights, cost)
    if combos:
        rows = []
        for price, known, o, b in combos[:top]:
            shown += [o, b]
            legs = [(o["origin"], o["destination"], o["date"]), (b["origin"], b["destination"], b["date"])]
            rows.append([money(price, known), f"{o['date']} {o['origin']}-{o['destination']}", describe(o),
                         f"{b['date']} {b['origin']}-{b['destination']}", describe(b), f"{o['id']} {b['id']}",
                         ("Out", o["link"]), ("Back", b["link"]),
                         ("As package", google_link(legs, o["adults"]))])
        head = ["Total with bag" if need_bag else "Total", "Out", "Outbound flight", "Back", "Return flight",
                "IDs", "Link out", "Link back", "Link package"]
        tables.append(("Round trip: cheapest combinations", head, rows))

    unknown = sorted({f["airline"] for f in shown if need_bag and bag_fee(f, baggage) is None})
    return tables, unknown


def load_sites(path, flights):
    p = Path(path)
    if not p.exists():
        return []
    by_id = {f["id"]: f for f in flights}
    latest = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["id"] in by_id:
            latest[(row["id"], row["site"], row["country"])] = row
    return [(by_id[r["id"]], r) for r in latest.values()]


def paid_eur(r, fx_fee):
    return r["eur"] if r["currency"] == "EUR" else r["eur"] * (1 + fx_fee / 100)


def sites_table(checks, fx_fee):
    rows = []
    for f, r in sorted(checks, key=lambda c: paid_eur(c[1], fx_fee) - c[0]["price"]):
        paid = paid_eur(r, fx_fee)
        diff = paid - f["price"]
        pct = round(100 * diff / f["price"])
        diff_text = "same" if abs(diff) < 1 else f"{'+' if diff > 0 else '-'}€{abs(diff):.0f} ({pct:+d} %)"
        local = f"{r['amount']:,.2f} {r['currency']}"
        rows.append([diff_text, f["id"], f"{f['date']} {f['origin']}-{f['destination']}", describe(f),
                     f"€{f['price']}", r["site"], r["country"], local, f"€{paid:.0f}", r["checked"][:10],
                     (r["site"], r["url"])])
    head = ["Vs Google", "ID", "Leg", "Flight", "Google", "Site", "Country", "Price there", "In euro", "Checked", "Link"]
    return ("Direct on airline and booking sites", head, rows)


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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{color-scheme:light dark;--bg:#f4f2ee;--fg:#16161a;--mute:#6b6862;--line:#d9d5ce;--link:#1e6f8f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14141a;--fg:#ecebe8;--mute:#9a978f;--line:#2e2e36;--link:#7cc4e0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:40px 20px 80px}}
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


def cmd_table(args):
    flights, errors, runs = load_flights(args.file, args.max_hours, args.max_stops)
    if not flights:
        sys.exit(f"no flights in {args.file}" + (f", {len(errors)} errors" if errors else ""))
    adults = sorted({f["adults"] for f in flights})
    if len(adults) > 1:
        sys.exit(f"{args.file} mixes searches for {adults} adults, use one file per passenger count")
    baggage = json.loads(Path(args.baggage).read_text(encoding="utf-8")) if args.baggage else {}
    need_bag = bool(args.baggage)
    lands = sorted({land for f in flights for land in f["countries"]})
    tables, unknown = build_tables(flights, baggage, need_bag, args.top, lands)
    checks = load_sites(args.sites, flights)
    if checks:
        tables.append(sites_table(checks, args.fx_fee))

    span = runs[0] if runs[0] == runs[-1] else f"{runs[0]} to {runs[-1]}"
    who = "1 adult" if adults[0] == 1 else f"{adults[0]} adults together"
    notes = [f"Searched {span} from {', '.join(lands)}. Prices in euro for {who}, base fare on Google Flights."]
    if unknown:
        notes.append(f"Bag unknown for: {' / '.join(unknown)}. Only the ticket counts there.")
    if checks:
        days = sorted({r["rate_date"] for _, r in checks})
        fee = f"plus {args.fx_fee:g} % card fee for foreign currencies" if args.fx_fee else "without a card fee for foreign currencies"
        notes.append(f"Site prices converted at the ECB rate of {', '.join(days)}, {fee}.")
    if errors:
        failed = sorted({f"{e['country']} {e['origin']}-{e['destination']} {e['date']}" for e in errors})
        notes.append(f"No result ({len(errors)}): {', '.join(failed[:12])}" + (" ..." if len(failed) > 12 else ""))

    print(to_markdown(tables, notes))
    board = Path(args.board)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(to_html(tables, notes, args.title), encoding="utf-8")
    print(f"\nboard: {board.resolve()}", file=sys.stderr)


def portal_links(f, country):
    a, b, d = f["origin"], f["destination"], f["date"]
    kayak, sky = PORTALS[country]
    people = f"/{f['adults']}adults" if f["adults"] > 1 else ""
    yymmdd = d[2:].replace("-", "")
    return [
        (kayak, f"https://www.{kayak}/flights/{a}-{b}/{d}{people}?sort=price_a"),
        (sky, f"https://www.{sky}/transport/flights/{a.lower()}/{b.lower()}/{yymmdd}/?adultsv2={f['adults']}"),
    ]


def cmd_links(args):
    flights, _, _ = load_flights(args.file)
    countries = parse_codes(args.countries)
    missing = [c for c in countries if c not in PORTALS]
    if missing:
        print(f"no Kayak or Skyscanner domain for {', '.join(missing)}, skipped. known: {', '.join(PORTALS)}", file=sys.stderr)
        countries = [c for c in countries if c in PORTALS]
    picked = []
    for _, _, o, b in best_combos(flights, lambda f: (f["price"], True))[:args.top]:
        picked += [f for f in (o, b) if f not in picked]
    if not picked:
        picked = sorted(flights, key=lambda f: f["price"])[:args.top]
    for f in picked:
        print(f"\n{f['id']}  {f['date']} {f['origin']}-{f['destination']}  {describe(f)}  Google €{f['price']}")
        for country in countries:
            for site, url in portal_links(f, country):
                print(f"  {country}  {site:18} {url}")


def ecb_rates():
    res = client().get(ECB)
    if res.status_code != 200:
        raise RuntimeError(f"ECB rates not available (http {res.status_code})")
    found = re.search(r"time='([\d-]+)'", res.text)
    if not found:
        raise RuntimeError("ECB answer has no rates")
    day = found.group(1)
    rates = {c: float(r) for c, r in re.findall(r"currency='([A-Z]{3})' rate='([\d.]+)'", res.text)}
    rates["EUR"] = 1.0
    return day, rates


def cmd_record(args):
    flights, _, _ = load_flights(args.file)
    matches = [f for f in flights if f["id"] == args.id]
    if not matches:
        sys.exit(f"unknown flight id {args.id}, see the ID column of the table")
    if len(matches) > 1:
        sys.exit(f"flight id {args.id} matches {len(matches)} flights, record it from a smaller search file")
    if args.price <= 0:
        sys.exit("price must be above 0")
    if not re.match(r"https?://", args.url):
        sys.exit("url must start with http:// or https://")
    amount = args.price * matches[0]["adults"] if args.per_person else args.price
    currency = args.currency.upper()
    day, rates = ecb_rates()
    if currency not in rates:
        sys.exit(f"no ECB rate for {currency}, known: {', '.join(sorted(rates))}")
    row = {"id": args.id, "site": args.site, "country": args.country.upper(), "amount": amount,
           "currency": currency, "eur": round(amount / rates[currency], 2), "rate_date": day,
           "url": args.url, "checked": datetime.now().isoformat(timespec="seconds")}
    out = Path(args.sites)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{args.id} {args.site} {row['country']}: {amount:.2f} {currency} = €{row['eur']}")


def main():
    p = argparse.ArgumentParser(prog="flight.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("country")
    s.add_argument("--proxy")
    s.set_defaults(fn=cmd_country)

    s = sub.add_parser("search")
    s.add_argument("--from", dest="origin", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--depart", required=True)
    s.add_argument("--return", dest="ret")
    s.add_argument("--adults", type=int, default=1)
    s.add_argument("--stops", type=int)
    s.add_argument("--country")
    s.add_argument("--proxy")
    s.add_argument("--pause", type=float, default=2.0)
    s.add_argument("--out", default="results/search.jsonl")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("table")
    s.add_argument("file", nargs="?", default="results/search.jsonl")
    s.add_argument("--baggage")
    s.add_argument("--sites", default="results/sites.jsonl")
    s.add_argument("--fx-fee", type=float, default=0.0)
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--max-hours", type=float)
    s.add_argument("--max-stops", type=int)
    s.add_argument("--board", default="results/board.html")
    s.add_argument("--title", default="Flight search")
    s.set_defaults(fn=cmd_table)

    s = sub.add_parser("links")
    s.add_argument("file", nargs="?", default="results/search.jsonl")
    s.add_argument("--countries", default="US,GB,DE,PL,TR,BR,IN,TH")
    s.add_argument("--top", type=int, default=2)
    s.set_defaults(fn=cmd_links)

    s = sub.add_parser("record")
    s.add_argument("--file", default="results/search.jsonl")
    s.add_argument("--sites", default="results/sites.jsonl")
    s.add_argument("--id", required=True)
    s.add_argument("--site", required=True)
    s.add_argument("--country", required=True)
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--currency", required=True)
    s.add_argument("--url", required=True)
    s.add_argument("--per-person", action="store_true")
    s.set_defaults(fn=cmd_record)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
