import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask, request, render_template, redirect, session,
    send_from_directory, url_for, render_template_string
)

app = Flask(__name__)
app.secret_key = "change_me_please"

DB_PATH = "database.db"
REPORTS_DIR = "reports_files"
os.makedirs(REPORTS_DIR, exist_ok=True)

def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().isoformat()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,                -- student/cook/admin
            login TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            work TEXT NOT NULL,
            benefit TEXT,
            allergy TEXT,
            balance INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_date TEXT NOT NULL,
            name TEXT NOT NULL,
            meal_type TEXT NOT NULL,           -- breakfast/lunch/snack
            price INTEGER NOT NULL DEFAULT 0,
            kcal INTEGER NOT NULL DEFAULT 0,
            allergens TEXT,
            portions_total INTEGER NOT NULL DEFAULT 0,
            portions_available INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            meal_type TEXT NOT NULL,
            item TEXT NOT NULL,
            count INTEGER NOT NULL,
            comment TEXT,
            status TEXT NOT NULL DEFAULT 'new'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS serves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            meal_type TEXT NOT NULL,
            item TEXT NOT NULL,
            count INTEGER NOT NULL,
            pay_type TEXT NOT NULL,            -- subscription/balance/free
            amount INTEGER NOT NULL DEFAULT 0,
            comment TEXT,
            order_id INTEGER,
            staff_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS writeoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            item TEXT NOT NULL,
            count INTEGER NOT NULL,
            reason TEXT NOT NULL,
            comment TEXT,
            staff_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            meal_date TEXT,
            meal_type TEXT,
            item TEXT,
            rating INTEGER,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',  -- new/in_review/resolved/rejected
            answer TEXT,
            answered_ts TEXT,
            staff_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS procurement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            count INTEGER NOT NULL,
            price INTEGER NOT NULL,
            supplier TEXT NOT NULL,
            staff_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            title TEXT NOT NULL,
            text TEXT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            type TEXT NOT NULL,                -- topup/charge
            amount INTEGER NOT NULL,
            note TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            until_date TEXT NOT NULL,
            plan TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_notice(title: str, text: str, sender: str, recipient: str):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO notices (ts, title, text, sender, recipient) VALUES (?, ?, ?, ?, ?)",
        (now_ts(), title, text, sender, recipient),
    )
    conn.commit()
    conn.close()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return user


def login_required(fn):
    @wraps(fn)
    def w(*args, **kwargs):
        if not current_user():
            return redirect("/login")
        return fn(*args, **kwargs)
    return w


def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def w(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect("/login")
            if u["role"] not in roles:
                return render_template("dashboard.html", user=u, error="Недостаточно прав.")
            return fn(*args, **kwargs)
        return w
    return deco


def seed_if_empty():
    conn = get_db_connection()
    cur = conn.cursor()

    has_users = cur.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if has_users == 0:
        cur.execute(
            "INSERT INTO users(role, login, password, name, work, balance) VALUES(?,?,?,?,?,?)",
            ("admin", "admin", "admin", "Администратор", "завуч", 0)
        )
        cur.execute(
            "INSERT INTO users(role, login, password, name, work, balance) VALUES(?,?,?,?,?,?)",
            ("cook", "cook", "cook", "Повар", "столовая", 0)
        )
        cur.execute(
            "INSERT INTO users(role, login, password, name, work, balance) VALUES(?,?,?,?,?,?)",
            ("student", "student", "student", "Ученик", "7Б", 500)
        )
        conn.commit()

    need = {
        "admin": ("admin", "admin", "Администратор", "завуч", 0),
        "cook": ("cook", "cook", "Повар", "столовая", 0),
        "student": ("student", "student", "Ученик", "7Б", 500),
    }
    for role, (login, password, name, work, balance) in need.items():
        exists = cur.execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()
        if not exists:
            cur.execute(
                "INSERT INTO users(role, login, password, name, work, balance) VALUES(?,?,?,?,?,?)",
                (role, login, password, name, work, balance)
            )
            conn.commit()

    has_menu_today = cur.execute(
        "SELECT COUNT(*) AS c FROM menu_items WHERE menu_date = ?",
        (today_str(),)
    ).fetchone()["c"]

    if has_menu_today == 0:
        items = [
            ("Каша овсяная", "завтрак", 80, 250, "молоко", 30),
            ("Суп куриный", "обед", 120, 300, "", 40),
            ("Котлета с гречкой", "обед", 180, 520, "глютен", 35),
            ("Компот", "обед", 40, 120, "", 50),
            ("Булочка", "закуска", 60, 280, "глютен", 25),
        ]
        for name, meal_type, price, kcal, allergens, portions in items:
            cur.execute("""
                INSERT INTO menu_items(menu_date, name, meal_type, price, kcal, allergens, portions_total, portions_available)
                VALUES(?,?,?,?,?,?,?,?)
            """, (today_str(), name, meal_type, price, kcal, allergens or None, portions, portions))
        conn.commit()

    conn.close()


def get_active_subscription(conn, student_id: int):
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE student_id = ? ORDER BY until_date DESC LIMIT 1",
        (student_id,)
    ).fetchone()
    if not row:
        return None
    try:
        until = date.fromisoformat(row["until_date"])
    except Exception:
        return None
    if until < date.today():
        return None
    return row

