# This file is part of R Board, a fork of BeeRef.
#
# R Board is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Softclub themes.

Six presets come from the design tokens. Custom themes are built from
four base colours (canvas, surface, ink, accent); every other token is
derived from those, and any token can be overridden.
"""

import json
import logging
import os

from PyQt6 import QtCore, QtGui, QtWidgets

from beeref import constants


logger = logging.getLogger(__name__)

_DIR = os.path.dirname(__file__)
with open(os.path.join(_DIR, 'softclub_tokens.json'), encoding='utf-8') as f:
    TOKENS = json.load(f)

DEFAULT_THEME = 'carbon'
BASE_KEYS = ('canvas', 'surface', 'ink', 'accent')
LIGHT_TONE = {'pictogram', 'survivor'}

# Tokens a custom theme can edit, in display order
EDITABLE = ('canvas', 'surface', 'surface-raised', 'surface-sunken',
            'divider', 'control-border', 'hover', 'ink', 'ink-muted',
            'accent', 'accent-strong', 'accent-soft', 'on-accent',
            'selection', 'danger')


def _presets():
    themes = {}
    for theme in TOKENS['color']['themes']:
        tid = theme['id']
        colors = {t['name']: (t['value'][tid] if isinstance(t['value'], dict)
                              else t['value'])
                  for t in TOKENS['color']['tokens']}
        # Some tokens are aliases, e.g. focus-ring = "{accent}"
        for name, value in colors.items():
            if value.startswith('{'):
                colors[name] = colors[value.strip('{}')]
        themes[tid] = {
            'id': tid,
            'name': theme['name'],
            'tone': 'light' if tid in LIGHT_TONE else 'dark',
            'colors': colors,
        }
    return themes


PRESETS = _presets()
PALETTE_KEYS = [k for k in PRESETS[DEFAULT_THEME]['colors']
                if k.startswith('palette-')]
SIZES = {t['name']: t['value'] for group in ('spacing', 'radius', 'size')
         for t in TOKENS[group]['tokens']}


# Helvetica Neue in the three weights the design uses. Some installs of
# plain "Helvetica Neue" map Regular/Light to italic files, so the LT Std
# family (separate family per weight) is preferred when present.
FONT_CHOICES = {
    'light': [('HelveticaNeueLT Std Lt', None), ('Helvetica Neue', 'Light'),
              ('Arial', None)],
    'regular': [('HelveticaNeueLT Std', '55 Roman'),
                ('Helvetica Neue', 'Regular'), ('Arial', None)],
    'medium': [('HelveticaNeueLT Std Med', None),
               ('Helvetica Neue', 'Medium'), ('Arial', None)],
}
WEIGHTS = {'light': QtGui.QFont.Weight.Light,
           'regular': QtGui.QFont.Weight.Normal,
           'medium': QtGui.QFont.Weight.Medium}
_font_cache = {}
_custom = {'family': None}


def fonts_dir():
    from beeref.config import BeeSettings
    return os.path.join(os.path.dirname(BeeSettings().fileName()), 'fonts')


def load_custom_font():
    """Pick up the interface font chosen in settings: an added font file
    or an installed family. Empty means the design's Helvetica Neue."""
    from beeref.config import BeeSettings
    settings = BeeSettings()
    family = None
    path = settings.valueOrDefault('Appearance/font_file')
    if path and os.path.isfile(path):
        font_id = QtGui.QFontDatabase.addApplicationFont(path)
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        family = families[0] if families else None
    if family is None:
        family = settings.valueOrDefault('Appearance/font_family') or None
        if family and family not in QtGui.QFontDatabase.families():
            family = None
    _custom['family'] = family
    _font_cache.clear()


def add_font_file(path):
    """Copy a font file into the settings folder; returns its family name
    (or None if Qt can't read it) and the copied path."""
    import shutil
    font_id = QtGui.QFontDatabase.addApplicationFont(path)
    families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return None, None
    os.makedirs(fonts_dir(), exist_ok=True)
    target = os.path.join(fonts_dir(), os.path.basename(path))
    if os.path.normcase(os.path.abspath(path)) != \
            os.path.normcase(os.path.abspath(target)):
        shutil.copyfile(path, target)
    return families[0], target


