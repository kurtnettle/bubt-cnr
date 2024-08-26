from mimetypes import guess_type as guess_mime_type
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bubt_cnr import LOGGER
from bubt_cnr.constants import BUBT_BASE_URL
from bubt_cnr.log_tags import LOG_TAGS

LOG_TAG = LOG_TAGS.UTILS


def check_n_fix_link(url: str, notice_id=None) -> str | None:
    if notice_id:
        notice_id = f"{notice_id} -"

    LOGGER.debug("[%s] %s processing url: %s", LOG_TAG, notice_id, url)

    link = urlparse(url)
    if not link.path:
        LOGGER.debug("[%s] %s url missing path.", LOG_TAG, notice_id)
        return None

    path = Path(link.path)
    file_mime = guess_mime_type(path)
    if file_mime[0] is None:
        LOGGER.debug("[%s] %s url not a file.", LOG_TAG, notice_id)
        return None

    if not link.netloc:
        LOGGER.debug("[%s] %s url missing base url.", LOG_TAG, notice_id)
        return urljoin(BUBT_BASE_URL, url)

    LOGGER.debug("[%s] %s url is valid. required no fixes.", LOG_TAG, notice_id)

    return url


# TODO: Add support for auto renaming files if it exists
def auto_rename_file(file: Path) -> Path:
    return file
