from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

from auth.login import *
from auth.register import *
from auth.logout import *
