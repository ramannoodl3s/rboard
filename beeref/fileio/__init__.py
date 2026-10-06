# This file is part of BeeRef.
#
# BeeRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BeeRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BeeRef.  If not, see <https://www.gnu.org/licenses/>.

import logging

from PyQt6 import QtCore

from beeref import commands
from beeref.fileio.errors import BeeFileIOError
from beeref.fileio.image import load_image_data
from beeref.fileio.sql import SQLiteIO, is_bee_file, is_rboard_file
from beeref.items import BeePixmapItem
from beeref.rboard import imagestore, sidecar


__all__ = [
    'is_bee_file',
    'is_rboard_file',
    'load_bee',
    'save_bee',
    'load_images',
    'ThreadedLoader',
    'BeeFileIOError',
]

logger = logging.getLogger(__name__)


def load_bee(filename, scene, worker=None):
    """Load BeeRef native file."""
    logger.info(f'Loading from file {filename}...')
    io = SQLiteIO(filename, scene, readonly=True, worker=worker)
    return io.read()


def save_bee(filename, scene, create_new=False, worker=None):
    """Save BeeRef native file."""
    logger.info(f'Saving to file {filename}...')
    logger.debug(f'Create new: {create_new}')
    io = SQLiteIO(filename, scene, create_new, worker=worker)
    io.write()
    logger.info('End save')


def load_images(filenames, pos, scene, worker):
    """Add images to existing scene."""

    errors = []
    items = []
    worker.begin_processing.emit(len(filenames))
    # R Board: read every file, then decode them in parallel, each at
    # the resolution imagestore keeps
    datas, names = [], []
    for filename in filenames:
        logger.info(f'Loading image from file {filename}')
        data, name = load_image_data(filename)
        datas.append(data)
        names.append(name)
        if worker.canceled:
            break
    sources = imagestore.decode_many(
        datas, on_progress=lambda done, total: worker.progress.emit(
            round(done * len(names) / max(total, 1)) - 1),
        is_canceled=lambda: worker.canceled)

    for source, filename in zip(sources, names):
        if source is None:
            logger.info(f'Could not load file {filename}')
            errors.append(filename)
            continue
        item = BeePixmapItem(source, filename)
        sidecar.apply(item, filename)  # R Board: source links (links.txt)
        item.set_pos_center(pos)
        scene.add_item_later({'item': item, 'type': 'pixmap'}, selected=True)
        items.append(item)

    scene.undo_stack.push(
        commands.InsertItems(scene, items, ignore_first_redo=True))
    worker.finished.emit('', errors)


class ThreadedIO(QtCore.QThread):
    """Dedicated thread for loading and saving."""

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str, list)
    begin_processing = QtCore.pyqtSignal(int)
    user_input_required = QtCore.pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.kwargs['worker'] = self
        self.canceled = False

    def run(self):
        self.func(*self.args, **self.kwargs)

    def on_canceled(self):
        self.canceled = True
