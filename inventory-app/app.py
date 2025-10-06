python
import os
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-123')
DATABASE_URL = os.environ.get('DATABASE_URL')

DOC_TYPES = ["накладная", "раздаточная ведомость", "наряд", "акт изъятия", "акт списания"]

def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect('inventory.db')
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Номенклатура
    if DATABASE_URL:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS nomenclature (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT
            )
        ''')
        # Партии
        cur.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id SERIAL PRIMARY KEY,
                nomenclature_id INTEGER NOT NULL,
                batch_number TEXT NOT NULL,
                manufacture_year INTEGER NOT NULL,
                manufacturer TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                location TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Документы
        cur.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                doc_number TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                doc_date DATE NOT NULL,
                issued_by TEXT,
                notes TEXT
            )
        ''')
        # Операции
        cur.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                quantity_change INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS nomenclature (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nomenclature_id INTEGER NOT NULL,
                batch_number TEXT NOT NULL,
                manufacture_year INTEGER NOT NULL,
                manufacturer TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                location TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_number TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                doc_date TEXT NOT NULL,
                issued_by TEXT,
                notes TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                quantity_change INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    
    conn.commit()
    conn.close()

@app.before_first_request
def setup():
    init_db()

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('''
            SELECT n.id, n.code, n.name, n.category, 
                   COALESCE(SUM(b.quantity), 0) as total_qty
            FROM nomenclature n
            LEFT JOIN batches b ON n.id = b.nomenclature_id
            GROUP BY n.id, n.code, n.name, n.category
            ORDER BY n.name
        ''')
    else:
        cur.execute('''
            SELECT n.id, n.code, n.name, n.category, 
                   IFNULL(SUM(b.quantity), 0) as total_qty
            FROM nomenclature n
            LEFT JOIN batches b ON n.id = b.nomenclature_id
            GROUP BY n.id, n.code, n.name, n.category
            ORDER BY n.name
        ''')
    items = cur.fetchall()
    conn.close()
    return render_template('index.html', items=items, doc_types=DOC_TYPES, today=date.today())

@app.route('/add_nomenclature', methods=['POST'])
def add_nomenclature():
    code = request.form['code'].strip()
    name = request.form['name'].strip()
    if not code or not name:
        flash('❌ Код и наименование обязательны!', 'error')
        return redirect('/')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO nomenclature (code, name, category)
            VALUES (%s, %s, %s)
        ''', (code, name, request.form.get('category', '').strip()))
        conn.commit()
        flash('✅ Номенклатура добавлена!', 'success')
    except Exception as e:
        if 'unique' in str(e).lower():
            flash('❌ Код уже существует!', 'error')
        else:
            flash('❌ Ошибка.', 'error')
    finally:
        conn.close()
    return redirect('/')

@app.route('/add_receipt/<int:nomen_id>', methods=['POST'])
def add_receipt(nomen_id):
    batch_number = request.form['batch_number'].strip()
    manufacture_year = request.form.get('manufacture_year', '').strip()
    manufacturer = request.form['manufacturer'].strip()
    quantity = request.form.get('quantity', '0')
    doc_number = request.form['doc_number'].strip()
    doc_type = request.form['doc_type']
    doc_date = request.form['doc_date']
    location = request.form.get('location', '').strip()
    issued_by = request.form.get('issued_by', '').strip()
    notes = request.form.get('notes', '').strip()

    if not batch_number or not manufacturer or not manufacture_year.isdigit() or not quantity.isdigit() or int(quantity) <= 0 or not doc_number or not doc_date:
        flash('❌ Заполните все обязательные поля.', 'error')
        return redirect('/')

    year = int(manufacture_year)
    qty = int(quantity)
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute('''
            SELECT id, quantity FROM batches 
            WHERE nomenclature_id = %s 
              AND batch_number = %s 
              AND manufacture_year = %s 
              AND manufacturer = %s
        ''', (nomen_id, batch_number, year, manufacturer))
        existing = cur.fetchone()

        if DATABASE_URL:
            cur.execute('''
                INSERT INTO documents (doc_number, doc_type, doc_date, issued_by, notes)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            ''', (doc_number, doc_type, doc_date, issued_by, notes))
            doc_id = cur.fetchone()['id']
        else:
            cur.execute('''
                INSERT INTO documents (doc_number, doc_type, doc_date, issued_by, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (doc_number, doc_type, doc_date, issued_by, notes))
            doc_id = cur.lastrowid

        if existing:
            cur.execute('UPDATE batches SET quantity = %s WHERE id = %s', (existing['quantity'] + qty, existing['id']))
            batch_id = existing['id']
        else:
            if DATABASE_URL:
                cur.execute('''
                    INSERT INTO batches (nomenclature_id, batch_number, manufacture_year, manufacturer, quantity, location)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                ''', (nomen_id, batch_number, year, manufacturer, qty, location))
                batch_id = cur.fetchone()['id']
            else:
                cur.execute('''
                    INSERT INTO batches (nomenclature_id, batch_number, manufacture_year, manufacturer, quantity, location)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (nomen_id, batch_number, year, manufacturer, qty, location))
                batch_id = cur.lastrowid

        cur.execute('''
            INSERT INTO transactions (batch_id, document_id, quantity_change)
            VALUES (%s, %s, %s)
        ''', (batch_id, doc_id, qty))

        conn.commit()
        flash(f'✅ Приход на {qty} ед. проведён', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'❌ Ошибка: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect('/')

@app.route('/write_off/<int:batch_id>', methods=['POST'])
def write_off(batch_id):
    quantity = request.form.get('quantity', '0')
    doc_number = request.form['doc_number'].strip()
    doc_type = request.form['doc_type']
    doc_date = request.form['doc_date']
    issued_by = request.form.get('issued_by', '').strip()
    notes = request.form.get('notes', '').strip()
    nomen_id = request.form.get('nomen_id')

    if not quantity.isdigit() or int(quantity) <= 0 or not doc_number or not doc_date or not nomen_id:
        flash('❌ Ошибка в данных.', 'error')
        return redirect(f'/nomenclature/{nomen_id}')

    qty = int(quantity)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT quantity FROM batches WHERE id = %s', (batch_id,))
    batch = cur.fetchone()
    if not batch or batch['quantity'] < qty:
        flash('❌ Недостаточно остатка!', 'error')
        return redirect(f'/nomenclature/{nomen_id}')

    try:
        if DATABASE_URL:
            cur.execute('''
                INSERT INTO documents (doc_number, doc_type, doc_date, issued_by, notes)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            ''', (doc_number, doc_type, doc_date, issued_by, notes))
            doc_id = cur.fetchone()['id']
        else:
            cur.execute('''
                INSERT INTO documents (doc_number, doc_type, doc_date, issued_by, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (doc_number, doc_type, doc_date, issued_by, notes))
            doc_id = cur.lastrowid

        cur.execute('''
            INSERT INTO transactions (batch_id, document_id, quantity_change)
            VALUES (%s, %s, %s)
        ''', (batch_id, doc_id, -qty))
        cur.execute('UPDATE batches SET quantity = quantity - %s WHERE id = %s', (qty, batch_id))
        conn.commit()
        flash('✅ Списание проведено', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'❌ Ошибка: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(f'/nomenclature/{nomen_id}')

@app.route('/nomenclature/<int:nomen_id>')
def nomenclature_detail(nomen_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nomenclature WHERE id = %s', (nomen_id,))
    nomen = cur.fetchone()
    if not nomen:
        flash('❌ Не найдено', 'error')
        return redirect('/')
    cur.execute('SELECT * FROM batches WHERE nomenclature_id = %s AND quantity > 0 ORDER BY created_at DESC', (nomen_id,))
    batches = cur.fetchall()
    total = sum(b['quantity'] for b in batches)
    conn.close()
    return render_template('nomenclature_detail.html', nomen=nomen, batches=batches, total=total, doc_types=DOC_TYPES, today=date.today())

@app.route('/documents')
def documents_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM documents ORDER BY doc_date DESC, id DESC')
    docs = cur.fetchall()
    conn.close()
    return render_template('documents.html', documents=docs)

if name == '__main__':
    init_db()

    app.run(debug=True)