def font_spec(weight='regular'):
    if _custom['family']:
        return _custom['family'], None
    if weight not in _font_cache:
        families = set(QtGui.QFontDatabase.families())
        for family, style in FONT_CHOICES[weight]:
            if family in families:
                _font_cache[weight] = (family, style)
                break
        else:
            _font_cache[weight] = ('Arial', None)
    return _font_cache[weight]


def ui_font(size=12, weight='regular'):
    """A QFont in the interface typeface at a pixel size."""
    family, style = font_spec(weight)
    font = QtGui.QFont(family)
    if style:
        font.setStyleName(style)
    elif _custom['family'] or family == 'Arial':
        font.setWeight(WEIGHTS[weight])
    font.setPixelSize(size)
    return font


def system_scale():
    """Windows' display scaling for the main screen (1.0 = 100%), read
    before Qt starts."""
    if os.name != 'nt':
        return 1.0
    try:
        import ctypes
        percent = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        return max(1.0, percent / 100)
    except (AttributeError, OSError):
        return 1.0


def apply_interface_scale(settings):
    """Scale the whole interface (call before the QApplication exists).
    The setting is relative to a 96 dpi screen, so screens Windows
    already scales up aren't scaled twice."""
    if 'QT_SCALE_FACTOR' in os.environ:
        return
    wanted = settings.valueOrDefault('Appearance/ui_scale') / 100
    factor = wanted / system_scale()
    if factor > 1.01:
        os.environ['QT_SCALE_FACTOR'] = f'{factor:.3f}'


def px(name):
    """A size token as an int, e.g. px('radius-lg') -> 18."""
    value = SIZES[name]
    return 999 if value.endswith('999px') else int(float(value.rstrip('px')))


# ---------- colour maths ----------

def _rgb(hex_color):
    c = QtGui.QColor(hex_color)
    return c.redF(), c.greenF(), c.blueF()


