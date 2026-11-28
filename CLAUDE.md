# Flight search: instructions for the agent

You find the cheapest flights for the user. Tools:

- `uv run flight.py` in this folder: Google Flights search, tables, portal links, price records.
- A browser (Playwright MCP) for airline and booking sites.
- searchify for web search (airports, baggage rules, airline sites): the MCP tool `passages`, or without MCP `uvx --from "searchify[rerank]" searchify passages "<question>" -k 5`.

Talk to the user in their language. Tables stay as the script prints them.

## 1. Interview

Read the user's message first. Then ask only what is missing, all in one question round (AskUserQuestion if available):

1. From where (a city is enough)
2. To where
3. Outbound date and how flexible (for example 2 days earlier or later)
4. Return date and flexibility, or one way
5. How many adults
6. Baggage, only if the message says nothing about it: hand luggage only, 1 checked bag (23 kg) per person, or more
7. Payment: how they pay (credit card, debit card, PayPal), whether paying in a foreign currency is fine, and the card fee for foreign currencies if they know it (often 0 to 2 %)
8. Where to buy: which countries or regions to compare. Offer the default list US, GB, DE, PL, TR, BR, IN, TH, or "Europe only", or their own list

Assume without asking and name it in the plan: economy, connections allowed, nearby airports up to about 3 hours by train or car.

Before starting, show the plan in four lines: airports, days, countries, sites. Add the estimated time: Google queries times countries times 3 seconds, plus about 1 minute per site check.

Example plan:

```
Airports  BER, LEJ to LIS, OPO
Days      out 14 to 17 Jan, back 21 to 23 Jan (28 queries)
Countries DE, GB, PL, TR, BR (VPN via Mullvad)
Sites     airline, Kayak, Skyscanner, one local portal for the 2 best combinations
Time      about 7 min Google, about 40 min sites
```

## 2. Airports

Cities become IATA codes (Berlin BER, Lisbon LIS). Add nearby airports when they are realistic (for Berlin LEJ, PRG, HAM; check with searchify if unsure). At most 4 airports per side.

## 3. Google Flights from the home country

```
uv run flight.py search --from BER,LEJ --to LIS,OPO --depart 2027-01-14..2027-01-17 --return 2027-01-21..2027-01-23 --adults 2 --out results/lisbon.jsonl
```

- Dates: single with commas (`2027-01-14,2027-01-16`) or as a range (`2027-01-14..2027-01-17`).
- `--stops 0` only if the user wants nonstop flights.
- Run more than 40 queries in the background.
- One file per search and passenger count. `table` stops if a file mixes passenger counts.
- Exit code 1 means captcha or not a single flight found. Do not retry right away, read the error rows in the file.

## 4. Switching countries

For every country from the interview, repeat the Google search with `--country <CODE>` into the same file. The script checks the real IP. Exit code 2 means the VPN is not up yet or the country is wrong: wait 5 seconds, retry once, otherwise skip the country. Exit code 1 after a captcha: skip the country. Use `--force` only if the user asks for it.

Tell the user before the first switch that changing the VPN briefly drops the connection, yours too.

Which way, in this order:

1. **Mullvad** (`mullvad status` works): remember the status at the start. Per country `mullvad relay set location <code in lower case>`, then `mullvad connect`, wait until `mullvad status` says Connected (at most 30 seconds). `mullvad relay list` shows which countries exist. Restore the starting status at the end.
2. **Proxy** (the user gives a SOCKS5 or HTTP address, or `FLIGHT_PROXY` is in `.env`): `--proxy <address> --country <CODE>`. With `.env`: `uv run --env-file .env flight.py ...`. The browser only uses the proxy if Playwright MCP was started with `--proxy-server`.
3. **Tor** (`tor --version` works): start `tor --SocksPort 9150 --ExitNodes "{us}" --StrictNodes 1` in the background, then `--proxy socks5h://127.0.0.1:9150 --country US`. Restart per country, stop at the end. Google often shows Tor a captcha, then skip the country.
4. **Any other VPN app**: ask the user to switch the country in their app and reply "go on". Then `--country <CODE>`.

Do step 5 for a country while its VPN is still on, then switch to the next country.

## 5. Airline and booking sites per country

