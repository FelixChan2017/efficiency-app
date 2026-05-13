import os
import sys


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APPDIR = get_app_dir()
DATABASE = os.path.join(APPDIR, "efficiency.db")
