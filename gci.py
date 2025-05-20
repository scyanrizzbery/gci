#!/usr/bin/env python3

import argparse
import csv
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time

import requests

from requests.adapters import HTTPAdapter
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

from urllib3.util.retry import Retry


logger = logging.getLogger('gci')

BROWSER_PATH = '/usr/bin/brave-browser'
DRIVER_PATH = '/usr/local/bin/chromedriver'

options = Options()
options.binary_location = BROWSER_PATH
selenium_driver = webdriver.Chrome(options=options)


def cleanup(signal):
    selenium_driver.quit()
    sys.exit(1)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGABRT, cleanup)


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


def get_card_info(card_name, year, card_num, trading_card=False, variant_name='', verbose=False):
    api_key = os.getenv('SPORTS_CARDS_PRO_API_KEY')

    if not api_key:
        logger.error("❌ SPORTS_CARDS_PRO_API_KEY is not set.")
        return 1

    if not card_name:
        logger.error("Usage: get_card_info <card_name> [year] [card_number] [--variant-name] [--trading-card]")
        return 1

    year = str(year).strip() or ''

    if not year.isdigit():
        logger.error("Usage: get_card_info <card_name> [year] [card_number] [--variant-name] [--trading-card]")
        return 1

    query = f"{card_name} {year} {card_num}".strip()

    domain = "https://www.pricecharting.com" if trading_card else "https://www.sportscardspro.com"
    api_url = f"{domain}/api/products"
    product_url = f"{domain}/game/"

    if verbose:
        logger.debug(f"📡 Making request to: {api_url}")
        logger.debug(f"🔎 Query: q={query}")
        logger.debug(f"🔐 Using API key from $SPORTS_CARDS_PRO_API_KEY")
        logger.debug("----------------------------------------")

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests_retry_session().get(api_url, params=dict(t=api_key, q=query), headers=headers)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ HTTP request failed: {e}")
        return 1

    try:
        raw_response = response.json()
    except json.JSONDecodeError:
        logger.error("❌ Failed to parse JSON response.")
        return 1

    products = [{
        "Name": product.get('product-name'),
        "Set": product.get('console-name'),
        "Buy": "{:.02f}".format((product.get('retail-loose-buy') or 0) / 100),
        "Sell": "{:.02f}".format((product.get('retail-loose-sell') or 0) / 100),
        "PSA_9": "{:.02f}".format((product.get('graded-price') or 0) / 100),
        "PSA_10": "{:.02f}".format((product.get('manual-only-price') or 0) / 100),
        "URL": f"{product_url}{product.get('id')}",
    } for i, product in enumerate(raw_response.get('products', []), start=1)]

    filtered_results = []

    for product in products:
        console = product['Set'].lower()
        name = product['Name'].lower()

        if year and year not in console and year not in name:
            if verbose:
                logger.debug(f"skipping due to lack of year match: got {year}, not in {console} {name}")
            continue

        if card_num and card_num.strip().lower() not in name:
            if verbose:
                logger.debug(f"skipping due to lack of number match: got {card_num} not in {name}")
            continue

        if '[' in name: # it's a variant e.g. [Refractor]
            if not variant_name.strip() or variant_name.strip() not in name:
                if verbose:
                    logger.debug(f'skipping variant: {name} due to defined variant: {variant_name}')
                continue

        filtered_results.append(product)

    for i, product in enumerate(filtered_results, 1):
        product['i'] = i

    if filtered_results:
        if len(filtered_results) == 1:
            result = filtered_results[0]
        else:
            for item in filtered_results:
                print(f"{item['i']}). {item['Name']} - {item['Set']}")

            index_choice = ''
            while not index_choice or not index_choice.isdigit():
                index_choice = input('Choice [1]: ') or '1'
                if int(index_choice) not in range(len(filtered_results), 1):
                    continue
            result = filtered_results[int(index_choice) - 1]

        selenium_driver.get(result['URL'])

        with open('card-log.csv', 'a+') as fh:
            csv_writer = csv.DictWriter(fh, fieldnames=('Name', 'Set', 'Buy', 'Sell', 'PSA_9', 'PSA_10', 'URL'))

            if not fh.tell():
                csv_writer.writeheader()

            result.pop('i')
            csv_writer.writerow(result)

    return filtered_results


def main():
    import datetime

    parser = argparse.ArgumentParser(description="Fetch sports card data.")
    parser.add_argument("card_name", type=str, nargs="+", help="The name of the card to search for")
    parser.add_argument("card_num", type=str, help="Regex pattern for the card number")
    parser.add_argument("-y", "--year",  default=datetime.datetime.today().year - 1, help="The year of the card")
    parser.add_argument("-t", "--trading-card", action="store_true", help="Trading card game such as Magic The Gathering (c)")
    parser.add_argument("-v", "--variant", type=str, help="Include variants")
    parser.add_argument("-V", "--verbose", action="store_true", help="Verbose")

    args = parser.parse_args()
    results = get_card_info(
        card_name=args.card_name,
        year=args.y,
        card_num=args.card_num,
        trading_card=args.trading_card,
        variant_name=args.variant,
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