ORDER_STATUS_RU = {
    "new": "Новая",
    "approved": "Принята",
    "rejected": "Отклонена",
    "served": "Выдано",
}
COMPLAINT_STATUS_RU = {
    "new": "Новая",
    "in_review": "На рассмотрении",
    "resolved": "Решена",
    "rejected": "Отклонена",
}
MEAL_RU = {"breakfast": "Завтрак", "lunch": "Обед", "snack": "Полдник"}


init_db()
seed_if_empty()

@app.route("/")
def root():
    return redirect("/dashboard" if current_user() else "/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_ = request.form.get("login", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db_connection()
        u = conn.execute("SELECT * FROM users WHERE login = ?", (login_,)).fetchone()
        conn.close()

        if not u or u["password"] != password:
            return render_template("login.html", error="Неверный логин или пароль.")
        session["user_id"] = u["id"]
        return redirect("/dashboard")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/register", methods=["GET", "POST"])
def register():
    role = request.args.get("role", "student").strip().lower()
    if role not in {"student", "cook", "admin"}:
        role = "student"

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        login_ = request.form.get("login", "").strip()
        work = request.form.get("work", "").strip()
        p1 = request.form.get("password1", "").strip()
        p2 = request.form.get("password2", "").strip()
        code = request.form.get("code", "").strip()

        if not all([name, login_, work, p1, p2]):
            return render_template("register.html", error="Заполните все поля.")
        if p1 != p2:
            return render_template("register.html", error="Пароли не совпадают.")

        codes = {"student": "1111", "cook": "2222", "admin": "1234"}
        if code and code != codes[role]:
            return render_template("register.html", error="Неверный код регистрации.")

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users(role, login, password, name, work) VALUES(?,?,?,?,?)",
                (role, login_, p1, name, work)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("register.html", error="Такой логин уже занят.")
        conn.close()

        add_notice("Новый пользователь", f"{name} ({role}), {work}", "Система", "admin")
        return redirect("/login")

    return render_template("register.html")


@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    conn = get_db_connection()

    menu_today = conn.execute(
        "SELECT COUNT(*) AS c FROM menu_items WHERE menu_date = ?",
        (today_str(),)
    ).fetchone()["c"]

    serves_today = conn.execute(
        "SELECT IFNULL(SUM(count),0) AS c FROM serves WHERE substr(ts,1,10)=?",
        (today_str(),)
    ).fetchone()["c"]

    writeoff_today = conn.execute(
        "SELECT IFNULL(SUM(count),0) AS c FROM writeoffs WHERE substr(ts,1,10)=?",
        (today_str(),)
    ).fetchone()["c"]

    orders_new = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='new'").fetchone()["c"]
    orders_approved = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='approved'").fetchone()["c"]

    notices = conn.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 8").fetchall()

    top_stock_rows = conn.execute("""
        SELECT name, SUM(portions_available) AS available
        FROM menu_items
        WHERE menu_date = ?
        GROUP BY name
        ORDER BY available DESC
        LIMIT 6
    """, (today_str(),)).fetchall()

    balance = None
    subscription = None
    if u["role"] == "student":
        balance = u["balance"]
        sub = get_active_subscription(conn, u["id"])
        if sub:
            until = date.fromisoformat(sub["until_date"])
            subscription = {"until": sub["until_date"], "days_left": (until - date.today()).days}

    conn.close()

    stats = {
        "menu_today": int(menu_today),
        "serves_today": int(serves_today),
        "writeoff_today": int(writeoff_today),
        "orders_new": int(orders_new),
        "orders_approved": int(orders_approved),
    }

    feed = [{
        "ts": n["ts"],
        "title": n["title"],
        "text": n["text"],
        "sender": n["sender"],
        "recipient": n["recipient"],
    } for n in notices]

    top_stock = [{"name": r["name"], "available": int(r["available"] or 0)} for r in top_stock_rows]

    return render_template(
        "dashboard.html",
        user=u,
        stats=stats,
        feed=feed,
        top_stock=top_stock,
        balance=balance,
        subscription=subscription
    )

@app.route("/menu", methods=["GET", "POST"])
@login_required
def menu():
    u = current_user()
    conn = get_db_connection()

    if request.method == "POST":
        if u["role"] not in ("cook", "admin"):
            conn.close()
            return render_template("menu.html", user=u, error="Только повар/админ может менять меню.")

        name = request.form.get("name", "").strip()
        meal_type = request.form.get("meal_type", "lunch").strip()
        price = int(request.form.get("price", "0") or 0)
        kcal = int(request.form.get("kcal", "0") or 0)
        portions = int(request.form.get("portions", "0") or 0)
        allergens = request.form.get("allergens", "").strip() or None

        if not name:
            conn.close()
            return render_template("menu.html", user=u, error="Название блюда обязательно.")

        conn.execute("""
            INSERT INTO menu_items(menu_date, name, meal_type, price, kcal, allergens, portions_total, portions_available)
            VALUES(?,?,?,?,?,?,?,?)
        """, (today_str(), name, meal_type, max(price, 0), max(kcal, 0), allergens, max(portions, 0), max(portions, 0)))
        conn.commit()
        add_notice("Меню обновлено", f"Добавлено: {name} ({MEAL_RU.get(meal_type, meal_type)}), порций: {portions}", u["name"], "admin")

    rows = conn.execute(
        "SELECT * FROM menu_items WHERE menu_date = ? ORDER BY meal_type, name",
        (today_str(),)
    ).fetchall()
    conn.close()

    menu_items = [{
        "name": r["name"],
        "meal_type": r["meal_type"],
        "meal_ru": MEAL_RU.get(r["meal_type"], r["meal_type"]),
        "price": r["price"],
        "kcal": r["kcal"],
        "allergens": r["allergens"],
        "available": r["portions_available"],
    } for r in rows]

    return render_template("menu.html", user=u, menu_items=menu_items)


@app.route("/menu/history")
@login_required
def menu_history():
    u = current_user()
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM menu_items ORDER BY menu_date DESC, meal_type, name LIMIT 200"
    ).fetchall()
    conn.close()

    menu_items = [{
        "name": f"{r['name']} (дата: {r['menu_date']})",
        "meal_type": r["meal_type"],
        "meal_ru": MEAL_RU.get(r["meal_type"], r["meal_type"]),
        "price": r["price"],
        "kcal": r["kcal"],
        "allergens": r["allergens"],
        "available": r["portions_available"],
    } for r in rows]

    return render_template("menu.html", user=u, menu_items=menu_items, message="История меню (последние записи).")

