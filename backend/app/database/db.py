import sqlite3
import os
import sys
from contextlib import contextmanager

def get_db_path():
    # Always store database in "data/" folder at project root (next to backend/, static/)
    # backend/app/database/db.py -> app/database/db.py -> database/db.py -> db.py -> root
    # or using 4 dirnames:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "data", "database.sqlite")

DB_PATH = get_db_path()

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                razao_social TEXT NOT NULL,
                cnpj_cpf TEXT UNIQUE NOT NULL,
                endereco TEXT,
                numero TEXT,
                bairro TEXT,
                municipio TEXT,
                uf TEXT,
                cep TEXT,
                regime TEXT,
                responsavel_legal TEXT,
                codigo_dominio TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS socios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                cpf TEXT,
                percentual REAL,
                ano_referencia INTEGER,
                data_saida DATE,
                FOREIGN KEY (empresa_id) REFERENCES empresas (id),
                UNIQUE(empresa_id, nome, cpf)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faturamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER NOT NULL,
                cnpj TEXT NOT NULL,
                ano INTEGER NOT NULL,
                mes INTEGER NOT NULL,
                valor REAL NOT NULL,
                origem TEXT NOT NULL,
                detalhes_json TEXT,
                data_importacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (empresa_id) REFERENCES empresas (id),
                UNIQUE(cnpj, ano, mes, origem)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                crc TEXT NOT NULL
            )
        """)
