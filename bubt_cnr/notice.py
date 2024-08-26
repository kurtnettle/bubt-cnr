import re
from dataclasses import asdict
from email.utils import parsedate_to_datetime
from hashlib import md5
from json import dumps, load
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from requests import exceptions

from bubt_cnr import LOGGER, NOTICE_API_URL, db, notice_dir, session
from bubt_cnr.constants import BUBT_NOTICE_URL
from bubt_cnr.log_tags import LOG_TAGS
from bubt_cnr.models import NoticeData, NoticeFile, NoticePageLinks
from bubt_cnr.utils import check_n_fix_link

LOG_TAG = LOG_TAGS.NOTICE


class Notice:
    def get_pending_notices_from_api(self, last_notice_id: int) -> list | None:
        last_notice_id = int(last_notice_id)

        try:
            resp = session.get(NOTICE_API_URL)
            json = resp.json()
        except exceptions.BaseHTTPError as err:
            LOGGER.error(
                "[%s] failed to get response from api. reason: %s", LOG_TAG, err
            )
            return
        except exceptions.JSONDecodeError as err:
            LOGGER.error("[%s] failed to parse api response. reason: %s", LOG_TAG, err)
            return
        except Exception as err:
            LOGGER.error(
                "[%s] unknown error occurred while getting response from API. reason: %s",
                LOG_TAG,
                err,
            )
            return

        notices = []
        for i in json["notices"]:
            ntc_id = int(i.get("id"))
            if ntc_id <= last_notice_id:
                continue

            data = NoticeData(
                n_api=True,
                n_id=ntc_id,
                n_link=i.get("link"),
                n_title=i.get("title"),
                n_content=i.get("content"),
                n_cat=i.get("cat_title"),
                n_date=i.get("date"),
                n_file=i.get("file"),
            )

            notices.append(data)

        return notices

    def get_pending_notices_from_html(self, last_notice_id: int) -> list | None:
        last_notice_id = int(last_notice_id)

        try:
            resp = session.get(BUBT_NOTICE_URL)
            resp.raise_for_status()
            resp.encoding = "utf-8"
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

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.select("#dtNoticeTable tbody")[0]

        notices = []
        for i in table.find_all("tr"):
            tds = i.find_all("td")

            ntc_link = tds[0].find("a")["href"]
            ntc_id = int(ntc_link.split("/")[-1])

            if ntc_id <= last_notice_id:
                continue

            ntc_title = tds[0].find("h4").get_text(strip=True)
            ntc_cat = tds[1].get_text(strip=True)
            ntc_date = tds[2].get_text(strip=True)

            data = NoticeData(
                n_api=False,
                n_id=ntc_id,
                n_cat=ntc_cat,
                n_link=ntc_link,
                n_title=ntc_title,
                n_date=ntc_date,
            )

            notices.append(data)

        return notices

    def extract_links_from_text(self, text: str, notice_id) -> set:
        links = set()
        if text:
            res = re.findall(r"(https?://\S+)", text)
            if res:
                for i in res:
                    x = check_n_fix_link(i, notice_id)
                    if x:
                        links.add(x)
        return links

    def extract_links_from_soup(self, soup: Tag | str, notice_id: int) -> dict:
        if isinstance(soup, str):
            soup = BeautifulSoup(soup, "lxml")

        checked_urls = set()
        urls = soup.find_all(attrs={"src": True}) + soup.find_all(attrs={"href": True})

        for i in urls:
            link = None
            try:
                link = i["src"]
            except KeyError:
                link = i["href"]

            link = check_n_fix_link(link, notice_id)
            if link:
                checked_urls.add(link)

        return checked_urls

    def extract_link_from_notice_page(self, n_link, notice_id) -> dict:
        resp = session.get(n_link)
        resp.encoding = "utf-8"
        if not resp.ok:
            LOGGER.error(
                "[%s] %s - failed to get notice page (%s). reason: %s",
                LOG_TAG,
                notice_id,
                n_link,
                resp.reason,
            )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        soup = soup.select("div.devs_history_body")[0]

        para_div = soup.select("div.event-details")[0]
        para_text = para_div.get_text(strip=True)
        para_html = para_div.decode_contents().strip()

        dl_btn = soup.select("a.btn")

        links = self.extract_links_from_soup(soup, notice_id)

        if para_text:
            LOGGER.debug(
                "[%s] %s - found paragraph. checking for links", LOG_TAG, notice_id
            )
            para_links = self.extract_links_from_text(para_text, notice_id)

            if para_links:
                links.update(para_links)
            LOGGER.debug(
                "[%s] %s - paragraph has %s links. <%s>",
                LOG_TAG,
                notice_id,
                len(para_links),
                para_links,
            )

        file = []
        if dl_btn:
            file = check_n_fix_link(dl_btn[0]["href"], notice_id)
            if file:
                try:
                    links.remove(file)
                    LOGGER.debug(
                        "[%s] %s - removed file link from attachments links.",
                        LOG_TAG,
                        notice_id,
                    )
                except KeyError:
                    LOGGER.error(
                        "[%s] %s - failed to remove file link from attachments links. (%s) <%s>",
                        LOG_TAG,
                        notice_id,
                        file,
                        links,
                    )
                file = [file]

        return NoticePageLinks(
            n_id=notice_id,
            attachments=list(links),
            file=file,
            paragraph_html=para_html,
        )

    def get_pending_notices(self, last_msg_id) -> list[NoticeData]:
        if NOTICE_API_URL:
            notices_from_api = self.get_pending_notices_from_api(last_msg_id)
        else:
            notices_from_api = []
        notices_from_html = self.get_pending_notices_from_html(last_msg_id)

        pending_notices = []
        ids_added = []

        for api_notice in notices_from_api:
            if api_notice.n_id not in ids_added:
                ids_added.append(api_notice.n_id)
                pending_notices.append(api_notice)

        for html_notice in notices_from_html:
            if html_notice.n_id not in ids_added:
                ids_added.append(html_notice.n_id)
                pending_notices.append(html_notice)

        return sorted(pending_notices, key=lambda x: x.n_id)

    def download_file(
        self, files: list[NoticeFile], notice_id: int
    ) -> list[NoticeFile]:
        for idx, file in enumerate(files, start=1):
            notice_file = notice_dir / file.name

            # if notice_file.exists() and file.last_modified != -1:
            #     LOGGER.info(
            #         "[%s] %s - (%s/%s) file exists <%s>",
            #         LOG_TAG,
            #         notice_id,
            #         idx,
            #         len(files),
            #         file.name,
            #     )
            #     continue

            LOGGER.info(
                "[%s] %s - (%s/%s) downloading file <%s (%s)>",
                LOG_TAG,
                notice_id,
                idx,
                len(files),
                file.name,
                file.link,
            )

            resp = session.get(file.link)
            if not resp.ok:
                LOGGER.error(
                    "[%s] %s - (%s/%s) failed to download file <%s>",
                    LOG_TAG,
                    notice_id,
                    idx,
                    len(files),
                    file.name,
                )
                continue

            files[idx - 1].md5 = md5(resp.content).hexdigest()
            last_modified = parsedate_to_datetime(resp.headers.get("last-modified"))
            files[idx - 1].last_modified = int(last_modified.timestamp())
            with notice_file.open("wb") as f:
                f.write(resp.content)

            LOGGER.info(
                "[%s] %s - (%s/%s) downloaded file <%s>",
                LOG_TAG,
                notice_id,
                idx,
                len(files),
                file.name,
            )

            sleep(0.3)

        return files

    def prepare_files(
        self, notice_id: int, files: list[str], start: int = 0
    ) -> list[NoticeFile]:
        prepared_files = []
        # existing_files = None

        # notice_meta_file = notice_dir / f"{str(notice_id).zfill(4)}.json"
        # if notice_meta_file.exists():
        #     with notice_meta_file.open("r") as f:
        #         existing_files = load(f).get("files")

        for idx, link in enumerate(files, start=start):
            url_path = urlparse(link).path
            file_path_obj = Path(url_path)

            main_name = file_path_obj.name
            name = f"{notice_id}_{str(idx).zfill(2)}{file_path_obj.suffix}"  # example: 1179_01.pdf

            prepared_files.append(
                NoticeFile(
                    name=name,
                    sln=idx,
                    main_name=main_name,
                    link=link,
                    last_modified=-1,
                    md5=None,
                )
            )

        # if existing_files:
        #     for i in existing_files:
        #         for idx, j in enumerate(prepared_files):
        #             if (
        #                 i.get("new_name") == j.new_name
        #                 and i.get("last_modified") != j.last_modified
        #             ):
        #                 prepared_files[idx].last_modified = i.get("last_modified")

        return prepared_files

    def download_notice(self, notice: NoticeData) -> list[str]:
        file = []
        attachments = []

        if not notice.n_api:
            # n_link = f"http://0.0.0.0:8000/{str(notice.n_id).zfill(4)}.html"
            n_page_links = self.extract_link_from_notice_page(
                notice.n_link, notice.n_id
            )
            file = n_page_links.file
            notice.n_content = n_page_links.paragraph_html
            attachments = n_page_links.attachments
        else:
            if notice.n_content:
                attachments = self.extract_links_from_soup(
                    notice.n_content, notice.n_id
                )

            if notice.n_file:
                file = check_n_fix_link(notice.n_file, notice.n_id)
                if file:
                    file = [file]

        LOGGER.debug(
            "[%s] %s - attachments: %s <> file: %s",
            LOG_TAG,
            notice.n_id,
            len(attachments),
            len(file),
        )

        files = self.prepare_files(notice.n_id, file, 0) + self.prepare_files(
            notice.n_id, attachments, 1
        )

        # is_success, downloaded_files = True, files
        downloaded_files = self.download_file(files, notice.n_id)
        LOGGER.info("[%s] %s - download %s files", LOG_TAG, notice.n_id, len(files))

        files = sorted(downloaded_files, key=lambda x: x.sln)
        file_names = [x.name for x in files]
        for i in files:
            db.add_notice_file(file=i)

        # notice_meta_file = notice_dir / f"{str(notice.n_id).zfill(4)}.json"
        # with notice_meta_file.open("w") as f:
        #     files = [asdict(x) for x in files]
        #     data = {"notice": asdict(notice), "files": files}
        #     f.write(dumps(data, indent=2))

        return file_names

    def update(self) -> bool:
        last_notice_id = db.get_last_notice_id()
        last_notice_sln = db.get_last_notice_sln(last_notice_id)
        LOGGER.info(
            "[%s] last notice id: %s (%s)", LOG_TAG, last_notice_id, last_notice_sln
        )

        x = self.get_pending_notices(last_notice_id)

        LOGGER.info("[%s] found %s pending notices", LOG_TAG, len(x))
        for i in x:
            LOGGER.info("[%s] %s - processing the notice", LOG_TAG, i.n_id)
            try:
                files = self.download_notice(i)
                if files:
                    i.files = str(files)

                db.add_notice(i)
            except Exception as err:
                LOGGER.error(
                    "[%s] %s - failed to process the notice (%s)", LOG_TAG, i.n_id, err
                )
                break

            db.commit()
            sleep(0.6)
