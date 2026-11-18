import os
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from functools import wraps
from datetime import datetime, timezone

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "usdt_sim.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Demo-only asset. This application does not issue, custody, or transfer real USDT.
ASSET_NAME = "USDT_SIM"
DISPLAY_NAME = "USDT Simulator"
DECIMALS = 6
MAX_AMOUNT = Decimal("1000000000")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            amount TEXT NOT NULL DEFAULT '0'
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            from_user TEXT,
            to_user TEXT,
            amount TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        admin_name = os.environ.get("ADMIN_USERNAME", "admin")
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if not admin_password:
            # A one-time random password is printed on first launch if none is configured.
            admin_password = secrets.token_urlsafe(16)
            print(f"\n[INITIAL ADMIN] username: {admin_name}\n[INITIAL ADMIN] password: {admin_password}\n"
                  "Set ADMIN_PASSWORD in your environment for persistent deployments.\n")
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (admin_name,)).fetchone()
        if not existing:
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, is_admin) VALUES (?, ?, 1)",
                (admin_name, generate_password_hash(admin_password))
            )
            conn.execute("INSERT INTO balances(user_id, amount) VALUES (?, '0')", (cur.lastrowid,))


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        supplied = request.form.get("_csrf", "")
        expected = session.get("_csrf", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            abort(400, "Jeton CSRF invalide. Rechargez la page.")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    if "user_id" not in session:
        return None
    with db() as conn:
        return conn.execute("SELECT id, username, is_admin FROM users WHERE id = ?",
                            (session["user_id"],)).fetchone()


def parse_amount(raw):
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError("Montant invalide.")
    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
        raise ValueError("Le montant doit être positif et inférieur ou égal à 1 milliard.")
    if value.as_tuple().exponent < -DECIMALS:
        raise ValueError(f"Maximum {DECIMALS} décimales.")
    return value.quantize(Decimal("0.000001"))


@app.get("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Connexion réussie.", "success")
            return redirect(url_for("dashboard"))
        flash("Identifiants incorrects.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    with db() as conn:
        balance_row = conn.execute("SELECT amount FROM balances WHERE user_id = ?",
                                   (user["id"],)).fetchone()
        transactions = conn.execute("""
            SELECT * FROM transactions
            WHERE from_user = ? OR to_user = ?
            ORDER BY id DESC LIMIT 20
        """, (user["username"], user["username"])).fetchall()
        total = conn.execute("SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) AS total FROM balances").fetchone()["total"]
    return render_template("dashboard.html", user=user,
                           balance=balance_row["amount"] if balance_row else "0",
                           transactions=transactions, total_supply=f"{total:,.6f}")


@app.post("/mint")
@login_required
def mint():
    user = current_user()
    if not user["is_admin"]:
        abort(403)
    try:
        amount = parse_amount(request.form.get("amount", ""))
        recipient = request.form.get("recipient", "").strip()
        if not recipient or len(recipient) > 40:
            raise ValueError("Nom du destinataire invalide.")
        with db() as conn:
            target = conn.execute("SELECT id, username FROM users WHERE username = ?", (recipient,)).fetchone()
            if not target:
                raise ValueError("Utilisateur introuvable.")
            row = conn.execute("SELECT amount FROM balances WHERE user_id = ?", (target["id"],)).fetchone()
            new_balance = Decimal(row["amount"]) + amount
            conn.execute("UPDATE balances SET amount = ? WHERE user_id = ?",
                         (str(new_balance), target["id"]))
            conn.execute("""INSERT INTO transactions(kind, from_user, to_user, amount, note, created_at)
                            VALUES ('MINT', NULL, ?, ?, 'Création de jetons de démonstration', ?)""",
                         (recipient, str(amount), datetime.now(timezone.utc).isoformat()))
        flash(f"{amount} {ASSET_NAME} simulés crédités à {recipient}.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard"))


@app.post("/transfer")
@login_required
def transfer():
    user = current_user()
    recipient = request.form.get("recipient", "").strip()
    try:
        amount = parse_amount(request.form.get("amount", ""))
        if recipient == user["username"]:
            raise ValueError("Vous ne pouvez pas vous envoyer des jetons à vous-même.")
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute("SELECT id FROM users WHERE username = ?", (recipient,)).fetchone()
            sender_balance = conn.execute("SELECT amount FROM balances WHERE user_id = ?",
                                          (user["id"],)).fetchone()
            if not target:
                raise ValueError("Destinataire introuvable.")
            available = Decimal(sender_balance["amount"])
            if amount > available:
                raise ValueError("Solde insuffisant.")
            target_balance = conn.execute("SELECT amount FROM balances WHERE user_id = ?",
                                          (target["id"],)).fetchone()
            conn.execute("UPDATE balances SET amount = ? WHERE user_id = ?",
                         (str(available - amount), user["id"]))
            conn.execute("UPDATE balances SET amount = ? WHERE user_id = ?",
                         (str(Decimal(target_balance["amount"]) + amount), target["id"]))
            conn.execute("""INSERT INTO transactions(kind, from_user, to_user, amount, note, created_at)
                            VALUES ('TRANSFER', ?, ?, ?, 'Transfert interne de démonstration', ?)""",
                         (user["username"], recipient, str(amount), datetime.now(timezone.utc).isoformat()))
        flash(f"Transfert simulé de {amount} {ASSET_NAME} effectué.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 40 or not username.replace("_", "").isalnum():
            flash("Identifiant : 3 à 40 caractères alphanumériques ou underscore.", "error")
        elif len(password) < 12:
            flash("Le mot de passe doit contenir au moins 12 caractères.", "error")
        else:
            try:
                with db() as conn:
                    cur = conn.execute("INSERT INTO users(username, password_hash) VALUES (?, ?)",
                                       (username, generate_password_hash(password)))
                    conn.execute("INSERT INTO balances(user_id, amount) VALUES (?, '0')", (cur.lastrowid,))
                flash("Compte de démonstration créé. Connectez-vous.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Cet identifiant existe déjà.", "error")
    return render_template("register.html")


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=str(error.description)), 400


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="Accès réservé à l'administrateur."), 403


init_db()

if __name__ == "__main__":
    # Local development only. Use a production WSGI server for deployment.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
