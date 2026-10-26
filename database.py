"""
Database module — supports SQLite (local) and PostgreSQL (cloud).

If DATABASE_URL env var is set, uses PostgreSQL. Otherwise, uses local SQLite.
"""
import os
import sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Fix Render's postgres:// → postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)


def get_db():
    """Get a database connection. Uses PostgreSQL if DATABASE_URL is set, else SQLite."""
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        from config import DASHBOARD_DB
        conn = sqlite3.connect(DASHBOARD_DB)
        conn.row_factory = sqlite3.Row
        return conn


def _execute(conn, sql, params=None):
    """Execute SQL, adapting syntax for PostgreSQL if needed."""
    cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor


def _fetchone(conn, sql, params=None):
    """Fetch one row as dict."""
    if DATABASE_URL:
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    row = cursor.fetchone()
    if row and DATABASE_URL:
        return dict(row)
    return row


def _fetchall(conn, sql, params=None):
    """Fetch all rows as list of dicts."""
    if DATABASE_URL:
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    rows = cursor.fetchall()
    if DATABASE_URL:
        return [dict(r) for r in rows]
    return rows


def init_db():
    """Initialize the database with required tables."""
    conn = get_db()
    cursor = conn.cursor()

    if DATABASE_URL:
        # PostgreSQL
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS absenteismo (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL,
            setor TEXT NOT NULL DEFAULT 'Geral',
            funcionarios_previstos INTEGER DEFAULT 0,
            funcionarios_presentes INTEGER DEFAULT 0,
            observacao TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(data, setor)
        );

        CREATE TABLE IF NOT EXISTS acidentes (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL,
            descricao TEXT,
            gravidade TEXT DEFAULT 'leve',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS producao_manual (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL,
            produto TEXT,
            lote TEXT,
            envasados INTEGER DEFAULT 0,
            finalizados INTEGER DEFAULT 0,
            retrabalhadas INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS producao_manual_totais (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL UNIQUE,
            total_envasados INTEGER DEFAULT 0,
            total_finalizados INTEGER DEFAULT 0,
            observacao TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS metas_periodo (
            id SERIAL PRIMARY KEY,
            ano INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            meta_automatica INTEGER DEFAULT 25000,
            meta_manual INTEGER DEFAULT 3000,
            meta_sleeve INTEGER DEFAULT 0,
            observacao TEXT,
            UNIQUE(ano, mes)
        );

        CREATE TABLE IF NOT EXISTS metas_diarias (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL UNIQUE,
            meta_automatica INTEGER,
            meta_manual INTEGER,
            meta_sleeve INTEGER,
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS producao_diaria (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL UNIQUE,
            producao INTEGER DEFAULT 0,
            embalagem INTEGER DEFAULT 0,
            sleeve INTEGER DEFAULT 0,
            celofane INTEGER DEFAULT 0,
            turno TEXT,
            total_colab INTEGER,
            ausentes INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS observacoes_diarias (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL,
            setor TEXT NOT NULL,
            observacao TEXT,
            UNIQUE(data, setor)
        );
        """)
        conn.commit()
    else:
        # SQLite
        cursor.executescript("""
        CREATE TABLE IF NOT EXISTS absenteismo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL,
            setor TEXT NOT NULL DEFAULT 'Geral',
            funcionarios_previstos INTEGER DEFAULT 0,
            funcionarios_presentes INTEGER DEFAULT 0,
            observacao TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(data, setor)
        );

        CREATE TABLE IF NOT EXISTS acidentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL,
            descricao TEXT,
            gravidade TEXT DEFAULT 'leve',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS producao_manual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL,
            produto TEXT,
            lote TEXT,
            envasados INTEGER DEFAULT 0,
            finalizados INTEGER DEFAULT 0,
            retrabalhadas INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS producao_manual_totais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL UNIQUE,
            total_envasados INTEGER DEFAULT 0,
            total_finalizados INTEGER DEFAULT 0,
            observacao TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS metas_periodo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ano INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            meta_automatica INTEGER DEFAULT 25000,
            meta_manual INTEGER DEFAULT 3000,
            meta_sleeve INTEGER DEFAULT 0,
            observacao TEXT,
            UNIQUE(ano, mes)
        );

        CREATE TABLE IF NOT EXISTS metas_diarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL UNIQUE,
            meta_automatica INTEGER,
            meta_manual INTEGER,
            meta_sleeve INTEGER,
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS producao_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL UNIQUE,
            producao INTEGER DEFAULT 0,
            embalagem INTEGER DEFAULT 0,
            sleeve INTEGER DEFAULT 0,
            celofane INTEGER DEFAULT 0,
            turno TEXT,
            total_colab INTEGER,
            ausentes INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS observacoes_diarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL,
            setor TEXT NOT NULL,
            observacao TEXT,
            UNIQUE(data, setor)
        );
        """)

    # Seed default configurations
    defaults = {
        'meta_linha_automatica': '25000',
        'meta_linha_manual': '3000',
        'data_ultimo_acidente': '2026-01-01',
    }

    for chave, valor in defaults.items():
        try:
            if DATABASE_URL:
                cursor.execute(
                    "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING",
                    (chave, valor)
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?, ?)",
                    (chave, valor)
                )
        except Exception:
            pass

    conn.commit()
    conn.close()
