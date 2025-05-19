import datetime
import json
import logging
import os
import re
import time

import boto3
import cv2
import requests
import obsws_python as obs

import gci

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


OBS_PASSWORD = os.getenv('OBS_WS_PASSWORD')
OBS_GREEN_SCREEN_SCENE_NAME = os.getenv('OBS_GREEN_SCREEN_SCENE_NAME', 'Green Screen')
OBS_ITEMS_TO_SUSPEND = map(int, os.getenv('OBS_ITEMS_TO_SUSPEND', '1,9').split(','))
OBS_FTL_ITEM_ID = int(os.getenv('OBS_FTL_ITEM_ID', '8'))
OBS_FTW_ITEM_ID = int(os.getenv('OBS_FTW_ITEM_ID', '5'))
OBS_CAMERA_SOURCE_NAME = os.getenv('OBS_CAMERA_SOURCE_NAME', 'Razer')

obs_client = obs.ReqClient(host='localhost', port=4455, password=OBS_PASSWORD, timeout=3)

rek_client = boto3.client('rekognition')

logger = logging.getLogger('gci')
logger.setLevel(logging.INFO)


def capture_card(device=4):
    cap = cv2.VideoCapture(device)

    ret, frame = cap.read()

    if frame is None:
        return None

    cap.release()

    success, buffer = cv2.imencode('.jpg', frame)
    if not success:
        raise RuntimeError("Failed to encode frame")

    return buffer.tobytes()
    

def detect_front_name(confidence=51):
    img_bytes = capture_card()
    if img_bytes is None:
        return None

    r = rek_client.detect_text(Image={'Bytes': img_bytes})

    logger.debug(f"got TextDetections: {r['TextDetections']}")

    lines = [text['DetectedText'] for text in r['TextDetections'] if text['Type'] == 'LINE' and text['Confidence'] > confidence]
    for line in reversed(lines):
        if re.search(r'\w{2,} \w{2,}', line):
            logger.info(f'found {line}')
            return line

    return None


def detect_back_number():
    img_bytes = capture_card()
    if img_bytes is None:
        return None

    r = rek_client.detect_text(Image={'Bytes': img_bytes})
    lines = [text['DetectedText'] for text in r['TextDetections'] if text['Type'] == 'LINE']
    for line in lines:
       re_match = re.search(r'((\w+-)?\d+)', line)
       if re_match:
           line = re_match.group(1)
           logger.info(f'found {line}')
           return line

    return None
    

def search_for_card(year=None, card_name='', card_number='', variant_name='', verbose=False):
    scene = obs_client.get_current_program_scene()
    if scene.scene_name == OBS_GREEN_SCREEN_SCENE_NAME:
        for itemId in OBS_ITEMS_TO_SUSPEND:
            obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, itemId, False)

    obs_client.set_source_filter_enabled(OBS_CAMERA_SOURCE_NAME, 'Chroma Key', False)

    time.sleep(0.2)

    obs_client.trigger_hot_key_by_name('OBSBasic.Screenshot')

    if not card_name:
        card_name = detect_front_name()

    new_card_name = input(f'Turn card around! 📷🔥 [{card_name}]: ')

    obs_client.trigger_hot_key_by_name('OBSBasic.Screenshot')

    obs_client.set_source_filter_enabled(OBS_CAMERA_SOURCE_NAME, 'Chroma Key', True)

    for itemId in OBS_ITEMS_TO_SUSPEND:
        obs_client.set_scene_item_enabled(OBS_CAMERA_SOURCE_NAME, itemId, True)

    variant_enabled_re = re.compile(r'\sv=(?P<value>[^=]*)')
    variant_disabled_re = re.compile(r'\snv=')
    year_operator_re = re.compile(r'\sy=(?P<value>\d{2,4})')
    number_operator_re = re.compile(r'\s=(?P<value>[^\s]+)')
    verbose_operator_re = re.compile(r'\sV=')

    if new_card_name:
        if new_card_name.startswith('+'):
           card_name = card_name + ' ' + new_card_name[1:]
        else:
           card_name = new_card_name

        variant_enabled_match = variant_enabled_re.search(new_card_name)
        variant_disabled_match = variant_disabled_re.search(new_card_name)

        if variant_enabled_match:
            logger.debug(f'found variant enabled operator: {variant_enabled_match.groupdict()}')
            variant_name = variant_enabled_match.group('value').strip()
            card_name = variant_operator_re.sub('', card_name)
        elif variant_disabled_match:
            logger.debug(f'found variant disabled operator: {variant_disabled_match.groupdict()}')
            variant_name = ''
            card_name = variant_disabled_re.sub('', card_name)

        year_match = year_operator_re.search(new_card_name)
        if year_match:
            logger.debug(f'found year: {year_match.groupdict()}')
            today = datetime.date.today()
            year = int(year_match.group('value'))
            if year < 100:
                if 0 < year < today.year - 2000:
                    year = 1900 + year
                else:
                    year = 2000 + today.year
            card_name = year_operator_re.sub('', card_name)

        number_match = number_operator_re.search(new_card_name)
        if number_match:
            logger.debug(f'found number: {number_match.groupdict()}')
            card_number = number_match.group('value')
            card_name = number_operator_re.sub('', card_name)

        verbose_match = verbose_operator_re.search(new_card_name)
        if verbose_match:
            logger.debug(f'found verbose: {verbose_match.groupdict()}')
            verbose = True
            card_name = verbose_operator_re.sub('', card_name)

    if not card_number:
        card_number = detect_back_number()

    for itemId in OBS_ITEMS_TO_SUSPEND:
        obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, itemId, True)

    if not card_number or not card_number.isdigit() or int(card_number) > 1900:
        card_number = input(f'Manually set card #? 📷🔥 [{card_number}]: ') or card_number

    cards = gci.get_card_info(card_name, year, card_number, variant_name=variant_name, verbose=verbose)

    time.sleep(1)

    if cards:
        card = cards[-1]
        sell_price = float(card['Sell'])
        psa10_price = float(card['PSA_10'])
        if sell_price < 1.00 and psa10_price < 15.00:
            logger.info('playing FTL')
            obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, OBS_FTL_ITEM_ID, True)
            time.sleep(3)
        elif sell_price > 5.00 and psa10_price > 30.00:
            logger.info('playing FTW')
            obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, OBS_FTW_ITEM_ID, True)
            time.sleep(2)

    obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, OBS_FTL_ITEM_ID, False)
    obs_client.set_scene_item_enabled(OBS_GREEN_SCREEN_SCENE_NAME, OBS_FTW_ITEM_ID, False)

    return cards


def lookup(year, name='', number='', variant=''):
    cards = search_for_card(year=year, card_name=name, card_number=number, variant_name=variant)
    print(json.dumps(cards, indent=2))
