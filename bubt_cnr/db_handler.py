import sqlite3

from bubt_cnr.log_tags import LOG_TAGS
from bubt_cnr.models import File, NoticeData, NoticeFile

LOG_TAG = LOG_TAGS.DB


class DbManager:
    def __init__(self, logger, db_file):
        self.logger = logger
        self.db_file = db_file
        self.connect()

    def connect(self):
        try:
            self.logger.info("[%s] opening database", LOG_TAG)
            self.conn = sqlite3.connect(self.db_file)
            self.cur = self.conn.cursor()
        except sqlite3.OperationalError as error:
            self.logger.error("[%s] error in DB connection: %s", LOG_TAG, error)

    def commit(self):
        try:
            self.conn.commit()
        except sqlite3.OperationalError as e:
            self.logger.info("[%s] operational error during commit: %s", LOG_TAG, e)
        except sqlite3.IntegrityError as e:
            self.logger.info("[%s] integrity error during commit: %s", LOG_TAG, e)
        except sqlite3.Error as e:
            self.logger.info("[%s] unknown error during commit: %s", LOG_TAG, e)

    def init_db(self):
        self.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notices(
                id INTEGER PRIMARY KEY,
                link TEXT,
                title TEXT,
                cat TEXT,
                date TEXT,
                content TEXT,
                file TEXT,
                files TEXT
            )
            """
        )

        self.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notice_files(
                name TEXT PRIMARY KEY,
                sln INTEGER,                    
                main_name TEXT,
                link TEXT,
                last_modified TEXT,
                md5 TEXT
            )
            """
        )

        self.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS calendars(
                last_modified TEXT,
                name TEXT,
                link TEXT,
                md5 TEXT
            )
            """
        )

        self.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS term_exams(
                last_modified TEXT,
                name TEXT,
                link TEXT,
                md5 TEXT,
                is_day INTEGER
            )
            """
        )

        self.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS suppli_exams(
                last_modified TEXT,
                name TEXT,
                link TEXT,
                md5 TEXT,
                is_day INTEGER
            )
            """
        )

        self.commit()

    def add_notice(self, notice: NoticeData):
        self.cur.execute(
            """
            INSERT INTO notices(
               id,  link,  title,  cat,  date,  content,  file, files
            ) 
            VALUES (
              :id, :link, :title, :cat, :date, :content, :file, :files
            )
            """,
            {
                "id": notice.n_id,
                "link": notice.n_link,
                "title": notice.n_title,
                "cat": notice.n_cat,
                "date": notice.n_date,
                "content": notice.n_content,
                "file": notice.n_file,
                "files": notice.files,
            },
        )

    def add_notice_file(self, file: NoticeFile):
        self.cur.execute(
            """
            INSERT INTO notice_files(
               name,  sln,  main_name,  link,  last_modified, md5
            ) 
            VALUES 
            (
              :name, :sln, :main_name, :link, :last_modified, :md5
            )
            """,
            {
                "name": file.name,
                "sln": file.sln,
                "main_name": file.main_name,
                "link": file.link,
                "last_modified": file.last_modified,
                "md5": file.md5,
            },
        )

    def get_notice_file(self, file: NoticeFile) -> list:
        self.cur.execute(
            """
            SELECT * 
            FROM notice_files
            WHERE name == :name OR main_name == :main_name
            """,
            {
                "name": file.name,
                "main_name": file.main_name,
            },
        )

        return self.cur.fetchall()

    def get_last_notice_id(self) -> int:
        self.cur.execute(
            """
            SELECT id
            FROM notices
            ORDER BY id DESC
            LIMIT 1;        
            """
        )

        result = self.cur.fetchone()
        if result:
            result = result[0]
        else:
            result = 0

        return result

    def get_last_notice_sln(self, notice_id) -> int:
        self.cur.execute(
            """
            SELECT COUNT(id) 
            FROM notices
            WHERE id <= :notice_id
            """,
            {
                "notice_id": notice_id,
            },
        )

        result = self.cur.fetchone()
        if result:
            result = result[0]
        else:
            result = 0

        return result

    def add_exam_file(self, file: File, tb_name, is_day: int):
        self.cur.execute(
            f"""
            INSERT INTO {tb_name} (
               name,  last_modified,  link,  md5, is_day
            ) 
            VALUES (
              :name, :last_modified, :link, :md5, :is_day
            )
            """,
            {
                "name": file.name,
                "last_modified": file.last_modified,
                "link": file.link,
                "md5": file.md5,
                "is_day": is_day,
            },
        )

    def add_calendar_file(self, file: File):
        self.cur.execute(
            """
            INSERT INTO calendars(
               name,  last_modified,  link,  md5
            ) 
            VALUES (
              :name, :last_modified, :link, :md5
            )
            """,
            {
                "name": file.name,
                "last_modified": file.last_modified,
                "link": file.link,
                "md5": file.md5,
            },
        )

    def get_file(self, file: File, tb_name: str) -> list:
        self.cur.execute(
            f"""
            SELECT * 
            FROM {tb_name}
            WHERE md5 == :md5 OR name == :name
            ORDER BY last_modified DESC 
            """,
            {
                "md5": file.md5,
                "name": file.name,
            },
        )

        return self.cur.fetchall()

    def __del__(self):
        self.logger.info("[%s] closing database", LOG_TAG)
        if self.conn:
            self.commit()
            self.conn.close()
