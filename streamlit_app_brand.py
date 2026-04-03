import os

os.environ.setdefault("SMES_REPORTING_PAGE_TITLE", "Supporto PMI Online")
os.environ.setdefault("SMES_REPORTING_DISPLAY_TITLE", "🌐 Supporto PMI Online")
os.environ.setdefault("SMES_REPORTING_DATA_DIR", "/tmp/smes-reporting-online")

from app_smes_reporting_support import *  # noqa: F401,F403