@app.route("/availability")
@login_required
def availability():
    u = current_user()
    conn = get_db_connection()

    served = conn.execute("""
        SELECT item, SUM(count) AS c
        FROM serves
        WHERE substr(ts,1,10) = ?
        GROUP BY item
    """, (today_str(),)).fetchall()
    served_map = {r["item"]: int(r["c"] or 0) for r in served}

    woff = conn.execute("""
        SELECT item, SUM(count) AS c
        FROM writeoffs
        WHERE substr(ts,1,10) = ?
        GROUP BY item
    """, (today_str(),)).fetchall()
    woff_map = {r["item"]: int(r["c"] or 0) for r in woff}

    menu_rows = conn.execute("""
        SELECT name, SUM(portions_available) AS available
        FROM menu_items
        WHERE menu_date = ?
        GROUP BY name
        ORDER BY name
    """, (today_str(),)).fetchall()
    conn.close()

    stock = []
    for r in menu_rows:
        nm = r["name"]
        stock.append({
            "name": nm,
            "available": int(r["available"] or 0),
            "served": int(served_map.get(nm, 0)),
            "writeoff": int(woff_map.get(nm, 0)),
        })

    return render_template("availability.html", user=u, stock=stock)
@app.route("/orders")
@login_required
def orders():
    u = current_user()
    conn = get_db_connection()

    if u["role"] in ("cook", "admin"):
        rows = conn.execute("""
            SELECT o.*, us.name AS student_name
            FROM orders o
            JOIN users us ON us.id = o.student_id
            ORDER BY o.id DESC
            LIMIT 200
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT o.*, us.name AS student_name
            FROM orders o
            JOIN users us ON us.id = o.student_id
            WHERE o.student_id = ?
            ORDER BY o.id DESC
            LIMIT 200
        """, (u["id"],)).fetchall()

    conn.close()

    orders_list = [{
        "id": r["id"],
        "student": r["student_name"],
        "status": r["status"],
        "status_ru": ORDER_STATUS_RU.get(r["status"], r["status"]),
        "meal_type": r["meal_type"],
        "meal_ru": MEAL_RU.get(r["meal_type"], r["meal_type"]),
        "item": r["item"],
        "count": r["count"],
        "comment": r["comment"],
    } for r in rows]

    return render_template("orders.html", user=u, orders=orders_list)


