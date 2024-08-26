import logging
from functools import partial
from pathlib import Path
import os 

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bubt_cnr.constants import (
    BUBT_BASE_URL,
    BUBT_CALENDAR_URL,
    BUBT_NOTICE_URL,
    BUBT_ROUTINE_URL,
    CALENDER_DIR,
    DATA_DIR,
    DB_NAME,
    EXAM_DIR,
    NOTICE_DIR,
    SUPP_EXAM_DIR,
    TEST_DATA_DIR,
)
from bubt_cnr.db_handler import DbManager
from bubt_cnr.log_tags import LOG_TAGS

logging.basicConfig(
    format="%(asctime)s - %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("bubt_cnr.log"), logging.StreamHandler()],
    level=logging.INFO,
)

LOGGER = logging.getLogger(__name__)

LOG_TAG = LOG_TAGS.APP

if os.getenv('CNR_DEBUG') == "true":
    LOGGER.info("[%s] running in DEBUG mode", LOG_TAG)
    data_dir = Path.cwd() / EXAM_DIR
else:
    LOGGER.info("[%s] running in RELEASE mode", LOG_TAG)
    data_dir = Path.cwd() / DATA_DIR

NOTICE_API_URL = os.getenv("BUBT_NOTICE_API_URL")

notice_dir = data_dir / NOTICE_DIR
calendar_dir = data_dir / CALENDER_DIR

exam_dir = data_dir / EXAM_DIR
supp_exam_dir = data_dir / SUPP_EXAM_DIR


data_dir.mkdir(parents=True, exist_ok=True)
notice_dir.mkdir(parents=True, exist_ok=True)
calendar_dir.mkdir(parents=True, exist_ok=True)
exam_dir.mkdir(parents=True, exist_ok=True)
supp_exam_dir.mkdir(parents=True, exist_ok=True)


db_file = data_dir / DB_NAME
db = DbManager(LOGGER, db_file)
db.init_db()


session = Session()
session.request = partial(session.request, timeout=180)
retries = Retry(total=3, backoff_factor=0.3)
adapter = HTTPAdapter(max_retries=retries)
session.mount("http://", adapter)
session.mount("https://", adapter)
