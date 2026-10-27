# Содержимое для WSGI-файла на PythonAnywhere (вкладка Web → ссылка на файл /var/www/..._wsgi.py).
# Удалите всё, что там есть по умолчанию, и вставьте ЭТО целиком.
import os
import sys

PROJECT = os.path.expanduser('~/CYBERPUNK2079_SPACE')   # папка, куда вы сделали git clone

if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from app import app as application  # noqa: E402  (PythonAnywhere ищет объект application)
