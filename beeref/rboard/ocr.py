# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Text recognition using the OCR engine built into Windows 10/11.

Runs without a model download; the language packs installed in Windows
determine which scripts are recognised.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import (
        DataWriter, InMemoryRandomAccessStream)
except ImportError:  # Not on Windows, or bindings missing
    OcrEngine = None


def is_available():
    return (OcrEngine is not None
            and OcrEngine.try_create_from_user_profile_languages() is not None)


def max_dimension():
    return OcrEngine.max_image_dimension if OcrEngine else 0


async def _recognize(png_bytes):
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    result = await engine.recognize_async(bitmap)
    return '\n'.join(line.text for line in result.lines)


def recognize(png_bytes):
    """Return the text found in an encoded image, one line per text line.

    Safe to call from a worker thread (it runs its own event loop).
    """
    if OcrEngine is None:
        raise RuntimeError('Text recognition needs Windows 10 or newer.')
    return asyncio.run(_recognize(png_bytes))
