import os
import secrets
import sqlite3
import json
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, flash, redirect, render_template, request, session, url_for

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('CP_DB_PATH', os.path.join(BASE_DIR, 'database.db'))


def _load_secret_key():
    # 1) переменная окружения SECRET_KEY, 2) файл secret.key рядом с app.py (создаётся при первом запуске)
    env = os.environ.get('SECRET_KEY')
    if env:
        return env
    path = os.path.join(BASE_DIR, 'secret.key')
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = _load_secret_key()

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Фото персонажей: static/uploads/sheets, до 6 МБ, только PNG / JPEG / GIF / WEBP (тип определяется по содержимому)
SHEET_PHOTO_DIR = os.path.join(app.root_path, 'static', 'uploads', 'sheets')
SHEET_PHOTO_PREFIX = 'uploads/sheets/'
MAX_PHOTO_BYTES = 6 * 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = MAX_PHOTO_BYTES + 512 * 1024
os.makedirs(SHEET_PHOTO_DIR, exist_ok=True)


def detect_image_ext(head):
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    return None


def remove_sheet_photo(rel_path):
    """Удаляет файл фото, только если он лежит в папке фото листов."""
    if rel_path and rel_path.startswith(SHEET_PHOTO_PREFIX):
        path = os.path.join(SHEET_PHOTO_DIR, os.path.basename(rel_path))
        if os.path.isfile(path):
            os.remove(path)


