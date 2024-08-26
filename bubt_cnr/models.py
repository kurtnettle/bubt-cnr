from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ExamRoutineData:
    shift_name: str
    is_day: bool
    link: str
    prog_dir: Path
    db_tb_name: str


@dataclass
class NoticeData:
    n_api: bool
    n_id: int
    n_link: str
    n_title: str
    n_cat: str
    n_date: str
    n_content: Optional[str] = None
    n_file: Optional[str] = None
    files: list[str] = None


@dataclass
class NoticePageLinks:
    n_id: int
    file: list[str]
    attachments: list[str]
    paragraph_html: str


@dataclass
class NoticeFile:
    name: str
    sln: int
    main_name: str
    link: str
    last_modified: int
    md5: str


@dataclass
class File:
    last_modified: int
    name: str
    link: str
    md5: str
