"""Check local documentation links, heading fragments and portable image embeds."""

import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FENCES = re.compile(r'^```[^\n]*\n.*?^```[ \t]*$', re.M | re.S)
LINKS = re.compile(r'(!?)\[([^\]]*)\]\((<[^>]+>|[^)]+)\)')
HTML_LINKS = re.compile(r'<(img|a)\b[^>]*?\b(?:src|href)=["\']([^"\']+)["\']', re.I)


def documents():
    files = [
        ROOT / name
        for name in [
            'README.md',
            'backend/README.md',
            'frontend/README.md',
            'scripts/README.md',
            'resources/README.md',
        ]
    ]
    for directory in ['docs', 'config', 'resources/demo', 'resources/images', 'backend/app/agent']:
        files.extend((ROOT / directory).rglob('*.md'))
    return sorted(set(file for file in files if file.is_file()))


def without_code(text):
    return FENCES.sub(lambda m: '\n' * m.group().count('\n'), text)


def heading_ids(text):
    found, counts = set(), {}
    for match in re.finditer(r'^#{1,6}\s+(.+?)\s*#*\s*$', without_code(text), re.M):
        label = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', match[1])
        label = re.sub(r'<[^>]+>|[*`~]', '', label).lower().strip()
        slug = ''.join(c for c in label if c in '-_ ' or unicodedata.category(c)[0] in 'LNM').replace(
            ' ', '-'
        )
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug + (f'-{count}' if count else ''))
    found.update(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', text))
    return found


def references(text):
    for match in LINKS.finditer(text):
        target = match[3]
        target = target[1 : target.index('>')] if target.startswith('<') else target.split(' "', 1)[0]
        yield match.start(), bool(match[1]), target
    for match in HTML_LINKS.finditer(text):
        yield match.start(), match[1].lower() == 'img', match[2]
    definitions = dict(re.findall(r'^\s*\[([^\]]+)\]:\s*<?([^\s>]+)>?', text, re.M))
    for match in re.finditer(r'(!?)\[([^\]]+)\]\[([^\]]*)\]', text):
        yield match.start(), bool(match[1]), definitions.get(match[3] or match[2], '')


def check():
    errors, images, links = [], set(), 0
    image_dir = ROOT / 'resources/images'
    image_extensions = {'.png', '.svg', '.jpg', '.jpeg', '.webp', '.gif'}
    used_assets = set()
    files = documents()
    for file in files:
        original = file.read_text()
        text = without_code(original)
        for offset, image, target in references(text):
            line = text[:offset].count('\n') + 1
            label = f'{file.relative_to(ROOT)}:{line}'
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            destination = (file.parent / unquote(parsed.path)).resolve() if parsed.path else file
            links += 1
            if not target or not destination.exists():
                errors.append(f'{label}: missing target {target!r}')
                continue
            if destination.is_relative_to(ROOT):
                relative = destination.relative_to(ROOT)
                parent = ROOT
                for part in relative.parts:
                    if part not in {entry.name for entry in parent.iterdir()}:
                        errors.append(f'{label}: target spelling or case does not match {target!r}')
                        break
                    parent /= part
            if destination.is_relative_to(image_dir) and destination.suffix.lower() in image_extensions:
                used_assets.add(destination)
            if image:
                images.add(destination)
                if destination.suffix.lower() in {'.svg', '.mmd'}:
                    errors.append(f'{label}: embed a PNG preview instead of {destination.name}')
            if parsed.fragment and destination.suffix.lower() == '.md':
                fragment = unquote(parsed.fragment)
                if fragment not in heading_ids(destination.read_text()):
                    errors.append(f'{label}: missing heading #{fragment} in {destination.relative_to(ROOT)}')
        if re.search(r'^```mermaid\s*$', original, re.M):
            errors.append(
                f'{file.relative_to(ROOT)}: embed a rendered PNG and link its editable Mermaid source'
            )
    for directory in [ROOT / 'docs', image_dir]:
        for path in sorted(directory.rglob('*')):
            if path.name == '.DS_Store' or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.name != 'README.md' and not re.fullmatch(r'[a-z0-9_]+(?:\.[a-z0-9_]+)*', path.name):
                errors.append(f'{path.relative_to(ROOT)}: use lowercase snake_case names')
    for asset in sorted(image_dir.rglob('*')):
        if asset.is_file() and asset.suffix.lower() in image_extensions and asset not in used_assets:
            errors.append(f'{asset.relative_to(ROOT)}: unused documentation image; reference it or remove it')
    if errors:
        print('\n'.join(errors))
        return 1
    print(
        f'Checked {len(files)} Markdown files, {links} local references, {len(images)} embedded images '
        f'and {len(used_assets)} referenced documentation assets. All passed.'
    )
    print('External URLs are not fetched.')
    return 0


if __name__ == '__main__':
    sys.exit(check())
