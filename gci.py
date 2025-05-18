#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import time

import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def requests_retry_session(retries=3, backoff_factor=0.3, status_forcelist=(404,), session=None):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def sanitize_query_string(s):
    """Strip regex-special characters for query use (not regex match)."""
    return re.sub(r'[\[\]\(\)\{\}\.\*\+\?\^\$\|\\]', '', s).lower()


def get_card_info(card_name, year, card_num, trading_card=False, include_variants=False, verbose=False):
    api_key = os.getenv('SPORTS_CARDS_PRO_API_KEY')

    if not api_key:
        print("❌ SPORTS_CARDS_PRO_API_KEY is not set.", file=sys.stderr)
        return 1

    if not card_name:
        print("Usage: get_card_info <card_name> [year] [card_number] [--include-variants] [--trading-card]", file=sys.stderr)
        return 1

    # Cleaned version used for API query string
    clean_pattern_text = sanitize_query_string(card_num) if card_num else ''

    year = str(year).strip() or ''

    if not year.isdigit() or int(year) < 1900:
        print("Usage: get_card_info <card_name> [year] [card_number] [--include-variants] [--trading-card]", file=sys.stderr)
        return 1


    query = f"{card_name} {year} {clean_pattern_text}".strip()

    domain = "https://www.pricecharting.com" if trading_card else "https://www.sportscardspro.com"
    api_url = f"{domain}/api/products"
    product_url = f"{domain}/game/"

    if verbose:
        print(f"📡 Making request to: {api_url}", file=sys.stderr)
        print(f"🔎 Query: q={query}", file=sys.stderr)
        print(f"🔐 Using API key from $SPORTS_CARDS_PRO_API_KEY", file=sys.stderr)
        print("----------------------------------------", file=sys.stderr)

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests_retry_session().get(api_url, params=dict(t=api_key, q=query), headers=headers)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ HTTP request failed: {e}", file=sys.stderr)
        return 1

    try:
        raw_response = response.json()
    except json.JSONDecodeError:
        print("❌ Failed to parse JSON response.", file=sys.stderr)
        return 1

    products = [{
        "Name": product.get('product-name'),
        "Set": product.get('console-name'),
        "Buy": "{:.02f}".format((product.get('retail-loose-buy') or 0) / 100),
        "Sell": "{:.02f}".format((product.get('retail-loose-sell') or 0) / 100),
        "PSA_9": "{:.02f}".format((product.get('graded-price') or 0) / 100),
        "PSA_10": "{:.02f}".format((product.get('manual-only-price') or 0) / 100),
        "URL": f"{product_url}{product.get('id')}",
    } for product in reversed(raw_response.get('products', []))]

    filtered_results = []

    for product in products:
        console = product['Set'].lower()
        name = product['Name'].lower()

        if year and year not in console and year not in name:
            if verbose:
                print(f"skipping due to lack of year match: got {year}, not in {console} {name}", file=sys.stderr)
            continue

        if card_num and card_num.strip().lower() not in name:
            if verbose:
                print(f"skipping due to lack of number match: got {clean_pattern_text} not in {name}", file=sys.stderr)
            continue

        if not include_variants and '[' in name:
            if verbose:
                print(f'skipping variant: {name}')
            continue

        filtered_results.append(product)

    try:
        print(json.dumps(filtered_results, indent=2, ensure_ascii=False))
    except BrokenPipeError:
        # Exit cleanly if output pipe is closed early (e.g. with jq)
        sys.stderr.close()
        sys.exit(0)

    if filtered_results:
        subprocess.Popen(['open', filtered_results[-1]['URL']], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with open('card-log.csv', 'a+') as fh:
            csv_writer = csv.DictWriter(fh, fieldnames=('Name', 'Set', 'Buy', 'Sell', 'PSA_9', 'PSA_10', 'URL'))
            csv_writer.writerow(filtered_results[-1])

    return filtered_results


def main():
    import datetime

    parser = argparse.ArgumentParser(description="Fetch sports card data.")
    parser.add_argument("card_name", type=str, nargs="+", help="The name of the card to search for")
    parser.add_argument("card_num", type=str, help="Regex pattern for the card number")
    parser.add_argument("-y", default=datetime.datetime.today().year - 1, help="The year of the card")
    parser.add_argument("-t", "--trading-card", action="store_true", help="Trading card game such as Magic The Gathering (c)")
    parser.add_argument("-i", "--include-variants", action="store_true", help="Include variants")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose")

    args = parser.parse_args()
    results = get_card_info(
        card_name=args.card_name,
        year=args.y,
        card_num_pattern=args.card_num,
        trading_card=args.trading_card,
        include_variants=args.include_variants,
        verbose=args.verbose
    )
    sys.exit(0 if results else 1)


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        main()
    except BrokenPipeError:
        # This is handled more explicitly in get_card_info, but also catch top-level
        pass

