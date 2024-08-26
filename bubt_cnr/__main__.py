import argparse
from time import sleep

from bubt_cnr import LOG_TAGS
from bubt_cnr.calendar import Calendar
from bubt_cnr.exam_routine import ExamRoutine
from bubt_cnr.notice import Notice

LOG_TAG = LOG_TAGS.APP


valid_args = ["notice", "examroutine", "calendar"]
parser = argparse.ArgumentParser(prog="BUBT-CNR")
for i in valid_args:
    parser.add_argument(f"-{i}", action="store_true", required=False)


if __name__ == "__main__":
    args = parser.parse_args()

    cooldown = 0
    if args.calendar:
        sleep(cooldown)
        Calendar().update()
        cooldown = 2

    if args.notice:
        sleep(cooldown)
        Notice().update()
        cooldown = 2

    if args.examroutine:
        sleep(cooldown)
        ExamRoutine().update()
        cooldown = 2
