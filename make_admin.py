"""Выдать права администратора пользователю.

Запуск (из папки проекта):  python make_admin.py имя_пользователя
Пользователь должен быть уже зарегистрирован на сайте.
"""
import sqlite3
import sys

from app import DB_PATH

if len(sys.argv) != 2:
    sys.exit('Использование: python make_admin.py имя_пользователя')

name = sys.argv[1]
conn = sqlite3.connect(DB_PATH)
row = conn.execute('SELECT id FROM users WHERE username = ?', (name,)).fetchone()
if not row:
    sys.exit(f'Пользователь «{name}» не найден. Сначала зарегистрируйтесь на сайте.')
conn.execute('UPDATE users SET is_admin = 1 WHERE id = ?', (row[0],))
conn.commit()
print(f'Готово: {name} теперь администратор.')
