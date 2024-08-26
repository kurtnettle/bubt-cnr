from email.utils import parsedate_to_datetime
from hashlib import md5
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from requests import exceptions

from bubt_cnr import LOG_TAGS, LOGGER, calendar_dir, db, session
from bubt_cnr.constants import BUBT_CALENDAR_URL
from bubt_cnr.models import File
from bubt_cnr.utils import check_n_fix_link

LOG_TAG = LOG_TAGS.CALENDAR


class Calendar:
    def get_calendar_url(self) -> list | None:
        try:
            resp = session.get(BUBT_CALENDAR_URL)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except exceptions.BaseHTTPError as err:
            LOGGER.error("[%s] failed to get calendar page. reason: %s", LOG_TAG, err)
            return
        except Exception as err:
            LOGGER.error(
                "[%s] unknown error occurred while getting calendar page. reason: %s",
                LOG_TAG,
                err,
            )
            return

        urls = set()
        soup = BeautifulSoup(resp.content, "lxml")
        soup = soup.select("div.panel > div.panel-body")
        for i in soup:
            x = (
                i.find_all(attrs={"src": True})
                + i.find_all(attrs={"href": True})
                + i.find_all(attrs={"data": True})
            )
            for j in x:
                try:
                    urls.add(check_n_fix_link(j["src"]))
                    urls.add(check_n_fix_link(j["href"]))
                    urls.add(check_n_fix_link(j["data"]))
                except KeyError:
                    pass

        return list(urls)

    def download(self, link) ->tuple:
        try:
            resp = session.get(link)
            resp.raise_for_status()

            url_path = urlparse(link).path
            file_path_obj = Path(url_path)
            calendar_file = calendar_dir / file_path_obj.name

            with calendar_file.open("wb") as f:
                f.write(resp.content)

            last_modified = parsedate_to_datetime(resp.headers.get("last-modified"))
            file = File(
                name=calendar_file.name,
                last_modified=int(last_modified.timestamp()),
                link=link,
                md5=md5(resp.content).hexdigest(),
            )

            result = db.get_file(file, "calendars")
            if not result:
                db.add_calendar_file(file)
                return ("done", calendar_file.name)
            return ("failed", calendar_file.name)

        except exceptions.BaseHTTPError as err:
            LOGGER.error(
                "[%s] failed to download calendar file <%s> reason: %s",
                LOG_TAG,
                link,
                err,
            )
        except Exception as err:
            LOGGER.error(
                "[%s] unknown error occurred while downloading calendar file <%s> reason: %s",
                LOG_TAG,
                link,
                err,
            )
            LOGGER.exception(err)

        return "error", None

    def update(self) -> bool:
        LOGGER.info("[%s] checking for calendar update", LOG_TAG)

        calendar_url = self.get_calendar_url()
        for i in calendar_url:
            exist, name = self.download(i)
            if exist == "done":
                LOGGER.info("[%s] downloaded new calendar <%s>", LOG_TAG, name)
            elif exist == "failed":
                LOGGER.info("[%s] calendar was already downloaded <%s>", LOG_TAG, name)
            elif exist == "error":
                LOGGER.info("[%s] failed to download the calendar <%s>", LOG_TAG, name)
            else:
                LOGGER.info(
                    "[%s] don't know what happened while downloading the calendar <%s>",
                    LOG_TAG,
                    name,
                )

            sleep(0.7)

        db.commit()
