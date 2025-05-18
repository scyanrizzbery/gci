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
    

def search_for_card(year=None, card_name='', card_number='', include_variants=False, verbose=True):
    scene = obs_client.get_current_program_scene()
    if scene.scene_name == 'Green Screen':
        obs_client.set_scene_item_enabled('Green Screen', 1, False)
        obs_client.set_scene_item_enabled('Green Screen', 9, False)

    obs_client.set_source_filter_enabled('Razer', 'Chroma Key', False)

    time.sleep(0.2)

    obs_client.trigger_hot_key_by_name('OBSBasic.Screenshot')

    if not card_name:
        card_name = detect_front_name()

    new_card_name = input(f'Turn card around! 📷🔥 [{card_name}]: ')

    obs_client.trigger_hot_key_by_name('OBSBasic.Screenshot')

    obs_client.set_source_filter_enabled('Razer', 'Chroma Key', True)
    obs_client.set_scene_item_enabled('Green Screen', 9, True)

    if new_card_name:
        if new_card_name.startswith('+'):
           card_name = card_name + ' ' + new_card_name[1:]
        else:
           card_name = new_card_name

        if '=v' in card_name:
            include_variants = True
            card_name = card_name.replace('=v', '')
        if 'y=' in card_name:
            index = card_name.index('y=') + 2
            year = card_name[index:index+4]
            card_name = card_name.replace('y=' + year, '')
        if '=nv' in card_name:
            include_variants = False
            card_name = card_name.replace('=nv', '')
        if '=' in card_name:
            card_number = card_name[card_name.index('=') + 1:]
            card_name = card_name.replace('=' + card_number, '')

    if not card_number:
        card_number = detect_back_number()

    obs_client.set_scene_item_enabled('Green Screen', 1, True)

    if not card_number or not card_number.isdigit() or int(card_number) > 1900:
        card_number = input(f'Manually set card #? 📷🔥 [{card_number}]: ') or card_number

    cards = gci.get_card_info(card_name, year, card_number, include_variants=include_variants, verbose=verbose)

    time.sleep(1)

    if cards:
        card = cards[-1]
        sell_price = float(card['Sell'])
        psa10_price = float(card['PSA_10'])
        if sell_price < 1.00 and psa10_price < 15.00:
            logger.info('playing FTL')
            obs_client.set_scene_item_enabled('Green Screen', 8, True)
            time.sleep(3)
        elif sell_price > 5.00 and psa10_price > 30.00:
            logger.info('playing FTW')
            obs_client.set_scene_item_enabled('Green Screen', 5, True)
            time.sleep(2)


    obs_client.set_scene_item_enabled('Green Screen', 8, False)
    obs_client.set_scene_item_enabled('Green Screen', 5, False)

    return cards


def lookup(year, name='', number='', variants=True):
    cards = search_for_card(year=year, card_name=name, card_number=number, include_variants=variants)
    print(json.dumps(cards, indent=2))