# БД
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        # Таблица пользователей
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                avatar TEXT DEFAULT 'uploads/avatars/default.png',
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Таблица классов
        conn.execute('''
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                hit_dice TEXT NOT NULL,
                hp_next_level TEXT NOT NULL,
                weapon_proficiencies TEXT NOT NULL,
                save_proficiencies TEXT NOT NULL,
                skill_proficiencies TEXT NOT NULL,
                equipment TEXT NOT NULL,
                fighting_style_choice TEXT,
                second_wind TEXT
            )
        ''')
        # Таблица особенностей классов
        conn.execute('''
            CREATE TABLE IF NOT EXISTS class_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                feature_name TEXT NOT NULL,
                feature_description TEXT NOT NULL,
                FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE
            )
        ''')
        # Таблица предысторий
        conn.execute('''
            CREATE TABLE IF NOT EXISTS backgrounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                skill_profs TEXT NOT NULL,
                equipment TEXT NOT NULL,
                languages TEXT,
                feature_name TEXT NOT NULL,
                feature_description TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS background_choice_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                background_id INTEGER NOT NULL,
                group_title TEXT NOT NULL,
                options_json TEXT NOT NULL,
                FOREIGN KEY (background_id) REFERENCES backgrounds (id) ON DELETE CASCADE
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS character_sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sheet_data TEXT NOT NULL,   -- JSON со всеми полями
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        admin = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
        if not admin:
            hashed = generate_password_hash('admin123')
            conn.execute(
                "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                ('admin', 'admin@example.com', hashed, 1)
            )
        fighter = conn.execute("SELECT * FROM classes WHERE name = 'Боец'").fetchone()
        if not fighter:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO classes (name, hit_dice, hp_next_level, weapon_proficiencies, save_proficiencies, skill_proficiencies, equipment, fighting_style_choice, second_wind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'Боец',
                '1к10 за каждый уровень воина',
                '1к10 (или 6) + модификатор СИСТЕМА',
                'Огнестрельное оружие, Холодное оружие',
                'Система, Сила',
                'Огнестрельное оружие, Холодное оружие, Устойчивость(скр), Устойчивость(имп)',
                '(а) штурмовая винтовка и 60 патронов или (б) дробовик и 20 патронов\n(а) тяжёлый пистолет и 30 патронов или (б) два лёгких пистолета и 40 патронов\n(а) бронежилет или (б) тактическая броня\nБоевой нож, аптечка, 100 еврдолларов',
                '''Стрелок: +2 к броскам урона огнестрельным оружием
Два ствола: Когда вы атакуете двумя пистолетами, можете добавить модификатор характеристики к урону второй атаки
Тяжёлое вооружение: Вы можете перебрасывать 1 и 2 на костях урона от тяжёлого оружия (дробовик, штурмовая винтовка, пулемёт)
Рукопашник: Ваши удары без оружия и атаки холодным оружием наносят дополнительно +2 к урону
Оборонительный: Пока вы носите броню, вы получаете +1 к КБ''',
                '''Бонусное действие: Вы восстанавливаете хиты равные 1d10 + ваш уровень бойца. Использование: один раз, восстанавливается после короткого или длинного отдыха.'''
            ))
            class_id = cur.lastrowid
            conn.execute("INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                         (class_id, 'Боевой стиль',
                          'Вы освоили определённый подход к бою. Выберите один из вариантов выше.'))
            conn.execute("INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                         (class_id, 'Второе дыхание', 'Бонусное действие: восстанавливаете хиты 1d10 + уровень бойца.'))
        # Миграция: поля «Хиты на 1 уровне» и «Инструменты» (для уже созданных БД)
        existing_cols = {r['name'] for r in conn.execute("PRAGMA table_info(classes)")}
        for col in ('hp_first_level', 'tool_proficiencies'):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE classes ADD COLUMN {col} TEXT DEFAULT ''")
        # Миграция: публичность листа персонажа (0 — только владелец, 1 — виден в разделе «Персонажи»)
        sheet_cols = {r['name'] for r in conn.execute("PRAGMA table_info(character_sheets)")}
        if 'is_public' not in sheet_cols:
            conn.execute("ALTER TABLE character_sheets ADD COLUMN is_public INTEGER DEFAULT 0")
        conn.commit()


init_db()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Декораторы
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в аккаунт.', 'danger')
            return redirect(url_for('account'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите.', 'danger')
            return redirect(url_for('account'))
        with get_db() as conn:
            user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            if not user or user['is_admin'] != 1:
                flash('Доступ запрещён. Требуются права администратора.', 'danger')
                return redirect(url_for('account'))
        return f(*args, **kwargs)

    return decorated_function


# Маршруты
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/account', methods=['GET', 'POST'])
def account():
    if 'user_id' in session:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            if not user:
                session.clear()
                flash('Сессия устарела, войдите снова.', 'danger')
                return redirect(url_for('account'))
        if request.method == 'POST' and 'change_password' in request.form:
            current = request.form.get('current_password')
            new_pass = request.form.get('new_password')
            confirm = request.form.get('confirm_password')
            if not check_password_hash(user['password_hash'], current):
                flash('Неверный текущий пароль.', 'danger')
            elif new_pass != confirm:
                flash('Новый пароль и подтверждение не совпадают.', 'danger')
            elif len(new_pass) < 4:
                flash('Пароль должен содержать минимум 4 символа.', 'danger')
            else:
                new_hash = generate_password_hash(new_pass)
                with get_db() as conn:
                    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
                flash('Пароль успешно изменён.', 'success')
            return redirect(url_for('account'))
        if request.method == 'POST' and 'change_avatar' in request.form:
            file = request.files.get('avatar')
            if file and allowed_file(file.filename):
                filename = secure_filename(f"user_{user['id']}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                avatar_path = f"uploads/avatars/{filename}"
                with get_db() as conn:
                    conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_path, user['id']))
                flash('Аватарка обновлена!', 'success')
            else:
                flash('Недопустимый формат файла.', 'danger')
            return redirect(url_for('account'))
        is_admin = user['is_admin'] == 1
        return render_template('account.html', user=user, is_admin=is_admin, active_tab='profile')
    return render_template('account.html', active_tab='login')


@app.route('/login', methods=['POST'])
def login():
    identifier = request.form.get('login_identifier')
    password = request.form.get('password')
    if not identifier or not password:
        flash('Заполните все поля.', 'danger')
        return redirect(url_for('account'))
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ? OR username = ?", (identifier, identifier)).fetchone()
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['is_admin'] = user['is_admin']
        flash(f'Добро пожаловать, {user["username"]}!', 'success')
    else:
        flash('Неверный email/имя или пароль.', 'danger')
    return redirect(url_for('account'))


@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')
    avatar = request.files.get('avatar')
    if not all([username, email, password, confirm]):
        flash('Заполните все поля.', 'danger')
        return redirect(url_for('account'))
    if password != confirm:
        flash('Пароли не совпадают.', 'danger')
        return redirect(url_for('account'))
    if len(password) < 4:
        flash('Пароль должен быть не короче 4 символов.', 'danger')
        return redirect(url_for('account'))
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = ? OR username = ?", (email, username)).fetchone()
        if existing:
            flash('Пользователь с таким email или именем уже существует.', 'danger')
            return redirect(url_for('account'))
    avatar_path = 'uploads/avatars/default.png'
    if avatar and allowed_file(avatar.filename):
        filename = secure_filename(f"{username}_{avatar.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        avatar.save(file_path)
        avatar_path = f"uploads/avatars/{filename}"
    password_hash = generate_password_hash(password)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, avatar) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, avatar_path)
        )
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        session['user_id'] = user['id']
        session['is_admin'] = user['is_admin']
    flash('Регистрация успешна!', 'success')
    return redirect(url_for('account'))


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из аккаунта.', 'info')
    return redirect(url_for('account'))


# Админ-панель
@app.route('/admin')
@admin_required
def admin_panel():
    with get_db() as conn:
        users = conn.execute("SELECT id, username, email, is_admin FROM users ORDER BY id").fetchall()
    return render_template('admin.html', users=users)


@app.route('/admin/toggle_admin/<int:user_id>')
@admin_required
def toggle_admin(user_id):
    if user_id == session['user_id']:
        flash('Нельзя изменить свой статус.', 'danger')
        return redirect(url_for('admin_panel'))
    with get_db() as conn:
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            new_status = 0 if user['is_admin'] else 1
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, user_id))
            flash('Статус изменён.', 'success')
    return redirect(url_for('admin_panel'))


# Управление классами
@app.route('/classes')
def show_classes():
    with get_db() as conn:
        classes = conn.execute("SELECT * FROM classes ORDER BY id").fetchall()
        classes_with_features = []
        for cls in classes:
            features = conn.execute("SELECT feature_name, feature_description FROM class_features WHERE class_id = ?",
                                    (cls['id'],)).fetchall()
            classes_with_features.append({'class': cls, 'features': features})
    return render_template('classes.html', classes=classes_with_features)


@app.route('/admin/add_class', methods=['GET', 'POST'])
@admin_required
def add_class():
    if request.method == 'POST':
        name = request.form['name'].strip()
        # Проверка уникальности
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM classes WHERE name = ?", (name,)).fetchone()
            if existing:
                flash('Класс с таким названием уже существует!', 'danger')
                return render_template('add_class.html')

        hit_dice = request.form['hit_dice']
        hp_next_level = request.form['hp_next_level']
        weapon_profs = request.form['weapon_proficiencies']
        save_profs = request.form['save_proficiencies']
        skill_profs = request.form['skill_proficiencies']
        equipment = request.form['equipment']
        fighting_style = request.form.get('fighting_style_choice', '')
        second_wind = request.form.get('second_wind', '')

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO classes (name, hit_dice, hp_first_level, hp_next_level, weapon_proficiencies, tool_proficiencies, save_proficiencies, skill_proficiencies, equipment, fighting_style_choice, second_wind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, hit_dice, request.form.get('hp_first_level', ''), hp_next_level, weapon_profs,
                  request.form.get('tool_proficiencies', ''), save_profs, skill_profs, equipment, fighting_style,
                  second_wind))
            class_id = cur.lastrowid
            feature_names = request.form.getlist('feature_name[]')
            feature_descs = request.form.getlist('feature_description[]')
            for fn, fd in zip(feature_names, feature_descs):
                if fn.strip():
                    conn.execute(
                        "INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                        (class_id, fn, fd))
            conn.commit()
        flash(f'Класс "{name}" успешно добавлен!', 'success')
        return redirect(url_for('show_classes'))
    return render_template('add_class.html')


# Управление предысториями
@app.route('/backgrounds')
def show_backgrounds():
    with get_db() as conn:
        bgs = conn.execute("SELECT * FROM backgrounds ORDER BY id").fetchall()
        bgs_with_groups = []
        for bg in bgs:
            groups = conn.execute(
                "SELECT group_title, options_json FROM background_choice_groups WHERE background_id = ?",
                (bg['id'],)).fetchall()
            parsed = []
            for g in groups:
                try:
                    options = json.loads(g['options_json'])
                except (TypeError, ValueError):
                    options = []
                parsed.append({'group_title': g['group_title'], 'options': options})
            bgs_with_groups.append({'background': bg, 'choice_groups': parsed})
    return render_template('backgrounds.html', backgrounds=bgs_with_groups)


@app.route('/admin/add_background', methods=['GET', 'POST'])
@admin_required
def add_background():
    if request.method == 'POST':
        name = request.form['name'].strip()
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM backgrounds WHERE name = ?", (name,)).fetchone()
            if existing:
                flash('Предыстория с таким названием уже существует!', 'danger')
                return render_template('add_background.html')

        description = request.form['description']
        skill_profs = request.form['skill_proficiencies']
        equipment = request.form['equipment']
        languages = request.form.get('languages', '')
        feature_name = request.form['feature_name']
        feature_desc = request.form['feature_description']

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO backgrounds (name, description, skill_profs, equipment, languages, feature_name, feature_description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, description, skill_profs, equipment, languages, feature_name, feature_desc))
            bg_id = cur.lastrowid
            group_titles = request.form.getlist('group_title[]')
            group_options = request.form.getlist('group_options[]')
            for title, opts_str in zip(group_titles, group_options):
                if title.strip() and opts_str.strip():
                    options_list = []
                    for line in opts_str.strip().split('\n'):
                        if ':' in line:
                            parts = line.split(':', 1)
                            opt_name = parts[0].strip()
                            opt_bonus = parts[1].strip()
                            options_list.append({'name': opt_name, 'bonus': opt_bonus})
                    if options_list:
                        conn.execute(
                            "INSERT INTO background_choice_groups (background_id, group_title, options_json) VALUES (?, ?, ?)",
                            (bg_id, title, json.dumps(options_list, ensure_ascii=False)))
            conn.commit()
        flash(f'Предыстория "{name}" добавлена!', 'success')
        return redirect(url_for('show_backgrounds'))
    return render_template('add_background.html')


@app.route('/sheets')
@login_required
def sheets_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, sheet_data, updated_at, is_public FROM character_sheets WHERE user_id = ? ORDER BY updated_at DESC",
            (session['user_id'],)
        ).fetchall()

    sheets = []
    for row in rows:
        data = json.loads(row['sheet_data'])
        sheets.append({
            'id': row['id'],
            'name': data.get('name', 'Без имени'),
            'class': data.get('class', 'Не указан'),
            'level': data.get('level', 1),
            'updated': row['updated_at'],
            'is_public': bool(row['is_public'])
        })
    return render_template('sheets_list.html', sheets=sheets)


# Визитка персонажа: шесть характеристик в виде кольца из шестиугольников (+ уровень в центре)
HEX_STATS = [('strength', 'СИЛ'), ('system', 'Т.СИС'), ('dexterity', 'ЛОВ'),
             ('wisdom', 'МУД'), ('charisma', 'ХАР'), ('intelligence', 'ИНТ')]


def hex_points(cx, cy, r):
    k = 0.8660254
    pts = [(0, -1), (k, -.5), (k, .5), (0, 1), (-k, .5), (-k, -.5)]
    return ' '.join(f'{cx + r * x:.1f},{cy + r * y:.1f}' for x, y in pts)


def hex_ring(stats, level):
    r, d, k = 23, 43, 0.8660254
    positions = [(-.5 * d, -k * d), (.5 * d, -k * d), (d, 0), (.5 * d, k * d), (-.5 * d, k * d), (-d, 0)]
    cells = []
    for (key, label), (x, y) in zip(HEX_STATS, positions):
        try:
            value = int(stats.get(key, 10))
        except (TypeError, ValueError):
            value = 10
        strength = max(.0, min(1., (value - 6) / 12))   # чем выше значение, тем ярче ячейка
        cells.append({'points': hex_points(x, y, r), 'x': round(x, 1), 'y': round(y, 1), 'value': value,
                      'label': label, 'alpha': round(.14 + .82 * strength, 2), 'light': strength > .5})
    return {'cells': cells, 'center': {'points': hex_points(0, 0, r * .72), 'level': level}}


# Раздел «Персонажи»: публичные листы всех игроков, только просмотр
@app.route('/characters')
def characters_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT cs.id, cs.sheet_data, cs.updated_at, u.username, u.avatar "
            "FROM character_sheets cs JOIN users u ON u.id = cs.user_id "
            "WHERE cs.is_public = 1 ORDER BY cs.updated_at DESC"
        ).fetchall()
    characters = []
    for row in rows:
        data = json.loads(row['sheet_data'])
        characters.append({
            'id': row['id'],
            'name': data.get('name') or 'Без имени',
            'class': data.get('class') or '—',
            'background': data.get('background') or '',
            'level': data.get('level', 1),
            'updated': row['updated_at'],
            'owner': row['username'],
            'avatar': row['avatar'],
            'photo': data.get('photo') or '',
            'ac': data.get('armor_class', 10),
            'hp': data.get('hp_max', 0),
            'speed': data.get('speed', 30),
            'hexes': hex_ring(data.get('stats') or {}, data.get('level', 1)),
        })
    return render_template('characters.html', characters=characters)


@app.route('/characters/<int:sheet_id>')
def character_view(sheet_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT cs.id, cs.user_id, cs.sheet_data, cs.is_public, cs.updated_at, u.username, u.avatar "
            "FROM character_sheets cs JOIN users u ON u.id = cs.user_id WHERE cs.id = ?",
            (sheet_id,)
        ).fetchone()
    if not row or not row['is_public']:
        flash('Этот лист не найден или закрыт владельцем.', 'danger')
        return redirect(url_for('characters_list'))
    if session.get('user_id') == row['user_id']:
        return redirect(url_for('sheet_edit', sheet_id=sheet_id))
    owner = {'username': row['username'], 'avatar': row['avatar'], 'updated': row['updated_at']}
    return render_template('sheet_edit.html', sheet_id=sheet_id, sheet=json.loads(row['sheet_data']),
                           readonly=True, owner=owner, is_public=True)

@app.route('/sheet/new', methods=['GET', 'POST'])
@login_required
def new_sheet():
    if request.method == 'POST':
        name = request.form.get('name', 'Персонаж')
        empty_sheet = {
            'name': name,
            'class': '',
            'background': '',
            'level': 1,
            'race': '',
            'alignment': '',
            'photo': '',
            'stats': {
                'strength': 10,
                'system': 10,
                'dexterity': 10,
                'wisdom': 10,
                'charisma': 10,
                'intelligence': 10
            },
            'hp_max': 0,
            'hp_current': 0,
            'hit_dice': '',
            'armor_class': 10,
            'speed': 30,
            'initiative': 0,
            'proficiency_bonus': 2,
            'skills': [
                {'name': 'Эго', 'stat': 'charisma', 'proficient': False, 'expertise': False},
                {'name': 'Присутствие', 'stat': 'charisma', 'proficient': False, 'expertise': False},
                {'name': 'Соц. рейтинг', 'stat': 'charisma', 'proficient': False, 'expertise': False},
                {'name': 'Проворство', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Реакция', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Скрытность', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Внимательность', 'stat': 'wisdom', 'proficient': False, 'expertise': False},
                {'name': 'Хладнокровие', 'stat': 'wisdom', 'proficient': False, 'expertise': False},
                {'name': 'Техника', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Медицина', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Наука', 'stat': 'wisdom', 'proficient': False, 'expertise': False},
                {'name': 'Огнестрел. оружие', 'stat': 'strength', 'proficient': False, 'expertise': False},
                {'name': 'Холодное оружие', 'stat': 'strength', 'proficient': False, 'expertise': False},
                {'name': 'Устойчивость(имп)', 'stat': 'system', 'proficient': False, 'expertise': False},
                {'name': 'Устойчивость(скр)', 'stat': 'system', 'proficient': False, 'expertise': False}
            ],
            'languages': '',
            'features': '',
            'equipment': '',
            'notes': ''
        }
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO character_sheets (user_id, name, sheet_data, is_public) VALUES (?, ?, ?, ?)",
                (session['user_id'], name, json.dumps(empty_sheet), 1 if request.form.get('is_public') else 0)
            )
            sheet_id = cur.lastrowid
        return redirect(url_for('sheet_edit', sheet_id=sheet_id))
    return render_template('sheet_new.html')


def _to_level(value):
    try:
        return max(1, min(20, int(value)))
    except (TypeError, ValueError):
        return 1


@app.route('/sheet/<int:sheet_id>', methods=['GET', 'POST'])
@login_required
def sheet_edit(sheet_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, sheet_data, is_public FROM character_sheets WHERE id = ? AND user_id = ?",
            (sheet_id, session['user_id'])
        ).fetchone()
        if not row:
            flash('Лист не найден.', 'danger')
            return redirect(url_for('sheets_list'))

    sheet = json.loads(row['sheet_data'])

    if request.method == 'POST':
        new_sheet = request.get_json()
        if new_sheet:
            # публичность хранится в отдельной колонке, а не в JSON листа
            is_public = 1 if new_sheet.pop('is_public', None) else 0
            # фото меняется только через /sheet/<id>/photo; значение из клиента не принимаем
            new_sheet['photo'] = sheet.get('photo', '')
            # форма присылает уровень строкой ("5"); храним числом, иначе на странице не выбирается нужный пункт
            new_sheet['level'] = _to_level(new_sheet.get('level'))
            with get_db() as conn:
                conn.execute(
                    "UPDATE character_sheets SET sheet_data = ?, is_public = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(new_sheet), is_public, sheet_id)
                )
            return {'status': 'ok'}
        else:
            flash('Не удалось сохранить.', 'danger')

    return render_template('sheet_edit.html', sheet_id=sheet_id, sheet=sheet, is_public=bool(row['is_public']))

@app.route('/sheet/<int:sheet_id>/delete', methods=['POST'])
@login_required
def delete_sheet(sheet_id):
    with get_db() as conn:
        sheet = conn.execute(
            "SELECT id, sheet_data FROM character_sheets WHERE id = ? AND user_id = ?",
            (sheet_id, session['user_id'])
        ).fetchone()
        if sheet:
            conn.execute("DELETE FROM character_sheets WHERE id = ?", (sheet_id,))
            try:
                remove_sheet_photo(json.loads(sheet['sheet_data']).get('photo', ''))
            except (ValueError, OSError):
                pass
            flash('Персонаж удалён.', 'success')
        else:
            flash('Ошибка: лист не найден.', 'danger')
    return redirect(url_for('sheets_list'))


# Фото персонажа: загрузка (POST, multipart, поле «photo») и удаление (DELETE). Только владелец листа.
@app.route('/sheet/<int:sheet_id>/photo', methods=['POST', 'DELETE'])
@login_required
def sheet_photo(sheet_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT sheet_data FROM character_sheets WHERE id = ? AND user_id = ?",
            (sheet_id, session['user_id'])
        ).fetchone()
    if not row:
        return {'status': 'error', 'message': 'Лист не найден.'}, 404
    sheet = json.loads(row['sheet_data'])
    old = sheet.get('photo', '')

    if request.method == 'DELETE':
        new = ''
    else:
        file = request.files.get('photo')
        if not file or not file.filename:
            return {'status': 'error', 'message': 'Файл не выбран.'}, 400
        data = file.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            return {'status': 'error', 'message': 'Файл слишком большой (максимум 6 МБ).'}, 413
        ext = detect_image_ext(data[:16])
        if not ext:
            return {'status': 'error', 'message': 'Поддерживаются только PNG, JPG, GIF и WEBP.'}, 415
        name = f"sheet_{sheet_id}_{secrets.token_hex(6)}.{ext}"
        with open(os.path.join(SHEET_PHOTO_DIR, name), 'wb') as out:
            out.write(data)
        new = SHEET_PHOTO_PREFIX + name

    sheet['photo'] = new
    with get_db() as conn:
        conn.execute(
            "UPDATE character_sheets SET sheet_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(sheet), sheet_id)
        )
    remove_sheet_photo(old)
    return {'status': 'ok', 'url': url_for('static', filename=new) if new else ''}


@app.errorhandler(413)
def too_large(_e):
    if request.path.endswith('/photo'):
        return {'status': 'error', 'message': 'Файл слишком большой (максимум 6 МБ).'}, 413
    flash('Файл слишком большой.', 'danger')
    return redirect(request.referrer or url_for('index'))

@app.route('/admin/delete_class/<int:class_id>')
@admin_required
def delete_class(class_id):
    with get_db() as conn:
        cls = conn.execute("SELECT id FROM classes WHERE id = ?", (class_id,)).fetchone()
        if cls:
            conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
            flash('Класс удалён.', 'success')
        else:
            flash('Класс не найден.', 'danger')
    return redirect(url_for('show_classes'))

@app.route('/admin/delete_background/<int:bg_id>')
@admin_required
def delete_background(bg_id):
    with get_db() as conn:
        bg = conn.execute("SELECT id FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if bg:
            conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
            flash('Предыстория удалена.', 'success')
        else:
            flash('Предыстория не найдена.', 'danger')
    return redirect(url_for('show_backgrounds'))


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')