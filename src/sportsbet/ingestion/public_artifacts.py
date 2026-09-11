"""Stage only public JSON evidence, rejecting configured credentials before upload."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote, urlsplit


DIRECTORIES = ('market-watch', 'prizepicks', 'nba-refresh')
CREDENTIALS = ('DATABASE_URL', 'DATABASE_URL_ASYNC', 'ANALYTICS_DATABASE_URL', 'ODDS_API_KEY')


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)


def stage(root: Path, output: Path, credentials: list[str]) -> int:
    needles = set()
    for credential in filter(None, credentials):
        values = [credential]
        if '://' in credential:
            password = urlsplit(credential).password
            if password:
                values.append(unquote(password))
        for value in values:
            needles.update((value, quote(value, safe=''), quote_plus(value, safe='')))
    output.mkdir(parents=True, exist_ok=False)
    count = 0
    if root.is_symlink() or root.is_junction():
        raise ValueError('Evidence links are forbidden')
    for directory in DIRECTORIES:
        source = root / directory
        if source.is_symlink() or source.is_junction():
            raise ValueError('Evidence links are forbidden')
        for path in sorted(source.glob('*.json')):
            if path.is_symlink() or path.is_junction() or not path.is_file():
                raise ValueError('Evidence links are forbidden')
            data = path.read_bytes()
            text = data.decode('utf-8')
            # Decode JSON strings too: escaped characters must not hide credentials.
            # Preserve duplicate keys so overwritten JSON values are checked too.
            for value in (text, path.name, *strings(json.loads(text, object_pairs_hook=list))):
                if any(secret in value for secret in needles):
                    raise ValueError('Configured credential found; public evidence upload blocked')
            destination = output / directory / path.name
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(data)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        count = stage(Path('.local'), args.output, [os.environ.get(name, '') for name in CREDENTIALS])
    except Exception as exc:
        # Never print parser errors, filenames, URLs or matched values from evidence.
        raise SystemExit(f'Public evidence verification failed ({type(exc).__name__}); upload blocked') from None
    print(f'Prepared {count} public evidence files for the secret scanner')


if __name__ == '__main__':
    main()
