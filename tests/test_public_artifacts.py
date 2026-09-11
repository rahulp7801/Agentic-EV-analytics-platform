import json
import os
import subprocess
import sys
from urllib.parse import quote

import pytest

from sportsbet.ingestion.public_artifacts import stage


def test_public_artifacts_preserve_evidence_and_exclude_private_directories(tmp_path):
    root = tmp_path / 'source'
    public = root / 'market-watch'
    public.mkdir(parents=True)
    data = b'{"source":"kalshi","price":"0.54"}'
    (public / 'capture.json').write_bytes(data)
    private = root / 'secrets'
    private.mkdir()
    (private / 'credentials.json').write_text('{"password":"private"}')
    output = tmp_path / 'staged'
    assert stage(root, output, ['private']) == 1
    assert (output / 'market-watch/capture.json').read_bytes() == data
    assert not (output / 'secrets').exists()
    with pytest.raises(FileExistsError):
        stage(root, output, [])


@pytest.mark.parametrize('encoding', ['plain', 'url', 'json_escaped', 'key'])
def test_public_artifacts_block_passwords_in_provider_responses(tmp_path, encoding):
    password = 'fixture-only-päss/word!'
    root = tmp_path / 'source'
    source = root / 'nba-refresh'
    source.mkdir(parents=True)
    value = quote(password, safe='') if encoding == 'url' else password
    payload = {value: 'error'} if encoding == 'key' else {'error': 'provider echoed ' + value}
    (source / 'capture.json').write_text(json.dumps(payload, ensure_ascii=encoding == 'json_escaped'), encoding='utf-8')
    credential = 'postgresql://worker:' + quote(password, safe='') + '@example.invalid/db'
    with pytest.raises(ValueError, match='public evidence upload blocked') as error:
        stage(root, tmp_path / 'staged', [credential])
    assert password not in str(error.value)


def test_public_artifacts_reject_invalid_json(tmp_path):
    root = tmp_path / 'source'
    source = root / 'prizepicks'
    source.mkdir(parents=True)
    (source / 'capture.json').write_text('invalid response')
    with pytest.raises(ValueError):
        stage(root, tmp_path / 'staged', [])


def test_public_artifacts_cli_blocks_escaped_duplicate_values_without_logging_secrets(tmp_path):
    source = tmp_path / '.local/market-watch'
    source.mkdir(parents=True)
    credential = 'fixture-only-publication-credential'
    escaped = ''.join('\\u' + format(ord(character), '04x') for character in credential)
    (source / 'capture.json').write_text('{"error":"' + escaped + '","error":"fine"}')
    result = subprocess.run([sys.executable, '-m', 'sportsbet.ingestion.public_artifacts',
        '--output', str(tmp_path / 'staged')], cwd=tmp_path,
        env={**os.environ, 'ODDS_API_KEY': credential}, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'upload blocked' in result.stderr
    assert credential not in result.stderr + result.stdout
    assert escaped not in result.stderr + result.stdout
