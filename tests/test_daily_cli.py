import json
import sys

from sportsbet import daily


def test_daily_cli_writes_a_clean_machine_readable_report(monkeypatch,tmp_path,capsys):
    report={'status':'observed','mode':'public_daily','execution_ready':False}

    async def run(*args):
        print('collector progress that must not enter the report file')
        return report

    output=tmp_path/'nested'/'report.json'
    monkeypatch.setattr(daily,'run',run)
    monkeypatch.setattr(sys,'argv',['daily','--mode','public_daily','--report-output',str(output)])
    daily.main()

    assert json.loads(output.read_text(encoding='utf-8'))==report
    assert 'collector progress' in capsys.readouterr().out
    assert not output.with_name('report.json.tmp').exists()


def test_daily_cli_all_includes_cfb_only_for_paid_modes(monkeypatch):
    captured=[]
    async def run(*args):
        captured.append(args)
        return {'status':'complete'}
    monkeypatch.setattr(daily,'run',run)
    monkeypatch.setattr(sys,'argv',['daily','--sport','all','--mode','daily'])
    daily.main()
    assert captured==[(['nfl','nba','cfb'],'daily',25)]
