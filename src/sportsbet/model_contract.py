"""Shared identity for the model evaluated by scans and published metrics."""

MODEL_VERSION = 'empirical-jeffreys-v4'

# These scanner cohorts were introduced after quote source and normalized-row
# commitments became mandatory. Advancing MODEL_VERSION must not make their
# historical records exempt from provenance validation.
QUOTE_PROVENANCE_MODEL_VERSIONS = frozenset({
    'empirical-v2',
    'empirical-jeffreys-v3',
    'empirical-jeffreys-v4',
})
