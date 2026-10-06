# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Import images from Are.na channels and blocks.

Are.na blocks plain HTTP clients, so pages are read with a real
(headless) Chromium driven by Playwright. Thumbnails on the page point
at Are.na's image service with resize edits encoded in the URL; we
decode the original file key from them and request the original, or a
server-side resized version when the user caps the image size.
"""

import base64
import json
import logging
import re
import subprocess
import sys
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

IMAGE_HOST = 'https://images.are.na/'
# Serves originals too large for the resizing service:
RAW_HOST = 'https://d2w9rnfcy7mm78.cloudfront.net/'
SITE = 'https://www.are.na'
MAX_IDLE_SCROLLS = 6
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

COLLECT_JS = """() => [...document.querySelectorAll('img')].map(img => {
    const a = img.closest('a[href*="/block/"]');
    return [img.currentSrc || img.src, a ? a.getAttribute('href') : null];
})"""


class ArenaError(Exception):
    pass


def is_arena_url(url):
    return bool(re.match(r'^https?://(www\.)?are\.na/.+', url.strip()))


def channel_url(url):
    """Normalise a link so the same channel always compares equal."""
    url = re.sub(r'[?#].*', '', url.strip()).rstrip('/')
    return re.sub(r'^https?://(www\.)?are\.na', SITE, url)


def decode_key(src):
    """The original-file key from an images.are.na URL, or None."""
    if not src or not src.startswith(IMAGE_HOST):
        return None
    token = src[len(IMAGE_HOST):].split('?')[0]
    try:
        spec = json.loads(base64.b64decode(token + '=' * (-len(token) % 4)))
    except ValueError:
        return None
    if spec.get('bucket') != 'arena_images':
        return None
    return spec.get('key')


def image_url(key, max_side=None):
    edits = {}
    if max_side:
        edits['resize'] = {'width': max_side, 'height': max_side,
                           'fit': 'inside', 'withoutEnlargement': True}
    spec = {'bucket': 'arena_images', 'key': key, 'edits': edits}
    return IMAGE_HOST + base64.b64encode(json.dumps(spec).encode()).decode()


def _launch(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as e:
        if 'Executable doesn\'t exist' not in str(e):
            raise
        logger.info('Installing Chromium for Playwright...')
        subprocess.run([sys.executable, '-m', 'playwright', 'install',
                        'chromium'], check=True)
        return playwright.chromium.launch(headless=True)


def fetch(url, max_side=None, skip_keys=(), on_found=None, on_image=None,
          is_canceled=lambda: False):
    """Read an Are.na page and download its images.

    :param skip_keys: image keys already on the board (for syncing)
    :param on_found: called with (number of images to download)
    :param on_image: called with (index, entry dict, image bytes) per image;
        entry has 'key', 'source_url' and 'channel'
    :returns: (page title, number of failed downloads)
    """
    from playwright.sync_api import sync_playwright

    url = channel_url(url)
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={'width': 1400, 'height': 1000})
            page = context.new_page()
            response = page.goto(url, wait_until='networkidle', timeout=60000)
            if response and response.status >= 400:
                raise ArenaError(f'Are.na returned HTTP {response.status}')
            title = page.title().removesuffix(' | Are.na')

            entries, seen, idle = [], set(), 0
            while idle < MAX_IDLE_SCROLLS and not is_canceled():
                new = 0
                for src, href in page.evaluate(COLLECT_JS):
                    key = decode_key(src)
                    if key and key not in seen:
                        seen.add(key)
                        new += 1
                        entries.append({
                            'key': key,
                            'source_url': urljoin(SITE, href) if href else url,
                            'channel': url,
                        })
                idle = 0 if new else idle + 1
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)

            todo = [e for e in entries if e['key'] not in skip_keys]
            if on_found:
                on_found(len(todo))
            failed = 0
            for i, entry in enumerate(todo):
                if is_canceled():
                    break
                headers = {'Referer': url}
                r = context.request.get(image_url(entry['key'], max_side),
                                        headers=headers, timeout=60000)
                if not r.ok:
                    r = context.request.get(RAW_HOST + entry['key'],
                                            headers=headers, timeout=120000)
                if r.ok:
                    on_image(i, entry, r.body())
                else:
                    logger.info(f'Download failed ({r.status}): {entry}')
                    failed += 1
            return title, failed
        finally:
            browser.close()
