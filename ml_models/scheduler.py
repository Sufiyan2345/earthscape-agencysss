"""Optional process-local scheduler for periodic model refreshes."""

import threading

_started = False
_lock = threading.Lock()


def start_scheduler(app):
    """Schedule weekly retraining once per application process."""
    global _started
    if not app.config.get('ENABLE_MODEL_SCHEDULER') or app.testing:
        return
    if app.debug and __import__('os').environ.get('WERKZEUG_RUN_MAIN') not in ('true', None):
        return
    with _lock:
        if _started:
            return
        _started = True

    interval = max(1.0, app.config.get('MODEL_RETRAIN_INTERVAL_HOURS', 168)) * 3600

    def run():
        try:
            with app.app_context():
                from ml_models.train_model import train_all_models
                train_all_models(user_id=0)
                from utils.model_cache import invalidate_models
                invalidate_models()
        except Exception:
            app.logger.exception('Scheduled model retraining failed')
        finally:
            timer = threading.Timer(interval, run)
            timer.daemon = True
            timer.start()

    timer = threading.Timer(interval, run)
    timer.daemon = True
    timer.start()