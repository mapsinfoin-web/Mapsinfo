"""
Removes the Jazzmin admin theme from a Django project, so the normal Django admin is used.

Usage (from your project folder, the one that contains manage.py):
    python remove_jazzmin.py

What it does
  * removes "jazzmin" from INSTALLED_APPS
  * removes every JAZZMIN_* setting (JAZZMIN_SETTINGS, JAZZMIN_UI_TWEAKS, ...)
  * removes django-jazzmin from requirements*.txt
  * saves a backup next to each file it changes (settings.py.bak)
Then run:  pip uninstall django-jazzmin
"""
import ast
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
SKIP = {'.venv', 'venv', 'env', 'site-packages', 'node_modules', '.git', 'staticfiles'}


def project_files(pattern):
    return [p for p in ROOT.rglob(pattern) if not (set(p.parts) & SKIP)]


def clean_settings(path):
    src = path.read_text(encoding='utf-8')
    if 'jazzmin' not in src.lower():
        return False
    lines = src.splitlines(keepends=True)
    drop = set()

    for node in ast.parse(src).body:
        names = []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]

        if any(n.upper().startswith('JAZZMIN') for n in names):
            drop.update(range(node.lineno - 1, node.end_lineno))

        if 'INSTALLED_APPS' in names and isinstance(node.value, (ast.List, ast.Tuple)):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and elt.value == 'jazzmin':
                    i = elt.lineno - 1
                    if re.fullmatch(r"\s*['\"]jazzmin['\"]\s*,?\s*(#.*)?", lines[i].rstrip('\r\n')):
                        drop.add(i)                      # the app has its own line
                    else:                                # list written on one line
                        lines[i] = re.sub(r"['\"]jazzmin['\"]\s*,?\s*", '', lines[i], count=1)

    new_src = ''.join(l for i, l in enumerate(lines) if i not in drop)
    ast.parse(new_src)                                   # never write a broken settings file
    shutil.copy(path, str(path) + '.bak')
    path.write_text(new_src, encoding='utf-8')
    return True


def clean_requirements(path):
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines(keepends=True)
    kept = [l for l in lines if not re.match(r'\s*django[-_]jazzmin\b', l, re.I)]
    if len(kept) == len(lines):
        return False
    shutil.copy(path, str(path) + '.bak')
    path.write_text(''.join(kept), encoding='utf-8')
    return True


changed = False
for f in project_files('settings.py') + project_files('settings/*.py'):
    if clean_settings(f):
        print(f"cleaned   {f}  (backup: {f.name}.bak)")
        changed = True
for f in project_files('requirements*.txt'):
    if clean_requirements(f):
        print(f"cleaned   {f}  (backup: {f.name}.bak)")
        changed = True

left = []
for ext in ('*.py', '*.html', '*.txt', '*.toml', '*.cfg'):
    for f in project_files(ext):
        if f.name == 'remove_jazzmin.py' or f.suffix == '.bak':
            continue
        try:
            if 'jazzmin' in f.read_text(encoding='utf-8', errors='ignore').lower():
                left.append(f)
        except OSError:
            pass

print()
print("Done." if changed else "Nothing to change - no Jazzmin found in settings.")
if left:
    print("These files still mention 'jazzmin' - check them by hand:")
    for f in left:
        print("   ", f)
print("Last step:  pip uninstall django-jazzmin")
y