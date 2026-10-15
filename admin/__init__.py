from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

from admin.dashboard import *
from admin.users import *
from admin.datasets import *
from admin.imagery import *
from admin.hdfs import *
from admin.mapreduce import *
from admin.machine_learning import *
from admin.reports import *
from admin.alerts import *
from admin.feedback import *
from admin.settings import *
from admin.profile import *
from admin.realtime import *
from admin.analytics import *
