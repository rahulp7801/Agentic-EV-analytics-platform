import json
import sys

import pytest

from sportsbet.quant.audit_storage import ReadOnlyLedger,audit_database_url
from sportsbet.quant import priced_market_audit as audit


@pytest.fixture(autouse=True)
def clear_audit_urls(monkeypatch):
    for name in ('ANALYTICS_DATABASE_URL','DATABASE_URL','AUDIT_CUSTOM_URL'):
        monkeypatch.delenv(name,raising=False)


def test_source_selection_prefers_analytics_and_respects_explicit_environment(monkeypatch):
    primary='postgresql://primary.invalid/db'
    analytics='postgresql://analytics.invalid/db'
    monkeypatch.setenv('DATABASE_URL',primary)
    assert audit_database_url()==primary
    monkeypatch.setenv('ANALYTICS_DATABASE_URL',analytics)
    assert audit_database_url()==analytics
    assert audit_database_url('DATABASE_URL')==primary
    with pytest.raises(ValueError):audit_database_url('AUDIT_CUSTOM_URL')
    monkeypatch.setenv('AUDIT_CUSTOM_URL',primary)
    assert audit_database_url('AUDIT_CUSTOM_URL')==primary


@pytest.mark.parametrize('value',['','  ','sqlite:///local.sqlite','file:local.sqlite'])
def test_invalid_audit_source_never_creates_local_files(value,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ANALYTICS_DATABASE_URL',value)
    with pytest.raises(ValueError):audit_database_url()
    with pytest.raises(ValueError):ReadOnlyLedger(database_url=value)
    assert not list(tmp_path.iterdir())


def test_priced_cli_missing_source_fails_without_creating_or_reading_local_ledger(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys,'argv',['audit','--sport','nfl'])
    with pytest.raises(SystemExit,match='Priced audit unavailable'):
        audit.main()
    assert not list(tmp_path.iterdir())
    assert capsys.readouterr().out==''


def test_priced_cli_explicit_missing_source_does_not_use_default(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL','postgresql://unused.invalid/db')
    monkeypatch.setattr(sys,'argv',['audit','--database-env','AUDIT_CUSTOM_URL'])
    with pytest.raises(SystemExit,match='ValueError'):audit.main()
    assert not list(tmp_path.iterdir())


def test_priced_cli_uses_snapshot_and_does_not_print_connection_errors(monkeypatch,capsys):
    from contextlib import contextmanager
    secret_url='postgresql://user:secret@example.invalid/db'
    monkeypatch.setenv('DATABASE_URL',secret_url)
    monkeypatch.setattr(sys,'argv',['audit','--sport','nfl'])
    class FakeLedger:
        active=False
        def __init__(self,*,database_url):assert database_url==secret_url
        @contextmanager
        def snapshot(self):
            self.active=True
            try:yield self
            finally:self.active=False
    def inspect(ledger,**kwargs):
        assert ledger.active
        return {'source':'hosted','sport':kwargs['sport']}
    monkeypatch.setattr(audit,'ReadOnlyLedger',FakeLedger)
    monkeypatch.setattr(audit,'audit_ledger',inspect)
    audit.main()
    assert json.loads(capsys.readouterr().out)=={'source':'hosted','sport':'nfl'}
    def fail(*args,**kwargs):raise RuntimeError(secret_url)
    monkeypatch.setattr(audit,'audit_ledger',fail)
    with pytest.raises(SystemExit) as error:audit.main()
    assert str(error.value)=='Priced audit unavailable: RuntimeError'
    assert capsys.readouterr().out==''
