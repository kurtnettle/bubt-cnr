import itertools
import json
import os
import re
import subprocess
import tempfile
from email.utils import parsedate_to_datetime
from hashlib import md5
from pathlib import Path
from time import sleep
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from requests import exceptions

from bubt_cnr import LOGGER, db, notice_dir, session
from bubt_cnr.constants import BUBT_NOTICE_URL,NODE_PATH
from bubt_cnr.log_tags import LOG_TAGS
from bubt_cnr.models import NoticeData, NoticeFile

LOG_TAG = LOG_TAGS.NOTICE


class NoticeV2:
    """
    v2 of the notice updater for the new BUBT website version written from scratch.
    """

    def __init__(self):
        self.node_path = NODE_PATH

    def get_notice_webpage_html(self) -> str | None:
        try:
            resp = session.get(BUBT_NOTICE_URL)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            return resp.text
        except exceptions.BaseHTTPError as err:
            LOGGER.error(
                "[%s] failed to get notice page. reason: %s",
                LOG_TAG,
                err,
            )
            return
        except Exception as err:
            LOGGER.error(
                "[%s] unknown error occurred while getting notice page. reason: %s",
                LOG_TAG,
                err,
            )
            return

    def extract_notice_filter_function_from_html(self, html: str):
        """
        Extract window.noticeList variable from HTML.

        Searches for `function noticeFilter() {...}` pattern in HTML, wraps it in
        code that calls the function and outputs the notices array as JSON.

        Args:
            html(str): HTML source code of the BUBT notice webpage.

        Returns:
            Optional[str]: JavaScript code that, when executed, outputs window.noticeList as JSON string,
            or None if window.noticeList is not found.

        Example:
            Given HTML containing:
            ```
            <script>
            function noticeFilter() {
                return {
                    notices: [
                        {"id":1454,"category_id":1,"title":"Confirmation ....}
                    ]
                };
            }
            </script>
            ```

            Returns JavaScript:
            ```
            function noticeFilter() {
                return {
                    notices: [
                        {"id":1454,"category_id":1,"title":"Confirmation ...."}
                    ]
                };
            }
            const result = noticeFilter();
            const data = result.notices;
            console.log(JSON.stringify(data));
            ```

            Which when executed outputs:
            ```
            [{"id":1454,"category_id":1,"title":"Confirmation ...."}]
            ```
        """

        pattern = r"<script>\s*function\s+noticeFilter\s*\(\)\s*\{.*?\}\s*</script>"
        match = re.search(pattern, html, re.DOTALL)

        if not match:
            LOGGER.warning(
                "[%s] Failed to extract noticeFilter() function, no match found",
                LOG_TAG,
            )
            return None

        notice_filter_js = (
            match.group(0).replace("<script>", "").replace("</script>", "")
        )
        result = f"""
        {notice_filter_js}
        const result = noticeFilter();
        const data = result.notices
        console.debug(JSON.stringify(data))
        """

        return result

    def extract_window_noticelist_var_from_html(self, html: str) -> Optional[str]:
        """
        Extract window.noticeList variable from HTML.

        Searches for `window.noticeList = [...];` pattern in HTML, outputs the array as JSON when executed.

        Args:
            html(str): HTML source code of the BUBT notice webpage.

        Returns:
            Optional[str]: JavaScript code that, when executed, outputs window.noticeList as JSON string,
            or None if window.noticeList is not found.

        Example:
            Given HTML containing:
            ```
            <script>
                window.noticeList = [{"id":1454,"category_id":1,"title":"Confirmation ...."}];
            </script>
            ```

            Returns JavaScript:
            ```
            const noticeList = [{"id":1454,"category_id":1,"title":"Confirmation ...."}];
            console.log(JSON.stringify(noticeList || []));
            ```

            Which when executed outputs:
            ```
            [{"id":1454,"category_id":1,"title":"Confirmation ...."}]
            ```
        """

        pattern = r"window\.noticeList\s*=\s*\[.*?\];"
        match = re.search(pattern, html, re.DOTALL)

        if not match:
            LOGGER.warning(
                "[%s] Failed to extract window.noticeList function, no match found",
                LOG_TAG,
            )
            return None

        noticelist_js = match.group(0).replace("window.", "const ")
        result = f"""
        {noticelist_js}
        console.log(JSON.stringify(noticeList || []));
        """

        return result

    def execute_and_capture_js_output(self, js_code):
        """
        Execute JavaScript with Node.js and capture output.

        Args:
            js_code: JS code to execute

        Returns:
            stdout from JavaScript execution, or empty string on failure
        """

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(js_code)
            temp_file = f.name

        try:
            result = subprocess.run(
                [self.node_path, temp_file],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )

            if result.stderr:
                LOGGER.error("[%s] Errors while executing: %s", LOG_TAG, result.stderr)

            return result.stdout
        except Exception as e:
            LOGGER.error("[%s] Failed to execute tempjs file: %s", LOG_TAG, e)
        finally:
            try:
                os.unlink(temp_file)
            except OSError as e:
                LOGGER.warning("[%s] Failed to delete tempjs file: %s", LOG_TAG, e)

    def _extract_notices_from_js(self, js_code: str, source_name: str):
        if not js_code:
            LOGGER.warning("[%s] No JavaScript extracted from %s", LOG_TAG, source_name)
            return []

        try:
            LOGGER.debug("[%s] Executing %s JavaScript", LOG_TAG, source_name)
            output = self.execute_and_capture_js_output(js_code)
            notices = json.loads(output) if output else []

            if not isinstance(notices, list):
                LOGGER.warning(
                    "[%s] Expected list from %s, got %s",
                    LOG_TAG,
                    source_name,
                    type(notices),
                )

            LOGGER.info(
                "[%s] Extracted %s notices from %s",
                LOG_TAG,
                len(notices),
                source_name,
            )

            return notices
        except json.JSONDecodeError as e:
            LOGGER.error(
                "[%s] Failed to parse JSON from %s: %s",
                LOG_TAG,
                source_name,
                e,
            )
            return []
        except Exception as e:
            LOGGER.error(
                "[%s] Failed to execute %s: %s",
                LOG_TAG,
                source_name,
                e,
            )
            return []

    def extract_notices_from_html(self, html: str) -> dict[str, dict]:
        """
        Extract and merge notices from notice webpage.

        Args:
            html(str): HTML content containing notice data

        Returns:
            Dictionary of unique notices keyed by their ID

        Raises:
            ValueError: If HTML extraction fails
        """

        try:
            filter_func_js = self.extract_notice_filter_function_from_html(html)
            window_noticelist_js = self.extract_window_noticelist_var_from_html(html)
        except Exception as e:
            LOGGER.error("[%s] Failed to extract JS from HTML: %s", LOG_TAG, e)
            raise ValueError(f"HTML extraction failed: {e}") from e

        notices_from_filter = self._extract_notices_from_js(
            filter_func_js, "noticeFilter()"
        )

        notices_from_window = self._extract_notices_from_js(
            window_noticelist_js, "window.noticeList"
        )

        return notices_from_filter, notices_from_window

    def merge_extracted_notices(
        self, notices_from_filter: list, notices_from_window: list
    ):
        LOGGER.info(
            "[%s] Merging notices from noticeFilter() & window.noticeList", LOG_TAG
        )

        merged_notices = dict()

        all_notices = itertools.chain(notices_from_filter, notices_from_window)
        for notice in all_notices:
            notice_id = notice.get("id")
            if notice_id is None:
                LOGGER.debug("[%s] Notice missing 'id' field, skipping", LOG_TAG)
                continue

            id_str = str(notice_id)
            if id_str not in merged_notices:
                merged_notices[id_str] = notice
            else:
                LOGGER.debug(
                    "[%s] Duplicate notice with id %s skipped", LOG_TAG, id_str
                )

        LOGGER.info(
            "[%s] Merged %s unique notices from noticeFilter() and window.noticeList",
            LOG_TAG,
            len(merged_notices),
        )

        notices = list(merged_notices.values())
        notices = sorted(notices, key=lambda x: x["id"])

        return notices

    def download_notice_files(self, notice: NoticeData) -> NoticeFile:
        """
        Download a single notice file and return NoticeFile object.

        Args:
            notice (NoticeData): Notice to process

        Returns:
            NoticeFile: Downloaded notice file
        """
        file_link = notice.n_file
        url_path = urlparse(file_link).path
        file_path_obj = Path(url_path)

        n_slug = notice.n_link.split("/")[-1]

        filename = f"{notice.n_id}_00_{n_slug[:150]}{file_path_obj.suffix}"
        notice_file = notice_dir / filename

        LOGGER.info(
            "[%s] %s - downloading file <%s (%s)>",
            LOG_TAG,
            notice.n_id,
            filename,
            file_link,
        )

        resp = session.get(file_link)

        # TODO: Calculate hash by chunks for better memory management.
        # So far I have seen most attachments of BUBT notices are under 5MB
        md5hash = md5(resp.content).hexdigest()

        last_modified = parsedate_to_datetime(resp.headers.get("last-modified"))
        last_modified = int(last_modified.timestamp())

        with notice_file.open("wb") as f:
            f.write(resp.content)

        ntc_file = NoticeFile(
            name=filename,
            sln=0,  # previously in some notices, we have multiple files so serial no was needed.
            main_name=file_path_obj.name,
            link=file_link,
            last_modified=last_modified,
            md5=md5hash,
        )

        db.add_notice_file(file=ntc_file)

        return ntc_file

    def parse_notice_data(self, raw_notice: dict) -> NoticeData:
        """Parse raw notice dictionary into NoticeData object."""
        try:
            ntc_id = int(raw_notice["id"])
            title = raw_notice["title"]
            created_at = raw_notice["created_at"]
            cat_name = raw_notice["category"]["name"]

            desc = raw_notice["description"]
            soup = BeautifulSoup(desc, "lxml")

            link = "https://bubt.edu.bd/notice/details/" + raw_notice["slug"]
            file_link = None
            if raw_notice.get("file"):
                file_link = "https://bubt.edu.bd/storage/" + raw_notice["file"]

            return NoticeData(
                n_api=False,
                n_id=ntc_id,
                n_link=link,
                n_title=title,
                n_cat=cat_name,
                n_date=created_at,
                n_content=soup.text,
                n_file=file_link,
            )
        except KeyError as e:
            raise ValueError(f"Missing required field in notice data: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to parse notice data: {e}") from e

    def get_pending_notices(self, last_notice_id: int) -> list[NoticeData]:
        html = self.get_notice_webpage_html()
        notice0, notice1 = self.extract_notices_from_html(html)
        all_notices = self.merge_extracted_notices(notice0, notice1)

        pending_notices = []
        for notice in all_notices:
            ntc_id = int(notice["id"])
            if ntc_id <= last_notice_id:
                continue

            parsed_notice = self.parse_notice_data(notice)
            pending_notices.append(parsed_notice)

        return pending_notices

    def update(self):
        last_notice_id = db.get_last_notice_id()
        last_notice_sln = db.get_last_notice_sln(last_notice_id)
        LOGGER.info(
            "[%s] Last notice id: %s and serial: %s",
            LOG_TAG,
            last_notice_id,
            last_notice_sln,
        )

        pending_notices = self.get_pending_notices(last_notice_id)
        LOGGER.info("[%s] Got %s pending notices", LOG_TAG, len(pending_notices))

        for notice in pending_notices:
            LOGGER.info("[%s] %s - processing the notice", LOG_TAG, notice.n_id)
            try:
                if notice.n_file:
                    self.download_notice_files(notice)
                    db.add_notice(notice)
            except Exception as err:
                LOGGER.error(
                    "[%s] %s - failed to process the notice (%s)",
                    LOG_TAG,
                    notice.n_id,
                    err,
                )
                break

            db.commit()
            sleep(1)
