# -*- coding: utf-8 -*-
"""Render the two cert HTML files to PNG demos used on eco-depot.html."""
import os, subprocess, time, shutil, tempfile

WEB = r'C:/Users/lio2e/Documents/AI_DEV/eco_oil_platform/website'
OUT_DIR = f'{WEB}/images/Industrial Tank Cleaning Facility'
CHROME = r'C:/Program Files/Google/Chrome/Application/chrome.exe'

CERTS = [
    ('cleaning_certificate.html', 'cleaning_certificate_demo.png'),
    ('release_certificate.html',  'release_certificate_demo.png'),
]


def make_temp(src_html):
    """Inline-hide the toolbar so screenshot is print-clean."""
    with open(src_html, 'r', encoding='utf-8') as f:
        content = f.read()
    inject = '<style>.toolbar,.no-print{display:none!important;}body{background:#fff!important;}.sheet{box-shadow:none!important;margin:0!important;}</style>'
    content = content.replace('</head>', inject + '</head>', 1)
    fd, tmp = tempfile.mkstemp(suffix='.html', dir=WEB)
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    return tmp


def render(src_html, out_png):
    src_path = f'{WEB}/{src_html}'
    out_path = f'{OUT_DIR}/{out_png}'
    tmp = make_temp(src_path)
    try:
        # window 820 wide ~ 210mm at 100dpi, 1180 tall ~ A4 portrait
        url = 'file:///' + tmp.replace('\\', '/')
        cmd = [
            CHROME,
            '--headless=new',
            '--disable-gpu',
            '--no-sandbox',
            '--hide-scrollbars',
            '--default-background-color=ffffff',
            f'--screenshot={out_path}',
            '--window-size=820,1180',
            '--virtual-time-budget=3000',
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print('STDOUT:', result.stdout)
            print('STDERR:', result.stderr)
            return False
        return os.path.exists(out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


for src, out in CERTS:
    print(f'Rendering {src} -> {out}...')
    ok = render(src, out)
    print('  OK' if ok else '  FAILED')