Google Flights showed the same price from every country in tests. Differences, if any, appear directly on airline and booking sites, so check those for the best flights.

1. `uv run flight.py table results/<file>.jsonl` and take the IDs from "Round trip: cheapest combinations" (default the best 2). For one way trips take them from "Outbound: cheapest flights".
2. `uv run flight.py links results/<file>.jsonl --countries <countries> --top 2` prints the Kayak and Skyscanner links per country for those flights. Domains exist for US, GB, DE, AT, CH, FR, ES, IT, NL, PT, PL, TR, BR, IN, TH; other countries are skipped there, check their sites by hand.
3. Per country, in the browser, while the VPN for that country is on:
   - **Airline site**: find the official site with searchify if unsure, choose that country's version or market and its currency, search the same date and route.
   - **Kayak and Skyscanner**: open the links from step 2.
   - **One local portal**, for example US expedia.com, GB opodo.co.uk, DE check24.de, PL esky.pl, TR enuygun.com, BR decolar.com, IN makemytrip.com, TH traveloka.com. Only well known sites.
4. Find exactly the same flight (same airline and times), read the price and the currency, then record it. Many sites (Kayak, Skyscanner, the Ryanair API) show the price per person: then add `--per-person`, the script multiplies by the adults of the search.

```
uv run flight.py record --file results/<file>.jsonl --id b7864b1cc2 --site ryanair.com --country GB --price 46.85 --currency GBP --per-person --url "<page url>"
```

- Only record prices you saw on the page. Never estimate.
- Skip sites where the user cannot pay with their method (local payment only, local ID number required) and say so in the result.
- Captcha in the browser: ask the user to solve it in the open window, or skip the site.
- Never log in, never enter personal or payment data, stop before the payment page.
- Ryanair has a price API that works without a browser: `https://www.ryanair.com/api/farfnd/v4/oneWayFares?departureAirportIataCode=LIS&arrivalAirportIataCode=BER&outboundDepartureDateFrom=2027-01-22&outboundDepartureDateTo=2027-01-22&market=en-gb&currency=GBP` (market and currency per country). It returns only the cheapest flight of that day, per person. Use it only when `flightNumber` and `departureDate` match the flight of the ID, record with `--per-person` and the API URL as source.

## 6. Baggage

Only if the user takes checked bags.

1. Note the airlines in the tables.
2. Per airline, find the rule, best on the airline's own site, with searchify (`passages`, or the `uvx` command from the top): "<airline> economy checked bag 23 kg fee".
3. Write `results/baggage.json`, names exactly as in the table:

```json
{
  "easyJet": {"included": false, "fee": 45, "source": "https://..."},
  "Tap Air Portugal": {"included": true, "source": "https://..."}
}
```

- `fee` is euro per person per flight for the requested bags.
- For names like "Lufthansa, Tap Air Portugal" the first name counts, unless there is an entry for the full name.
- Only with a source. Without proof leave it out, the table then shows "+ bag ?". Never guess.

Repeat until the top rows show no "?", or say in the result where it stays open.

## 7. Showing the result

```
uv run flight.py table results/<file>.jsonl --baggage results/baggage.json --fx-fee 1.75 --title "Berlin to Lisbon, January"
```

- `--fx-fee` is the card fee from the interview, 0 if they pay without one.
- Copy the Markdown tables into the chat and open `results/board.html` (Mac `open`, Linux `xdg-open`, Windows `start`).
- First line of the answer: the cheapest option with total price (with bags if asked), dates, airlines, where to buy and the link.
- Then the tables. Say whether a country or site was cheaper, and by how much after the card fee.
- Remind the user: the "As package" link shows the real round trip, which can be cheaper than two single flights. Check the top one or two there.

Example first lines:

```
Cheapest: €121 for 1 adult, easyJet BER-OPO 15 Jan 13:30 and Ryanair LIS-BER 22 Jan 06:20.
No country was cheaper on Google. ryanair.com in PT €56 instead of €57, GB and PL the same after the card fee.
```

## Rules

- Never book, never enter payment or personal data.
- Only name prices from flight.py results, recorded site prices or cited sources.
- Pause between Google queries at least 2 seconds. On a captcha skip the country, do not hammer.
- `results/` stays local and is never committed.
