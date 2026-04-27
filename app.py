# ==============================================
# app.py — Finanzplaner Backend
# Flask + MySQL + Session-Login + Sicherheit
# ==============================================

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from functools import wraps
import mysql.connector
from mysql.connector import pooling
import os
import hashlib
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# -----------------------------------------------
# SICHERHEITS-KONFIGURATION
# -----------------------------------------------

app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(minutes=30)

ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5000').split(',')
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)


# ==============================================
# MYSQL VERBINDUNG — Connection Pool
#
# Was ist ein Connection Pool?
# Statt bei jeder Anfrage eine neue Verbindung
# zu öffnen (langsam), hält der Pool mehrere
# Verbindungen offen und gibt sie bei Bedarf aus.
# Schneller und stabiler.
# ==============================================

# ==============================================
# DATENBANK-VERBINDUNG
#
# Railway gibt uns eine MYSQL_URL im Format:
# mysql://user:passwort@host:port/datenbankname
#
# Wir parsen diese URL automatisch.
# Lokal kann man auch einzelne DB_* Variablen nutzen.
# ==============================================

import urllib.parse

def parse_db_config():
    # Option 1: Railway URL (wird automatisch gesetzt)
    url = (
        os.environ.get('MYSQL_URL') or
        os.environ.get('MYSQL_PRIVATE_URL') or
        os.environ.get('DATABASE_URL') or
        os.environ.get('MYSQL_PUBLIC_URL')
    )
    if url:
        # URL aufteilen: mysql://root:passwort@host:3306/datenbankname
        parsed = urllib.parse.urlparse(url)
        return {
            'host':     parsed.hostname,
            'port':     parsed.port or 3306,
            'database': parsed.path.lstrip('/'),
            'user':     parsed.username,
            'password': parsed.password or '',
        }
    # Option 2: Einzelne Variablen (lokal)
    return {
        'host':     os.environ.get('DB_HOST')     or os.environ.get('MYSQLHOST',     'localhost'),
        'port':     int(os.environ.get('DB_PORT') or os.environ.get('MYSQLPORT',     3306)),
        'database': os.environ.get('DB_NAME')     or os.environ.get('MYSQLDATABASE', 'finanzplaner'),
        'user':     os.environ.get('DB_USER')     or os.environ.get('MYSQLUSER',     'root'),
        'password': os.environ.get('DB_PASSWORD') or os.environ.get('MYSQLPASSWORD', ''),
    }

db_config = parse_db_config()

db_pool = pooling.MySQLConnectionPool(
    pool_name="finanzplaner_pool",
    pool_size=5,
    host=db_config['host'],
    port=db_config['port'],
    database=db_config['database'],
    user=db_config['user'],
    password=db_config['password'],
    charset='utf8mb4',
    collation='utf8mb4_unicode_ci',
    autocommit=False,
)


def get_db():
    """
    Holt eine Verbindung aus dem Pool.
    Verwendung immer mit 'with get_db() as conn:'
    → Verbindung wird automatisch zurückgegeben.
    """
    return db_pool.get_connection()


def query(sql, params=None, fetch='all'):
    """
    Einheitliche Hilfsfunktion für alle Datenbankabfragen.

    sql    = SQL-Query mit %s als Platzhalter (verhindert SQL Injection)
    params = Tuple mit Werten für die Platzhalter
    fetch  = 'all' (alle Zeilen), 'one' (eine Zeile), 'none' (kein Ergebnis)

    Gibt bei SELECT eine Liste von Dicts zurück.
    Gibt bei INSERT die neue ID zurück.
    """
    conn = get_db()
    try:
        # dictionary=True = Ergebnisse als {spalte: wert} statt Tupel
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())

        if fetch == 'all':
            result = cursor.fetchall()
        elif fetch == 'one':
            result = cursor.fetchone()
        elif fetch == 'lastid':
            conn.commit()
            result = cursor.lastrowid
        else:
            conn.commit()
            result = None

        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()  # Gibt Verbindung zurück an Pool


