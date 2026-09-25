import pytest

from sportsbet.quant.baseline_reconstruction import baseline_evidence

ESTIMATE={'sample':30,'base':.6,'mean':7.125}
PAYLOAD={'direction':'over','model_sample_size':30,'model_probability':.6,
         'model_mean_stat':7.13,'push_probability':0}


def test_complete_and_legacy_missing_mean_are_distinct_and_never_promote():
    original=dict(PAYLOAD)
    assert baseline_evidence(PAYLOAD,ESTIMATE)['status']=='complete_agreement'
    for payload in ({k:v for k,v in PAYLOAD.items() if k!='model_mean_stat'},PAYLOAD|{'model_mean_stat':None}):
        result=baseline_evidence(payload,ESTIMATE)
        assert result['status']=='partial_agreement_missing_mean'
        assert result['missing_fields']==['model_mean_stat']
        assert result['prospective_eligible'] is False
    assert PAYLOAD==original


def test_absence_does_not_hide_conflicting_probabilities_or_sample():
    result=baseline_evidence(PAYLOAD|{'model_mean_stat':None,'model_probability':.7,'model_sample_size':31},ESTIMATE)
    assert result['status']=='conflict'
    assert set(result['conflicting_fields'])=={'model_probability','model_sample_size'}
    assert result['missing_fields']==['model_mean_stat']


@pytest.mark.parametrize('field', ['model_sample_size','model_probability','push_probability'])
def test_missing_required_evidence_remains_insufficient(field):
    assert baseline_evidence(PAYLOAD|{field:None},ESTIMATE)['status']=='insufficient_metadata'


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,'not-a-number'])
def test_invalid_evidence_is_never_partial_agreement(value):
    result=baseline_evidence(PAYLOAD|{'model_mean_stat':value},ESTIMATE)
    assert result['status']=='conflict'
    assert result['invalid_fields']==['model_mean_stat']


def test_under_direction_rounding_and_actual_mean_conflict():
    assert baseline_evidence(PAYLOAD|{'direction':'under','model_probability':.4},ESTIMATE)['status']=='complete_agreement'
    result=baseline_evidence(PAYLOAD|{'model_mean_stat':7.14},ESTIMATE)
    assert result['conflicting_fields']==['model_mean_stat']
    assert baseline_evidence(PAYLOAD|{'model_probability':.6000004},ESTIMATE)['status']=='complete_agreement'
    assert baseline_evidence(PAYLOAD|{'push_probability':.01},ESTIMATE)['status']=='conflict'


def test_invalid_reconstruction_or_direction_fails_explicitly():
    with pytest.raises(ValueError):baseline_evidence(PAYLOAD|{'direction':'sideways'},ESTIMATE)
    with pytest.raises(ValueError):baseline_evidence(PAYLOAD,ESTIMATE|{'sample':19})
