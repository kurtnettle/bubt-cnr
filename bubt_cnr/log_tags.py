from dataclasses import dataclass

__LOG_TAGS = {
    "APP": "APP",
    "CALENDAR": "Calendar",
    "DB": "DB",
    "EXAM_ROUTINE": "Exam Routine",
    "NOTICE": "Notice",
    "UTILS": "Utils",
}

max_len = max(len(v) for v in __LOG_TAGS.values())
__LOG_TAGS = {k: v.center(max_len) for k, v in __LOG_TAGS.items()}


@dataclass
class LogTags:
    APP: str
    CALENDAR: str
    DB: str
    EXAM_ROUTINE: str
    NOTICE: str
    UTILS: str


LOG_TAGS = LogTags(*__LOG_TAGS.values())