@app.route("/orders/create", methods=["POST"])
@login_required
def orders_create():
    u = current_user()
    meal_type = request.form.get("meal_type", "lunch").strip()
    item = request.form.get("item", "").strip()
    count = int(request.form.get("count", "1") or 1)
    comment = request.form.get("comment", "").strip() or None

    if not item or count <= 0:
        return redirect("/orders")

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO orders(ts, student_id, meal_type, item, count, comment, status)
        VALUES(?,?,?,?,?,?, 'new')
    """, (now_ts(), u["id"], meal_type, item, count, comment))
    conn.commit()
    conn.close()

    add_notice("Новая заявка", f"{u['name']} запросил: {item} x{count} ({MEAL_RU.get(meal_type, meal_type)})", u["name"], "admin")
    return redirect("/orders")


@app.route("/orders/<int:oid>/approve")
@role_required("cook", "admin")
def orders_approve(oid: int):
    u = current_user()
    conn = get_db_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if not order:
        conn.close()
        return redirect("/orders")

    conn.execute("UPDATE orders SET status='approved' WHERE id = ?", (oid,))
    student = conn.execute("SELECT * FROM users WHERE id = ?", (order["student_id"],)).fetchone()
    conn.commit()
    conn.close()

    if student:
        add_notice("Заявка принята", f"Заявка #{oid} принята: {order['item']} x{order['count']}", u["name"], student["login"])
    return redirect("/orders")


@app.route("/orders/<int:oid>/reject")
@role_required("cook", "admin")
def orders_reject(oid: int):
    u = current_user()
    conn = get_db_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if not order:
        conn.close()
        return redirect("/orders")

    conn.execute("UPDATE orders SET status='rejected' WHERE id = ?", (oid,))
    student = conn.execute("SELECT * FROM users WHERE id = ?", (order["student_id"],)).fetchone()
    conn.commit()
    conn.close()

    if student:
        add_notice("Заявка отклонена", f"Заявка #{oid} отклонена: {order['item']} x{order['count']}", u["name"], student["login"])
    return redirect("/orders")


@app.route("/payments")
@login_required
def payments():
    u = current_user()
    student_id = u["id"]

    if u["role"] == "admin":
        sid = request.args.get("student_id")
        if sid and sid.isdigit():
            student_id = int(sid)

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM users WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        session.clear()
        return redirect("/login")

    tx = conn.execute(
        "SELECT * FROM transactions WHERE student_id=? ORDER BY id DESC LIMIT 200",
        (student_id,)
    ).fetchall()
    conn.close()

    transactions = [{"ts": r["ts"], "type": r["type"], "amount": r["amount"], "note": r["note"]} for r in tx]
    return render_template("payments.html", user=u, balance=student["balance"], transactions=transactions)


@app.route("/payments/topup", methods=["POST"])
@login_required
def payments_topup():
    u = current_user()
    amount = int(request.form.get("amount", "0") or 0)
    method = request.form.get("method", "cash").strip()

    if amount <= 0:
        return redirect("/payments")

    student_id = u["id"]
    if u["role"] == "admin":
        sid = request.args.get("student_id")
        if sid and sid.isdigit():
            student_id = int(sid)

    conn = get_db_connection()
    student = conn.execute("SELECT id FROM users WHERE id=?", (student_id,)).fetchone()
    if not student:
        conn.close()
        return redirect("/payments")

    conn.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, student_id))
    conn.execute(
        "INSERT INTO transactions(ts, student_id, type, amount, note) VALUES(?,?,?,?,?)",
        (now_ts(), student_id, "topup", amount, f"Пополнение ({method})")
    )
    conn.commit()
    conn.close()

    add_notice("Баланс пополнен", f"+{amount}₽ ({method})", "Система", "admin")
    return redirect("/payments")


@app.route("/payments/export")
@login_required
def payments_export():
    return redirect("/payments")

@app.route("/payment", endpoint="payment_alias")
@login_required
def payment_alias():
    return redirect("/payments")


@app.route("/pay", endpoint="pay_alias")
@login_required
def pay_alias():
    return redirect("/payments")
@app.route("/subscriptions")
@login_required
def subscriptions():
    u = current_user()
    student_id = u["id"]
    if u["role"] == "admin":
        sid = request.args.get("student_id")
        if sid and sid.isdigit():
            student_id = int(sid)

    conn = get_db_connection()
    sub = get_active_subscription(conn, student_id)
    conn.close()

    active_subscription = None
    if sub:
        until = date.fromisoformat(sub["until_date"])
        active_subscription = {"until": sub["until_date"], "days_left": (until - date.today()).days}

    return render_template("subscriptions.html", user=u, active_subscription=active_subscription)


@app.route("/subscriptions/buy", methods=["POST"])
@login_required
def subscriptions_buy():
    u = current_user()
    plan = request.form.get("plan", "month").strip()
    pay_from = request.form.get("pay_from", "balance").strip()

    prices = {"month": 2000, "quarter": 5500, "year": 18000}
    days = {"month": 30, "quarter": 90, "year": 365}
    cost = prices.get(plan, 2000)
    dur = days.get(plan, 30)

    student_id = u["id"]
    if u["role"] == "admin":
        sid = request.args.get("student_id")
        if sid and sid.isdigit():
            student_id = int(sid)

    conn = get_db_connection()
    student = conn.execute("SELECT * FROM users WHERE id=?", (student_id,)).fetchone()
    if not student:
        conn.close()
        return redirect("/subscriptions")

    if pay_from == "balance":
        if student["balance"] < cost:
            conn.close()
            return render_template("subscriptions.html", user=u, error="Недостаточно средств на балансе.")
        conn.execute("UPDATE users SET balance = balance - ? WHERE id=?", (cost, student_id))
        conn.execute(
            "INSERT INTO transactions(ts, student_id, type, amount, note) VALUES(?,?,?,?,?)",
            (now_ts(), student_id, "charge", -cost, f"Абонемент ({plan})")
        )

    start = date.today()
    last = conn.execute(
        "SELECT * FROM subscriptions WHERE student_id=? ORDER BY until_date DESC LIMIT 1",
        (student_id,)
    ).fetchone()
    if last:
        try:
            last_until = date.fromisoformat(last["until_date"])
            if last_until >= start:
                start = last_until + timedelta(days=1)
        except Exception:
            pass

    until = start + timedelta(days=dur)
    conn.execute(
        "INSERT INTO subscriptions(student_id, start_date, until_date, plan) VALUES(?,?,?,?)",
        (student_id, start.isoformat(), until.isoformat(), plan)
    )
    conn.commit()
    conn.close()

    add_notice("Абонемент оформлен", f"Тариф {plan} до {until.isoformat()}", "Система", "admin")
    return redirect("/subscriptions")

@app.route("/notifications")
@login_required
def notifications():
    u = current_user()
    conn = get_db_connection()

    if u["role"] == "admin":
        rows = conn.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 200").fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM notices
            WHERE recipient IN (?, 'all', 'students', 'cook', 'admin')
            ORDER BY id DESC LIMIT 200
        """, (u["login"],)).fetchall()

    conn.close()

    notices = [{
        "title": r["title"],
        "ts": r["ts"],
        "sender": r["sender"],
        "recipient": r["recipient"],
        "text": r["text"],
    } for r in rows]

    return render_template("notifications.html", user=u, notices=notices)