def mix(a, b, amount):
    """Blend colour a towards b by amount (0..1)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    c = QtGui.QColor.fromRgbF(ra + (rb - ra) * amount,
                              ga + (gb - ga) * amount,
                              ba + (bb - ba) * amount)
    return c.name()


def luminance(hex_color):
    def channel(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def derive(base, tone=None):
    """All colour tokens from the four base colours."""
    canvas, surface = base['canvas'], base['surface']
    ink, accent = base['ink'], base['accent']
    if tone is None:
        tone = 'light' if luminance(canvas) > 0.4 else 'dark'
    dark = tone == 'dark'
    raised = (mix(surface, ink, 0.07) if dark
              else mix(surface, '#ffffff', 0.55))
    colors = {
        'canvas': canvas,
        'surface': surface,
        'surface-raised': raised,
        'surface-sunken': mix(surface, '#000000', 0.4) if dark
        else mix(surface, ink, 0.1),
        'divider': mix(surface, ink, 0.13 if dark else 0.15),
        'control-border': mix(surface, ink, 0.45 if dark else 0.55),
        'hover': mix(raised, ink, 0.08),
        'ink': ink,
        'ink-muted': mix(ink, surface, 0.3),
        'accent': accent,
        'accent-strong': mix(accent, '#ffffff' if dark else '#000000', 0.15),
        'accent-soft': mix(raised, accent, 0.2),
        'on-accent': '#16161a' if luminance(accent) > 0.35 else '#ffffff',
        'selection': accent,
        'focus-ring': accent,
        'danger': '#e8907c' if dark else '#a8321e',
        'on-danger': '#16161a' if dark else '#ffffff',
    }
    # Hold the design's contrast rules on every surface: muted text 4.5:1,
    # control outlines 3:1 (pull them towards ink until they pass)
    grounds = [colors[k] for k in ('canvas', 'surface', 'surface-raised',
                                   'surface-sunken', 'hover', 'accent-soft')]
    for key, target, start in (('ink-muted', 4.5, 0.3),
                               ('control-border', 3.0, 0.45)):
        amount = start
        while amount > 0 and min(contrast(colors[key], g)
                                 for g in grounds) < target:
            amount -= 0.02
            colors[key] = mix(ink, surface, amount) if key == 'ink-muted' \
                else mix(surface, ink, 1 - amount)
    for key in PALETTE_KEYS:
        colors[key] = PRESETS[DEFAULT_THEME]['colors'][key]
    return colors


# ---------- theme registry ----------

class ThemeManager(QtCore.QObject):
    """Holds the active theme and applies it app-wide."""

    changed = QtCore.pyqtSignal()
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.theme = dict(PRESETS[DEFAULT_THEME])

    # -- persistence (QSettings) --

    @staticmethod
    def _settings():
        from beeref.config import BeeSettings
        return BeeSettings()

    def custom_themes(self):
        raw = self._settings().value('Appearance/custom_themes', '[]')
        try:
            themes = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [t for t in themes if isinstance(t, dict) and 'id' in t]

    def save_custom_theme(self, theme):
        themes = [t for t in self.custom_themes() if t['id'] != theme['id']]
        themes.append(theme)
        self._settings().setValue('Appearance/custom_themes',
                                  json.dumps(themes))

    def delete_custom_theme(self, theme_id):
        themes = [t for t in self.custom_themes() if t['id'] != theme_id]
        self._settings().setValue('Appearance/custom_themes',
                                  json.dumps(themes))
        if self.theme['id'] == theme_id:
            self.set_theme(DEFAULT_THEME)

    def all_themes(self):
        return list(PRESETS.values()) + [
            self.resolve_custom(t) for t in self.custom_themes()]

    @staticmethod
    def resolve_custom(theme):
        """A stored custom theme -> a full theme dict."""
        colors = derive(theme['base'], theme.get('tone'))
        colors.update(theme.get('overrides', {}))
        tone = theme.get('tone') or (
            'light' if luminance(colors['canvas']) > 0.4 else 'dark')
        return {'id': theme['id'], 'name': theme['name'], 'tone': tone,
                'colors': colors, 'custom': True, 'base': theme['base'],
                'overrides': theme.get('overrides', {})}

    def find(self, theme_id):
        for theme in self.all_themes():
            if theme['id'] == theme_id:
                return theme

    def load(self):
        if QtWidgets.QApplication.instance() is not None:
            load_custom_font()
        theme_id = self._settings().value('Appearance/theme', DEFAULT_THEME)
        self.set_theme(theme_id, save=False)

    def set_theme(self, theme_id, save=True):
        theme = self.find(theme_id) or PRESETS[DEFAULT_THEME]
        self.preview(theme)
        if save:
            self._settings().setValue('Appearance/theme', theme['id'])

    def preview(self, theme):
        """Apply a theme dict without saving it."""
        self.theme = theme
        self.apply()
        self.changed.emit()

    # -- applying --

    def color(self, name):
        return QtGui.QColor(self.theme['colors'][name])

    def hex(self, name):
        return self.theme['colors'][name]

    def apply(self):
        c = self.theme['colors']

        def rgb(name):
            q = QtGui.QColor(c[name])
            return (q.red(), q.green(), q.blue())

        # BeeRef reads these at paint time
        constants.COLORS.update({
            'Scene:Canvas': rgb('canvas'),
            'Scene:Selection': rgb('selection'),
            'Scene:Text': rgb('ink'),
            'Active:Base': rgb('surface-sunken'),
            'Active:AlternateBase': rgb('surface-raised'),
            'Active:Window': rgb('surface'),
            'Active:Button': rgb('surface-raised'),
            'Active:Text': rgb('ink'),
            'Active:HighlightedText': rgb('on-accent'),
            'Active:WindowText': rgb('ink'),
            'Active:ButtonText': rgb('ink'),
            'Active:Highlight': rgb('accent'),
            'Active:Link': rgb('accent'),
            'Disabled:Base': rgb('surface'),
            'Disabled:WindowText': rgb('ink-muted'),
            'Disabled:Text': rgb('ink-muted'),
        })
        from beeref import selection
        selection.SELECT_COLOR = QtGui.QColor(c['selection'])

        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        from beeref.utils import create_palette_from_dict
        palette = create_palette_from_dict(constants.COLORS)
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase,
                         QtGui.QColor(c['ink']))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipText,
                         QtGui.QColor(c['surface']))
        palette.setColor(QtGui.QPalette.ColorRole.PlaceholderText,
                         QtGui.QColor(c['ink-muted']))
        app.setPalette(palette)
        app.setFont(ui_font(12))
        app.setStyleSheet(stylesheet(c))


def tm():
    return ThemeManager.instance()


def stylesheet(c):
    """Qt stylesheet for standard widgets (dialogs, fields, buttons)."""
    r_sm, r_md, r_lg = px('radius-sm'), px('radius-md'), px('radius-lg')
    return f"""
