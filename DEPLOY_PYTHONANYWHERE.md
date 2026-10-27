# Выкладка на PythonAnywhere (бесплатный тариф)

Адрес сайта будет `https://ВАШ_ЛОГИН.pythonanywhere.com`. Ниже `ВАШ_ЛОГИН` — логин на PythonAnywhere.

## 1. Регистрация
[pythonanywhere.com](https://www.pythonanywhere.com/) → Pricing → **Create a Beginner account** (бесплатно).

## 2. Код и зависимости (вкладка Consoles → Bash)
```bash
git clone https://github.com/joshibelike/CYBERPUNK2079_SPACE.git
cd CYBERPUNK2079_SPACE
mkvirtualenv --python=/usr/bin/python3.10 cp-venv
pip install -r requirements.txt
python seed_content.py
```
`seed_content.py` создаёт базу и заливает классы и предыстории. Если нужной версии Python нет, возьмите `python3.11` или `python3.12`
(`ls /usr/bin | grep python3`).

## 3. Веб-приложение (вкладка Web)
1. **Add a new web app** → Next → **Manual configuration** → ту же версию Python → Next.
2. Раздел **Virtualenv**: впишите `/home/ВАШ_ЛОГИН/.virtualenvs/cp-venv`.
3. Раздел **Code** → ссылка на WSGI-файл (`/var/www/ВАШ_ЛОГИН_pythonanywhere_com_wsgi.py`): удалите содержимое и вставьте
   содержимое файла `pythonanywhere_wsgi.py` из репозитория.
4. Раздел **Static files** (необязательно, но быстрее): URL `/static/` → Directory `/home/ВАШ_ЛОГИН/CYBERPUNK2079_SPACE/static`.
5. Нажмите зелёную кнопку **Reload**. Откройте `https://ВАШ_ЛОГИН.pythonanywhere.com`.

## 4. Администратор
1. Зарегистрируйтесь на сайте обычным способом (например, как `joshibelike`).
2. В Bash-консоли:
```bash
cd ~/CYBERPUNK2079_SPACE && workon cp-venv && python make_admin.py joshibelike
```
3. По умолчанию в базе есть аккаунт `admin` с паролем `admin123` — **сразу смените пароль** (Аккаунт → Смена пароля).

## 5. Обновление сайта
```bash
cd ~/CYBERPUNK2079_SPACE && git pull
```
затем **Reload** на вкладке Web. База (`database.db`), секретный ключ (`secret.key`) и загрузки (`static/uploads`) не входят в git,
поэтому при `git pull` данные игроков не затрутся.

## 6. Перенос уже существующих данных (по желанию)
Чтобы взять аккаунты и листы с локального компьютера: вкладка **Files** → папка `CYBERPUNK2079_SPACE` → загрузите свой
`database.db` (он заменит новую пустую) и аватары/фото в `static/uploads/`. После этого Reload.

## Ограничения бесплатного тарифа
- Раз в ~3 месяца на вкладке Web нужно нажимать кнопку продления («Run until …»), иначе сайт отключат.
- Ограничены процессорное время в сутки и размер диска; для небольшой игры обычно достаточно.
- Если ошибка: вкладка Web → ссылки **Error log** и **Server log**.
