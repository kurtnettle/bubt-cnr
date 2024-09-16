from dataclasses import asdict
from email.utils import parsedate_to_datetime
from hashlib import md5
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from requests.exceptions import BaseHTTPError

from bubt_cnr import LOGGER, db, exam_dir, session, supp_exam_dir
from bubt_cnr.constants import BUBT_ROUTINE_URL
from bubt_cnr.log_tags import LOG_TAGS
from bubt_cnr.models import ExamRoutineData, File
from bubt_cnr.utils import check_n_fix_link

LOG_TAG = LOG_TAGS.EXAM_ROUTINE


class ExamRoutine:
    def get_exam_urls(self, soup, exam_type) -> list[ExamRoutineData]:
        if exam_type == "term":
            shift_name = "term"
            selector = "div#Exam_Routine tbody tr"
            root_prog_dir = exam_dir
            db_tb_name = "term_exams"
        else:
            shift_name = "suppli"
            selector = "div#Sup_Exam_Routine tbody tr"
            root_prog_dir = supp_exam_dir
            db_tb_name = "suppli_exams"

        prog_rtn_urls = []
        cells = soup.select(selector)
        for cell in cells:
            tds = cell.select("td")
            day = tds[0].text.lower().replace("program", "").strip()

            links = tds[1].select("a")
            for link in links:
                link = check_n_fix_link(link["href"])
                if "day" in day:
                    is_day = True
                    prog_dir = root_prog_dir / "day"
                else:
                    is_day = False
                    prog_dir = root_prog_dir / "evn"

                prog_dir.mkdir(parents=True, exist_ok=True)
                data = ExamRoutineData(
                    shift_name=shift_name,
                    is_day=is_day,
                    link=link,
                    prog_dir=prog_dir,
                    db_tb_name=db_tb_name,
                )

                prog_rtn_urls.append(data)

        return prog_rtn_urls

    # TODO: Add support for checking existing file
    # and
    # comparing the changes of db with current one
    # then
    # update records if neccessary
    def download(self, exam_data: ExamRoutineData) -> tuple[str,File]:
        try:
            resp = session.get(exam_data.link)
            resp.raise_for_status()

            url_path = urlparse(exam_data.link).path
            file_path_obj = Path(url_path)

            last_modified = parsedate_to_datetime(resp.headers.get("last-modified"))
            file = exam_data.prog_dir / file_path_obj.name

            file_data = File(
                name=file.name,
                last_modified=int(last_modified.timestamp()),
                link=exam_data.link,
                md5=md5(resp.content).hexdigest(),
            )

            with file.open("wb") as f:
                f.write(resp.content)

            result = db.get_file(file=file_data, tb_name=exam_data.db_tb_name)
            if not result:
                db.add_exam_file(file_data, exam_data.db_tb_name, int(exam_data.is_day))
                return ("done", file_data)
            return ("failed", file_data)

            # if routine_file.exists():
            #     LOGGER.info("[%s] already downloaded <%s>", LOG_TAG, routine_file.name)
            #     if tb_name:
            #         res = db.get_file(file, tb_name)
            #         if len(res) > 1:
            #             LOGGER.info("[%s] found multiple records in db <%s> will only update the latest one", LOG_TAG, routine_file.name)
            #         old_file = File(*res[0])
            #         if old_file.md5 != file.md5:
            #             LOGGER.info("[%s] detected change in file <%s> ", LOG_TAG, routine_file.name)
            #             for field in file.__dataclass_fields__:
            #                 o_val = getattr(old_file, field)
            #                 n_val = getattr(file, field)
            #                 if o_val != n_val:
            #                     print(field,o_val,n_val)
            # else:
            #     LOGGER.info("[%s] downloaded <%s>", LOG_TAG, routine_file.name)
            # return

        except BaseHTTPError as err:
            LOGGER.error(
                "[%s] failed to download the file <%s> reason: %s",
                LOG_TAG,
                exam_data.link,
                err,
            )
            return ("failed", file_data)
        except Exception as err:
            LOGGER.exception(
                "[%s] unknown error occurred while downloading the file <%s> reason: %s",
                LOG_TAG,
                exam_data.link,
                err,
            )
        return "error", None

    def download_by_url(self):
        term_exam_day = ""

        files = []
        prog_dir = exam_dir / "evn"
        prog_dir.mkdir(parents=True, exist_ok=True)
        with open(term_exam_day, "r") as f:
            for i in f.readlines():
                url = i.replace("\n", "")
                data = ExamRoutineData(
                    shift_name="term",
                    is_day=False,
                    link=url,
                    prog_dir=prog_dir,
                    db_tb_name="term_exams",
                )
                files.append(data)

        return files

    def update(self):
        resp = session.get(BUBT_ROUTINE_URL)
        if resp.ok:
            soup = BeautifulSoup(resp.content, "lxml")
        else:
            LOGGER.error(
                "[%s] failed to get calendar page. reason: %s", LOG_TAG, resp.reason
            )
            return

        exam_types = [
            self.get_exam_urls(soup, "term"),
            self.get_exam_urls(soup, "suppli"),
        ]

        if not exam_types[0] and not exam_types[1]:
            LOGGER.error("[%s] found no exam routines.", LOG_TAG)
            return

        if not exam_types[0]:
            LOGGER.error("[%s] found no term exam routines.", LOG_TAG)

        if not exam_types[1]:
            LOGGER.error("[%s] found no supplementary exam routines.", LOG_TAG)

        for exam_type in exam_types:
            for i in exam_type:
                log_text_suffix = f'{i.shift_name} exam routine ({"day" if i.is_day else "evening"}) <{i.link}>'
                status, file = self.download(i)
                if status == "done":
                    LOGGER.info("[%s] downloaded <%s>", LOG_TAG, log_text_suffix)
                elif status == "failed":
                    LOGGER.info("[%s] already downloaded <%s>", LOG_TAG, file.name)
                else:
                    LOGGER.error(
                        "[%s] don't know what happened while downloading the <%s>",
                        LOG_TAG,
                        i.link,
                    )
                    break

                sleep(0.8)
        db.commit()