def init_db():
    """
    Erstellt alle Tabellen wenn sie noch nicht existieren.
    Beim ersten Start aufrufen.
    """
    conn = get_db()
    cursor = conn.cursor()

    tabellen = [
        """
        CREATE TABLE IF NOT EXISTS fixkosten (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            betrag      DECIMAL(10,2) NOT NULL,
            kategorie   VARCHAR(100) DEFAULT 'sonstiges',
            faelligkeit INT DEFAULT 1,
            erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS monate (
            id      INT AUTO_INCREMENT PRIMARY KEY,
            monat   VARCHAR(7) NOT NULL UNIQUE,
            stunden DECIMAL(6,2) DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS cashflow (
            id     INT AUTO_INCREMENT PRIMARY KEY,
            monat  VARCHAR(7) NOT NULL,
            name   VARCHAR(255) NOT NULL,
            betrag DECIMAL(10,2) NOT NULL,
            typ    ENUM('einnahme','ausgabe') NOT NULL,
            woche  TINYINT NOT NULL,
            FOREIGN KEY (monat) REFERENCES monate(monat) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS planung (
            id     INT AUTO_INCREMENT PRIMARY KEY,
            monat  VARCHAR(7) NOT NULL,
            name   VARCHAR(255) NOT NULL,
            betrag DECIMAL(10,2) NOT NULL,
            typ    ENUM('ausgabe','einnahme') NOT NULL,
            datum  DATE NOT NULL,
            notiz  TEXT DEFAULT NULL,
            FOREIGN KEY (monat) REFERENCES monate(monat) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS kalender (
            id     INT AUTO_INCREMENT PRIMARY KEY,
            datum  DATE NOT NULL,
            name   VARCHAR(255) NOT NULL,
            betrag DECIMAL(10,2) NOT NULL,
            typ    ENUM('ausgabe','einnahme') NOT NULL,
            INDEX idx_datum (datum)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS vertraege (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            kosten      DECIMAL(10,2) NOT NULL,
            zahlung     ENUM('monat','jahr') NOT NULL,
            datum       DATE NOT NULL,
            frist       VARCHAR(100) DEFAULT '',
            erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS sparziele (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            ziel        DECIMAL(10,2) NOT NULL,
            aktuell     DECIMAL(10,2) DEFAULT 0,
            monatlich   DECIMAL(10,2) DEFAULT 0,
            erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS wiederkehrend (
            id       INT AUTO_INCREMENT PRIMARY KEY,
            name     VARCHAR(255) NOT NULL,
            betrag   DECIMAL(10,2) NOT NULL,
            frequenz ENUM('monat','woche','jahr') NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS schulden (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            typ         ENUM('schuld','forderung') NOT NULL,
            name        VARCHAR(255) NOT NULL,
            gesamt      DECIMAL(10,2) NOT NULL,
            bezahlt     DECIMAL(10,2) DEFAULT 0,
            rate        DECIMAL(10,2) DEFAULT 0,
            erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
    ]

    for tabelle in tabellen:
        cursor.execute(tabelle)

    conn.commit()
    cursor.close()
    conn.close()
    print("✓ MySQL Datenbank initialisiert")


# ==============================================
# LOGIN & AUTHENTIFIZIERUNG
# ==============================================

def passwort_hash(passwort: str) -> str:
    salt = os.environ.get('PASSWORD_SALT', 'change-this-salt')
    return hashlib.sha256((salt + passwort).encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Nicht eingeloggt'}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/api/login', methods=['POST'])
def login():
    d = request.get_json()
    if not d:
        return jsonify({'error': 'Keine Daten'}), 400

    username = d.get('username', '')
    password = d.get('password', '')

    expected_user = os.environ.get('APP_USERNAME', 'admin')
    expected_hash = os.environ.get('APP_PASSWORD_HASH', '')

    user_ok = secrets.compare_digest(username, expected_user)
    pass_ok = secrets.compare_digest(passwort_hash(password), expected_hash)

    if user_ok and pass_ok:
        session.permanent = True
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Ungültige Zugangsdaten'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({'logged_in': bool(session.get('logged_in'))})


# ==============================================
# FIXKOSTEN
# ==============================================

@app.route('/api/fixkosten', methods=['GET'])
@login_required
def get_fixkosten():
    rows = query("SELECT * FROM fixkosten ORDER BY id")
    return jsonify(rows)


@app.route('/api/fixkosten', methods=['POST'])
@login_required
def add_fixkosten():
    d = request.get_json()
    if not d.get('name') or d.get('betrag') is None:
        return jsonify({'error': 'Name und Betrag erforderlich'}), 400

    new_id = query(
        "INSERT INTO fixkosten (name, betrag, kategorie, faelligkeit) VALUES (%s, %s, %s, %s)",
        (d['name'], float(d['betrag']), d.get('kategorie', 'sonstiges'), int(d.get('faelligkeit', 1))),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/fixkosten/<int:item_id>', methods=['DELETE'])
@login_required
def delete_fixkosten(item_id):
    query("DELETE FROM fixkosten WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# MONATE & STUNDEN
# ==============================================

@app.route('/api/monate/<monat>', methods=['GET'])
@login_required
def get_monat(monat):
    # Monat anlegen falls nicht vorhanden
    query("INSERT IGNORE INTO monate (monat, stunden) VALUES (%s, 0)", (monat,), fetch='none')

    monat_row = query("SELECT * FROM monate WHERE monat = %s", (monat,), fetch='one')
    cashflow  = query("SELECT * FROM cashflow WHERE monat = %s ORDER BY woche, id", (monat,))
    planung   = query("SELECT * FROM planung  WHERE monat = %s ORDER BY datum",     (monat,))

    return jsonify({
        'stunden':  float(monat_row['stunden']) if monat_row else 0,
        'cashflow': cashflow,
        'planung':  planung,
    })


@app.route('/api/monate/<monat>/stunden', methods=['PUT'])
@login_required
def update_stunden(monat):
    d = request.get_json()
    stunden = float(d.get('stunden', 0))
    query("INSERT INTO monate (monat, stunden) VALUES (%s, %s) ON DUPLICATE KEY UPDATE stunden = %s",
          (monat, stunden, stunden), fetch='none')
    return jsonify({'success': True})


# ==============================================
# CASHFLOW
# ==============================================

@app.route('/api/cashflow/<monat>', methods=['POST'])
@login_required
def add_cashflow(monat):
    d = request.get_json()
    if not d.get('name') or d.get('typ') not in ('einnahme', 'ausgabe'):
        return jsonify({'error': 'Ungültige Daten'}), 400

    query("INSERT IGNORE INTO monate (monat) VALUES (%s)", (monat,), fetch='none')
    new_id = query(
        "INSERT INTO cashflow (monat, name, betrag, typ, woche) VALUES (%s, %s, %s, %s, %s)",
        (monat, d['name'], float(d['betrag']), d['typ'], int(d.get('woche', 1))),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/cashflow/<int:item_id>', methods=['DELETE'])
@login_required
def delete_cashflow(item_id):
    query("DELETE FROM cashflow WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# PLANUNG
# ==============================================

@app.route('/api/planung/<monat>', methods=['POST'])
@login_required
def add_planung(monat):
    d = request.get_json()
    if not d.get('name') or not d.get('datum'):
        return jsonify({'error': 'Name und Datum erforderlich'}), 400

    query("INSERT IGNORE INTO monate (monat) VALUES (%s)", (monat,), fetch='none')
    new_id = query(
        "INSERT INTO planung (monat, name, betrag, typ, datum, notiz) VALUES (%s, %s, %s, %s, %s, %s)",
        (monat, d['name'], float(d['betrag']), d.get('typ', 'ausgabe'), d['datum'], d.get('notiz', '')),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/planung/<int:item_id>', methods=['DELETE'])
@login_required
def delete_planung(item_id):
    query("DELETE FROM planung WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# KALENDER
# ==============================================

@app.route('/api/kalender/<monat>', methods=['GET'])
@login_required
def get_kalender(monat):
    # MySQL: datum LIKE '2026-04%' → alle Einträge im April 2026
    rows = query(
        "SELECT * FROM kalender WHERE DATE_FORMAT(datum, %s) = %s ORDER BY datum",
        ('%Y-%m', monat)
    )
    return jsonify(rows)


@app.route('/api/kalender', methods=['POST'])
@login_required
def add_kalender():
    d = request.get_json()
    if not d.get('datum') or not d.get('name'):
        return jsonify({'error': 'Datum und Name erforderlich'}), 400

    new_id = query(
        "INSERT INTO kalender (datum, name, betrag, typ) VALUES (%s, %s, %s, %s)",
        (d['datum'], d['name'], float(d['betrag']), d.get('typ', 'ausgabe')),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/kalender/<int:item_id>', methods=['DELETE'])
@login_required
def delete_kalender(item_id):
    query("DELETE FROM kalender WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# VERTRÄGE
# ==============================================

@app.route('/api/vertraege', methods=['GET'])
@login_required
def get_vertraege():
    return jsonify(query("SELECT * FROM vertraege ORDER BY datum"))


@app.route('/api/vertraege', methods=['POST'])
@login_required
def add_vertrag():
    d = request.get_json()
    if not d.get('name') or not d.get('datum'):
        return jsonify({'error': 'Name und Datum erforderlich'}), 400

    new_id = query(
        "INSERT INTO vertraege (name, kosten, zahlung, datum, frist) VALUES (%s, %s, %s, %s, %s)",
        (d['name'], float(d['kosten']), d.get('zahlung', 'monat'), d['datum'], d.get('frist', '')),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/vertraege/<int:item_id>', methods=['DELETE'])
@login_required
def delete_vertrag(item_id):
    query("DELETE FROM vertraege WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# SPARZIELE
# ==============================================

@app.route('/api/sparziele', methods=['GET'])
@login_required
def get_sparziele():
    return jsonify(query("SELECT * FROM sparziele ORDER BY id"))


@app.route('/api/sparziele', methods=['POST'])
@login_required
def add_sparziel():
    d = request.get_json()
    if not d.get('name') or not d.get('ziel'):
        return jsonify({'error': 'Name und Ziel erforderlich'}), 400

    new_id = query(
        "INSERT INTO sparziele (name, ziel, aktuell, monatlich) VALUES (%s, %s, %s, %s)",
        (d['name'], float(d['ziel']), float(d.get('aktuell', 0)), float(d.get('monatlich', 0))),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/sparziele/<int:item_id>', methods=['DELETE'])
@login_required
def delete_sparziel(item_id):
    query("DELETE FROM sparziele WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# WIEDERKEHRENDE EINNAHMEN
# ==============================================

@app.route('/api/wiederkehrend', methods=['GET'])
@login_required
def get_wiederkehrend():
    return jsonify(query("SELECT * FROM wiederkehrend ORDER BY id"))


@app.route('/api/wiederkehrend', methods=['POST'])
@login_required
def add_wiederkehrend():
    d = request.get_json()
    if not d.get('name') or d.get('frequenz') not in ('monat', 'woche', 'jahr'):
        return jsonify({'error': 'Ungültige Daten'}), 400

    new_id = query(
        "INSERT INTO wiederkehrend (name, betrag, frequenz) VALUES (%s, %s, %s)",
        (d['name'], float(d['betrag']), d['frequenz']),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/wiederkehrend/<int:item_id>', methods=['DELETE'])
@login_required
def delete_wiederkehrend(item_id):
    query("DELETE FROM wiederkehrend WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# SCHULDEN
# ==============================================

@app.route('/api/schulden', methods=['GET'])
@login_required
def get_schulden():
    return jsonify(query("SELECT * FROM schulden ORDER BY id"))


@app.route('/api/schulden', methods=['POST'])
@login_required
def add_schuld():
    d = request.get_json()
    if not d.get('name') or not d.get('gesamt'):
        return jsonify({'error': 'Name und Gesamtbetrag erforderlich'}), 400

    new_id = query(
        "INSERT INTO schulden (typ, name, gesamt, bezahlt, rate) VALUES (%s, %s, %s, %s, %s)",
        (d.get('typ', 'schuld'), d['name'], float(d['gesamt']),
         float(d.get('bezahlt', 0)), float(d.get('rate', 0))),
        fetch='lastid'
    )
    return jsonify({'id': new_id, 'success': True}), 201


@app.route('/api/schulden/<int:item_id>', methods=['DELETE'])
@login_required
def delete_schuld(item_id):
    query("DELETE FROM schulden WHERE id = %s", (item_id,), fetch='none')
    return jsonify({'success': True})


# ==============================================
# ALLE DATEN AUF EINMAL (Frontend-Start)
# ==============================================

@app.route('/api/alles', methods=['GET'])
@login_required
def get_alles():
    return jsonify({
        'fixkosten':     query("SELECT * FROM fixkosten ORDER BY id"),
        'vertraege':     query("SELECT * FROM vertraege ORDER BY datum"),
        'sparziele':     query("SELECT * FROM sparziele ORDER BY id"),
        'wiederkehrend': query("SELECT * FROM wiederkehrend ORDER BY id"),
        'schulden':      query("SELECT * FROM schulden ORDER BY id"),
    })


# ==============================================
# START
# ==============================================

if __name__ == '__main__':
    init_db()
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
