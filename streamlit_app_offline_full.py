import os

APP_DIR = os.path.dirname(__file__)

os.environ.setdefault("SMES_REPORTING_PAGE_TITLE", "Supporto PMI Offline Completo")
os.environ.setdefault("SMES_REPORTING_DISPLAY_TITLE", "💻 Supporto PMI Offline Completo")
os.environ.setdefault("SMES_REPORTING_OFFLINE_MODE", "1")
os.environ.setdefault("SMES_REPORTING_DATA_DIR", os.path.join(APP_DIR, ".offline_full_data"))

from app_smes_reporting_support import *  # noqa: F401,F403
