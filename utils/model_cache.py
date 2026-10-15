"""
Model caching layer.

ML model objects (ClimatePredictor, AnomalyDetector) load pickled models
from disk in their constructors.  Constructing them on every request is
wasteful because the model files rarely change.  This module provides
process-wide singleton caches keyed by model class and TTL.
"""
from utils.helper import get_cached_value


def get_climate_predictor(ttl_seconds=300):
    """Return a cached ClimatePredictor singleton (5 min TTL)."""
    from ml_models.climate_prediction import ClimatePredictor
    return get_cached_value(
        'ml:climate_predictor',
        ClimatePredictor,
        ttl_seconds=ttl_seconds,
    )


def get_anomaly_detector(ttl_seconds=300):
    """Return a cached AnomalyDetector singleton (5 min TTL)."""
    from ml_models.anomaly_detection import AnomalyDetector
    return get_cached_value(
        'ml:anomaly_detector',
        AnomalyDetector,
        ttl_seconds=ttl_seconds,
    )


def get_correlation_analyzer():
    """CorrelationAnalyzer has no constructor cost (no disk I/O), so it is
    cheap to instantiate per-call.  Still cached for consistency."""
    from ml_models.correlation_analysis import CorrelationAnalyzer
    return get_cached_value(
        'ml:correlation_analyzer',
        CorrelationAnalyzer,
        ttl_seconds=300,
    )


def get_preprocessor():
    """ClimatePreprocessor has no constructor cost either, but caching
    avoids unnecessary allocations."""
    from ml_models.preprocessing import ClimatePreprocessor
    return get_cached_value(
        'ml:preprocessor',
        ClimatePreprocessor,
        ttl_seconds=300,
    )


def invalidate_models():
    """Clear all cached ML models (useful after retrain)."""
    from utils.helper import _CACHE
    for key in list(_CACHE.keys()):
        if key.startswith('ml:'):
            del _CACHE[key]
