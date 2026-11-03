"""
Finds out why the Paytm QR picture is not showing.

Run it from your project folder (the one that contains manage.py):

    python check_paytm.py

It only READS your files, it never changes anything.
"""
import os
import re
import sys

ROOT = os.getcwd()
SKIP = {'.venv', 'venv', 'env', 'node_modules', '.git', '__pycache__'}
OK, BAD, WARN = 'OK   ', 'FIX  ', 'NOTE '


def say(tag, text):
    print(f'  [{tag}] {text}')


def kind(path):
    """What the file really is, judged by its first bytes (catches a PDF or text renamed to .png)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
    except OSError:
        return 'unreadable'
    if head.startswith(b'\x89PNG'):
        return 'png'
    if head.startswith(b'\xff\xd8'):
        return 'jpeg'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head.startswith(b'%PDF'):
        return 'pdf'
    return 'not an image'


print('\nChecking the Paytm QR picture in:', ROOT, '\n')
if not os.path.exists(os.path.join(ROOT, 'manage.py')):
    say(BAD, 'manage.py is not in this folder. Open the terminal in the main project folder and run this again.')
    sys.exit(1)

# 1. every file with "paytm" in its name
found = []
for folder, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for name in files:
        if 'paytm' in name.lower():
            found.append(os.path.join(folder, name))

static_dir = os.path.join(ROOT, 'store', 'static')
print('1. Files with "paytm" in the name:')
if not found:
    say(BAD, 'No such file anywhere in the project. Copy your QR picture into store/static/ and name it paytm.png')
for path in found:
    rel = os.path.relpath(path, ROOT)
    say('     ', f'{rel}   (really a: {kind(path)}, {os.path.getsize(path)} bytes)')

# 2. the exact name the website looks for
print('\n2. The exact file name the website looks for:')
wanted = [n for n in ('paytm.png', 'paytm.jpg', 'paytm.jpeg', 'paytm.webp') if os.path.exists(os.path.join(static_dir, n))]
if wanted:
    for n in wanted:
        k = kind(os.path.join(static_dir, n))
        say(OK if k != 'not an image' and k != 'pdf' else BAD, f'store/static/{n} exists and is really a: {k}')
else:
    close = [os.path.basename(p) for p in found if os.path.dirname(p) == static_dir]
    if close:
        say(BAD, f'store/static has {close!r} but the website needs exactly:  paytm.png  (small letters, ONE dot, no spaces, no "(1)")')
        say(BAD, 'Rename it in VS Code: click the file, press F2, type paytm.png, press Enter.')
    else:
        say(BAD, 'store/static/paytm.png does not exist. Put your QR picture there.')
    wrong = [p for p in found if os.path.dirname(p) != static_dir and os.path.splitext(p)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp')]
    for p in wrong:
        say(WARN, f'{os.path.relpath(p, ROOT)} is in the wrong folder. It must be directly inside store/static/')

# 3. collected static files (what the live site serves)
print('\n3. Live site (Vercel) - collected static files:')
collected = os.path.join(ROOT, 'staticfiles')
if os.path.isdir(collected):
    have = [n for n in ('paytm.png', 'paytm.jpg', 'paytm.jpeg', 'paytm.webp') if os.path.exists(os.path.join(collected, n))]
    if have:
        say(OK, f'staticfiles/{have[0]} exists')
    else:
        say(BAD, 'staticfiles/ has no paytm file. Run:  python manage.py collectstatic --noinput   then deploy again.')
else:
    say(WARN, 'No staticfiles/ folder here. That is normal on your own computer. The live site builds it when it deploys.')
    say(WARN, 'If the QR works here but not on the live site, run  python manage.py collectstatic --noinput  and deploy again.')

# 4. is the file hidden from git / deploys?
print('\n4. Is it being left out when you deploy?')
ignore = os.path.join(ROOT, '.gitignore')
bad_lines = []
if os.path.exists(ignore):
    for line in open(ignore, encoding='utf-8', errors='ignore'):
        s = line.strip()
        if s and not s.startswith('#') and re.search(r'(^|/)(\*\.(png|jpg|jpeg|webp)|store/static/?|static/?|paytm\S*)$', s):
            bad_lines.append(s)
if bad_lines:
    say(BAD, f'.gitignore contains {bad_lines!r}: that stops the picture from being uploaded. Remove those lines, then commit and push.')
else:
    say(OK, '.gitignore does not block the picture.')

print('\n5. Admin upload: in the admin, Payment settings > "Paytm QR code image". If one is saved there it is shown FIRST;')
print('   if that picture is broken the website now falls back to store/static/paytm.png automatically.')
print('\nDone. Fix anything marked FIX, then refresh the payment page with Ctrl + F5.\n')