QDialog, QMessageBox, QInputDialog, QProgressDialog {{
    background: {c['surface']}; color: {c['ink']};
}}
QWidget {{ color: {c['ink']}; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {c['ink']}; color: {c['surface']}; border: none;
    border-radius: 6px; padding: 4px 6px;
}}
QPushButton {{
    background: transparent; color: {c['ink']};
    border: 1px solid {c['control-border']}; border-radius: {r_sm}px;
    min-height: 26px; padding: 0 12px;
    font-family: "{font_spec('medium')[0]}";
}}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:default, QPushButton[primary="true"] {{
    background: {c['accent']}; color: {c['on-accent']};
    border-color: {c['accent']};
}}
QPushButton:default:hover, QPushButton[primary="true"]:hover {{
    background: {c['accent-strong']};
}}
QPushButton:disabled {{ color: {c['ink-muted']}; }}
QPushButton:focus {{ outline: none; border: 2px solid {c['focus-ring']}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {c['surface-sunken']}; color: {c['ink']};
    border: 1px solid {c['control-border']}; border-radius: {r_sm}px;
    min-height: 26px; padding: 0 8px;
    selection-background-color: {c['accent']};
    selection-color: {c['on-accent']};
}}
QPlainTextEdit, QTextEdit {{ padding: 6px 8px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {c['focus-ring']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {c['surface-raised']}; color: {c['ink']};
    border: 1px solid {c['divider']}; border-radius: {r_md}px;
    selection-background-color: {c['accent-soft']};
    selection-color: {c['ink']}; outline: none; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px; border: 1px solid {c['control-border']};
    background: {c['surface-sunken']};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']};
}}
QSlider::groove:horizontal {{
    height: 4px; background: {c['control-border']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {c['accent']}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['accent']}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QProgressBar {{
    background: {c['surface-sunken']}; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent; border: none; width: 8px; height: 8px;
}}
QScrollBar::handle {{
    background: {c['control-border']}; border-radius: 4px; min-height: 24px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page,
QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QTabWidget::pane {{
    border: 1px solid {c['divider']}; border-radius: {r_md}px;
}}
QTabBar::tab {{
    background: transparent; color: {c['ink-muted']}; padding: 6px 12px;
    border-radius: {r_sm}px;
}}
QTabBar::tab:selected {{ background: {c['accent-soft']}; color: {c['ink']}; }}
QListWidget, QTreeWidget, QTableWidget, QTableView {{
    background: {c['surface']}; color: {c['ink']};
    border: 1px solid {c['divider']}; border-radius: {r_md}px;
    alternate-background-color: {c['surface-raised']};
    selection-background-color: {c['accent-soft']};
    selection-color: {c['ink']}; outline: none;
}}
QHeaderView::section {{
    background: {c['surface']}; color: {c['ink-muted']}; border: none;
    border-bottom: 1px solid {c['divider']}; padding: 4px 8px;
}}
QGroupBox {{
    border: 1px solid {c['divider']}; border-radius: {r_md}px;
    margin-top: 16px; padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
    color: {c['ink-muted']};
}}
QMenuBar {{ background: {c['surface']}; color: {c['ink']}; }}
QMenuBar::item:selected {{ background: {c['hover']}; }}
QMenu {{
    background: {c['surface-raised']}; color: {c['ink']};
    border: 1px solid {c['divider']}; padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 24px; border-radius: {r_sm}px; }}
QMenu::item:selected {{ background: {c['hover']}; }}
QMenu::separator {{
    height: 1px; background: {c['divider']}; margin: 4px 8px;
}}
#BeeNotification {{
    background: {c['surface-raised']}; color: {c['ink']};
    border-radius: {r_lg}px;
}}
"""
