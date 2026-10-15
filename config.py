import os

basedir = os.path.abspath(os.path.dirname(__file__))
runtime_dir = os.environ.get('EARTHSCAPE_RUNTIME_DIR') or (
    '/tmp/earthscape-climate' if os.environ.get('VERCEL') else basedir
)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-this-secret')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get(
        'SESSION_COOKIE_SECURE',
        'true' if os.environ.get('VERCEL') else 'false',
    ).lower() == 'true'

    UPLOAD_FOLDER = os.path.join(runtime_dir, 'uploads')
    DATASETS_FOLDER = os.path.join(runtime_dir, 'datasets')
    REPORTS_FOLDER = os.path.join(runtime_dir, 'reports')
    LOGS_FOLDER = os.path.join(runtime_dir, 'logs')
    MODELS_FOLDER = os.path.join(basedir, 'ml_models', 'saved_models')
    MODEL_RETRAIN_INTERVAL_HOURS = float(os.environ.get('MODEL_RETRAIN_INTERVAL_HOURS', '168'))
    ENABLE_MODEL_SCHEDULER = os.environ.get(
        'ENABLE_MODEL_SCHEDULER',
        'false' if os.environ.get('VERCEL') else 'true',
    ).lower() == 'true'

    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max upload

    HDFS_NAMENODE = os.environ.get('HDFS_NAMENODE', 'http://localhost:9870')
    HDFS_BASE_PATH = '/climate'
    HDFS_USER = os.environ.get('HDFS_USER', 'climateservice')
    HDFS_USE_REAL = os.environ.get('HDFS_USE_REAL', 'false').lower() == 'true'
    MAPREDUCE_AUTO_THRESHOLD = int(os.environ.get('MAPREDUCE_AUTO_THRESHOLD', '5000'))
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', '')
    KAFKA_CLIMATE_TOPIC = os.environ.get('KAFKA_CLIMATE_TOPIC', 'earthscape.climate.readings')
    KAFKA_CONSUMER_GROUP = os.environ.get('KAFKA_CONSUMER_GROUP', 'earthscape-climate')

    # MongoDB configuration (primary and only datastore)
    # Uses MongoDB Atlas. If unavailable, the app falls back to in-memory data
    # via mongomock to keep the application running without crashing.
    MONGO_URI = os.environ.get(
        'MONGO_URI',
        '' if os.environ.get('VERCEL') else 'mongodb://localhost:27017/earthscapeagency',
    )
    MONGO_DB = "earthscapeagency"

    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls', 'json', 'txt', 'tif', 'tiff', 'nc', 'hdf5', 'h5'}

    ALERT_THRESHOLDS = {
        'temperature_max': 45.0,
        'temperature_min': -30.0,
        'rainfall_max': 200.0,
        'humidity_max': 95.0,
        'wind_speed_max': 120.0,
        'air_quality_max': 300.0,
        'co2_max': 500.0,
    }

    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', 'admin@climate.gov')


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    DEBUG = True
    TESTING = True


config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}
