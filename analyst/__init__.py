from flask import Blueprint

analyst_bp = Blueprint('analyst', __name__, url_prefix='/analyst')

from analyst.dashboard import *
from analyst.climate_data import *
from analyst.upload_dataset import *
from analyst.ingestion import *
from analyst.imagery import *
from analyst.hdfs import *
from analyst.mapreduce import *
from analyst.machine_learning import *
from analyst.realtime import *
from analyst.reports import *
from analyst.visualization import *
from analyst.alerts import *
from analyst.feedback import *
from analyst.profile import *
from analyst.analytics import *