@app.route("/complaint", methods=["GET", "POST"])
@role_required("student")
def complaint():
    u = current_user()

    if request.method == "POST":
        meal_date = request.form.get("meal_date", "").strip() or None
        meal_type = request.form.get("meal_type", "").strip() or None
        item = request.form.get("item", "").strip() or None
        rating = request.form.get("rating", "").strip()
        text = request.form.get("text", "").strip()

        rating_val = None
        if rating:
            try:
                rating_val = int(rating)
            except Exception:
                rating_val = None
        if rating_val is not None and (rating_val < 1 or rating_val > 5):
            rating_val = None

        if not text:
            return render_template("complaint.html", user=u, error="Опишите проблему (текст обязателен).")

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO complaints(ts, student_id, meal_date, meal_type, item, rating, text, status)
            VALUES(?,?,?,?,?,?,?, 'new')
        """, (now_ts(), u["id"], meal_date, meal_type, item, rating_val, text))
        conn.commit()
        conn.close()

        add_notice("Жалоба", f"{u['name']} отправил жалобу по питанию", u["name"], "admin")
        return redirect("/complaints?mine=1")

    return render_template("complaint.html", user=u)


@app.route("/complaints")
@login_required
def complaints():
    u = current_user()
    show_all = request.args.get("all") == "1"
    mine = request.args.get("mine") == "1"

    conn = get_db_connection()

    if u["role"] in ("cook", "admin"):
        if show_all:
            rows = conn.execute("""
                SELECT c.*, us.name AS student_name
                FROM complaints c JOIN users us ON us.id=c.student_id
                ORDER BY c.id DESC LIMIT 300
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT c.*, us.name AS student_name
                FROM complaints c JOIN users us ON us.id=c.student_id
                WHERE c.status NOT IN ('resolved','rejected')
                ORDER BY c.id DESC LIMIT 300
            """).fetchall()
    else:
        rows = conn.execute("""
            SELECT c.*, us.name AS student_name
            FROM complaints c JOIN users us ON us.id=c.student_id
            WHERE c.student_id=?
            ORDER BY c.id DESC LIMIT 300
        """, (u["id"],)).fetchall()

    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "ts": r["ts"],
            "student": r["student_name"],
            "meal_date": r["meal_date"],
            "meal_type": r["meal_type"],
            "meal_ru": MEAL_RU.get(r["meal_type"], r["meal_type"]) if r["meal_type"] else None,
            "item": r["item"],
            "rating": r["rating"],
            "text": r["text"],
            "status": r["status"],
            "status_ru": COMPLAINT_STATUS_RU.get(r["status"], r["status"]),
            "answer": r["answer"],
            "answered_ts": r["answered_ts"],
        })

    return render_template("complaints.html", user=u, complaints=items, show_all=show_all, mine=mine)


@app.route("/complaints/<int:cid>/answer", methods=["POST"])
@role_required("cook", "admin")
def complaints_answer(cid: int):
    u = current_user()
    answer = request.form.get("answer", "").strip()
    action = request.form.get("action", "resolved").strip()

    if action not in ("resolved", "rejected", "in_review"):
        action = "resolved"

    conn = get_db_connection()
    row = conn.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return redirect("/complaints")

    conn.execute("""
        UPDATE complaints
        SET status=?, answer=?, answered_ts=?, staff_id=?
        WHERE id=?
    """, (action, answer or None, now_ts(), u["id"], cid))
    student = conn.execute("SELECT * FROM users WHERE id=?", (row["student_id"],)).fetchone()
    conn.commit()
    conn.close()

    if student:
        add_notice("Ответ по жалобе", "По вашей жалобе был дан ответ (см. раздел 'Жалобы').", u["name"], student["login"])

    return redirect("/complaints")


@app.route("/procurement", methods=["GET", "POST"])
@role_required("cook", "admin")
def procurement():
    u = current_user()
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form.get("itemName", "").strip()
        category = request.form.get("itemCategory", "").strip()
        price = int(request.form.get("price", "0") or 0)
        count = int(request.form.get("count", "0") or 0)
        supplier = request.form.get("supplier", "").strip()

        if not all([name, category, supplier]) or price <= 0 or count <= 0:
            conn.close()
            return render_template("procurement.html", user=u, error="Некорректные данные закупки.")

        conn.execute("""
            INSERT INTO procurement(ts, name, category, count, price, supplier, staff_id)
            VALUES(?,?,?,?,?,?,?)
        """, (now_ts(), name, category, count, price, supplier, u["id"]))
        conn.commit()
        add_notice("Закупки", f"Добавлено: {name} ({category}) x{count} по {price}₽ — {supplier}", u["name"], "admin")

    rows = conn.execute("SELECT * FROM procurement ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()

    plans = [{"id": r["id"], "name": r["name"], "category": r["category"], "count": r["count"],
              "price": r["price"], "supplier": r["supplier"]} for r in rows]

    return render_template("procurement.html", user=u, plans=plans)

@app.route("/reports")
@role_required("admin")
def reports():
    u = current_user()
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()

    reports_list = [{"id": r["id"], "title": r["title"]} for r in rows]
    return render_template("reports.html", user=u, reports=reports_list)


@app.route("/reports/create")
@role_required("admin")
def reports_create():
    u = current_user()
    conn = get_db_connection()

    menu_count = conn.execute("SELECT COUNT(*) AS c FROM menu_items WHERE menu_date=?", (today_str(),)).fetchone()["c"]
    orders_new = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='new'").fetchone()["c"]
    serves_today = conn.execute("SELECT IFNULL(SUM(count),0) AS c FROM serves WHERE substr(ts,1,10)=?", (today_str(),)).fetchone()["c"]
    writeoff_today = conn.execute("SELECT IFNULL(SUM(count),0) AS c FROM writeoffs WHERE substr(ts,1,10)=?", (today_str(),)).fetchone()["c"]
    proc_count = conn.execute("SELECT COUNT(*) AS c FROM procurement").fetchone()["c"]

    next_id = conn.execute("SELECT IFNULL(MAX(id),0)+1 AS nxt FROM reports").fetchone()["nxt"]
    title = f"Отчёт #{next_id} — {today_str()}"
    filename = f"report_{next_id}.txt"
    path = os.path.join(REPORTS_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write("=== Система управления столовой ===\n")
        f.write(f"Дата формирования: {now_ts()}\n")
        f.write(f"Создатель: {u['name']} (admin)\n\n")
        f.write("Сводка:\n")
        f.write(f"- Позиции меню на сегодня: {menu_count}\n")
        f.write(f"- Новые заявки: {orders_new}\n")
        f.write(f"- Выдано сегодня (порций): {serves_today}\n")
        f.write(f"- Списано сегодня (порций): {writeoff_today}\n")
        f.write(f"- Позиции в закупках: {proc_count}\n")
        f.write("\nКонец отчёта.\n")

    conn.execute("INSERT INTO reports(ts, title, filename) VALUES(?,?,?)", (now_ts(), title, filename))
    conn.commit()
    conn.close()

    add_notice("Отчёт сформирован", title, u["name"], "admin")
    return redirect("/reports")


@app.route("/reports/<int:rid>/download")
@role_required("admin")
def reports_download(rid: int):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not row:
        return redirect("/reports")
    return send_from_directory(REPORTS_DIR, row["filename"], as_attachment=True)


def _stub_page(title: str, text: str):
    u = current_user()
    return render_template_string(
        """
        {% extends "base.html" %}
        {% block title %}{{ title }}{% endblock %}
        {% block content %}
          <div class="card shadow-soft p-4">
            <h3 class="mb-2">{{ title }}</h3>
            <div class="text-muted">{{ text }}</div>
          </div>
        {% endblock %}
        """,
        user=u, title=title, text=text
    )

@app.route("/serve", methods=["GET", "POST"], endpoint="serve")
@role_required("cook", "admin")
def serve():
    u = current_user()
    conn = get_db_connection()
    error = None
    message = None

    students = conn.execute("SELECT id, name, work FROM users WHERE role='student' ORDER BY name").fetchall()
    menu_today = conn.execute("""
        SELECT id, name, meal_type, price, portions_available
        FROM menu_items
        WHERE menu_date=?
        ORDER BY meal_type, name
    """, (today_str(),)).fetchall()

    if request.method == "POST":
        student_id = int(request.form.get("student_id", "0") or 0)
        item_id = int(request.form.get("item_id", "0") or 0)
        count = int(request.form.get("count", "1") or 1)
        pay_type = request.form.get("pay_type", "balance").strip()
        comment = request.form.get("comment", "").strip() or None

        if student_id <= 0 or item_id <= 0 or count <= 0:
            error = "Заполните все поля корректно."
        else:
            student = conn.execute("SELECT * FROM users WHERE id=?", (student_id,)).fetchone()
            item = conn.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()

            if not student or student["role"] != "student":
                error = "Ученик не найден."
            elif not item:
                error = "Блюдо не найдено."
            elif item["portions_available"] < count:
                error = f"Недостаточно порций. Доступно: {item['portions_available']}."
            else:

                amount = int(item["price"] or 0) * count

                if pay_type == "balance":
                    if student["balance"] < amount:
                        error = f"Недостаточно средств на балансе ученика. Нужно {amount}₽."
                    else:
                        conn.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, student_id))
                        conn.execute(
                            "INSERT INTO transactions(ts, student_id, type, amount, note) VALUES(?,?,?,?,?)",
                            (now_ts(), student_id, "charge", -amount, f"Оплата питания: {item['name']} x{count}")
                        )

                elif pay_type == "subscription":
                    sub = get_active_subscription(conn, student_id)
                    if not sub:
                        error = "У ученика нет активного абонемента."
                    else:
                        amount = 0  

                elif pay_type == "free":
                    amount = 0
                else:
                    error = "Неверный способ оплаты."

                if not error:
                    conn.execute(
                        "UPDATE menu_items SET portions_available = portions_available - ? WHERE id=?",
                        (count, item_id)
                    )

                    conn.execute("""
                        INSERT INTO serves(ts, student_id, meal_type, item, count, pay_type, amount, comment, staff_id)
                        VALUES(?,?,?,?,?,?,?,?,?)
                    """, (now_ts(), student_id, item["meal_type"], item["name"], count, pay_type, amount, comment, u["id"]))


                    conn.commit()
                    message = f"Выдача выполнена: {student['name']} получил {item['name']} x{count}."

                    add_notice("Выдача", f"{student['name']} получил {item['name']} x{count}.", u["name"], "admin")

                    menu_today = conn.execute("""
                        SELECT id, name, meal_type, price, portions_available
                        FROM menu_items
                        WHERE menu_date=?
                        ORDER BY meal_type, name
                    """, (today_str(),)).fetchall()

    history = conn.execute("""
        SELECT s.*, u.name AS student_name
        FROM serves s
        JOIN users u ON u.id = s.student_id
        ORDER BY s.id DESC
        LIMIT 100
    """).fetchall()

    conn.close()

    return render_template(
        "serve.html",
        user=u,
        students=students,
        menu_today=menu_today,
        history=history,
        error=error,
        message=message,
        MEAL_RU=MEAL_RU
    )


@app.route("/writeoff", methods=["GET", "POST"], endpoint="writeoff")
@role_required("cook", "admin")
def writeoff():
    u = current_user()
    conn = get_db_connection()
    error = None
    message = None

    menu_today = conn.execute("""
        SELECT id, name, meal_type, portions_available
        FROM menu_items
        WHERE menu_date=?
        ORDER BY meal_type, name
    """, (today_str(),)).fetchall()

    if request.method == "POST":
        item_id = int(request.form.get("item_id", "0") or 0)
        count = int(request.form.get("count", "1") or 1)
        reason = request.form.get("reason", "").strip()
        comment = request.form.get("comment", "").strip() or None

        if item_id <= 0 or count <= 0 or not reason:
            error = "Заполните все поля корректно."
        else:
            item = conn.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
            if not item:
                error = "Позиция не найдена."
            elif item["portions_available"] < count:
                error = f"Недостаточно порций. Доступно: {item['portions_available']}."
            else:
                conn.execute(
                    "UPDATE menu_items SET portions_available = portions_available - ? WHERE id=?",
                    (count, item_id)
                )

                conn.execute("""
                    INSERT INTO writeoffs(ts, item, count, reason, comment, staff_id)
                    VALUES(?,?,?,?,?,?)
                """, (now_ts(), item["name"], count, reason, comment, u["id"]))

                conn.commit()
                message = f"Списано: {item['name']} x{count}."

                add_notice("Списание", f"Списано {item['name']} x{count}. Причина: {reason}", u["name"], "admin")

                menu_today = conn.execute("""
                    SELECT id, name, meal_type, portions_available
                    FROM menu_items
                    WHERE menu_date=?
                    ORDER BY meal_type, name
                """, (today_str(),)).fetchall()

    history = conn.execute("""
        SELECT w.*, u.name AS staff_name
        FROM writeoffs w
        LEFT JOIN users u ON u.id = w.staff_id
        ORDER BY w.id DESC
        LIMIT 100
    """).fetchall()

    conn.close()

    return render_template(
        "writeoff.html",
        user=u,
        menu_today=menu_today,
        history=history,
        error=error,
        message=message,
        MEAL_RU=MEAL_RU
    )


@app.route("/users", endpoint="users")
@role_required("admin")
def users():
    return _stub_page("Пользователи", "Раздел 'Пользователи' пока не реализован в app.py. Это заглушка, чтобы меню не падало.")


@app.route("/analytics", endpoint="analytics")
@role_required("admin")
def analytics():
    return _stub_page("Аналитика", "Раздел 'Аналитика' пока не реализован в app.py. Это заглушка, чтобы меню не падало.")


@app.route("/sub")
@login_required
def sub():
    return redirect("/subscriptions")


@app.route("/order")
@login_required
def order():
    return redirect("/orders")


@app.route("/stock")
@login_required
def stock():
    return redirect("/availability")


if __name__ == "__main__":
    app.run(debug=True)
