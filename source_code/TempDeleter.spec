# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_all
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

# Collect delete_func_scripts (datas/binaries/hiddenimports)
tmp_ret = collect_all('delete_func_scripts')  # (datas, binaries, hiddenimports)

# Datas & Binaries
datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('data', 'data'),
]
# add collected datas from delete_func_scripts
datas += tmp_ret[0]
binaries = tmp_ret[1]

# Hidden imports
hiddenimports = [
    # tray / notification
    'pystray',
    'pystray._win32',
    'pystray._base',
    'win10toast',

    # web / gui
    'webview',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',

    # Pillow
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFile',

    # Flask & templating
    'flask',
    'flask_cors',
    'jinja2',
    'werkzeug',
    'click',
    'blinker',
    'itsdangerous',
    'markupsafe',

    # timezone helpers (if kullanıyorsan)
    'tzlocal',
    'pytz',
]

# add any submodules from delete_func_scripts
hiddenimports += collect_submodules('delete_func_scripts')
# also add any hiddenimports collect_all returned
hiddenimports += tmp_ret[2]

# Excludes (bloat / irrelevant libs)
excludes = [
    'matplotlib', 'numpy', 'scipy', 'pandas', 'tkinter',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
    'IPython', 'jupyter', 'test', 'tests', 'unittest'
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TempDeleter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon='static\\icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TempDeleter',
)
