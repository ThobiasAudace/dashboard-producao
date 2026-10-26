"""
Factory metrics: absenteeism tracking and days-without-accidents counter.

Uses the dashboard's own SQLite database (dashboard.db).
"""

from datetime import datetime, date
from database import get_db


def get_dias_sem_acidente():
    """Calculate days since last accident.

    Returns dict with: dias, data_ultimo_acidente, descricao
    """
    conn = get_db()
    cursor = conn.cursor()

    # Check for most recent accident record
    cursor.execute("""
        SELECT data, descricao, gravidade
        FROM acidentes
        ORDER BY data DESC
        LIMIT 1
    """)
    row = cursor.fetchone()

    if row:
        data_acidente = datetime.strptime(row['data'], '%Y-%m-%d').date()
        dias = (date.today() - data_acidente).days
        result = {
            'dias': dias,
            'data_ultimo_acidente': row['data'],
            'descricao': row['descricao'],
            'gravidade': row['gravidade']
        }
    else:
        # Fallback to configuration
        cursor.execute(
            "SELECT valor FROM configuracoes WHERE chave = 'data_ultimo_acidente'"
        )
        config = cursor.fetchone()
        if config:
            data_acidente = datetime.strptime(config['valor'], '%Y-%m-%d').date()
            dias = (date.today() - data_acidente).days
        else:
            dias = 0
            data_acidente = date.today()

        result = {
            'dias': dias,
            'data_ultimo_acidente': data_acidente.strftime('%Y-%m-%d'),
            'descricao': None,
            'gravidade': None
        }

    conn.close()
    return result


def registrar_acidente(data_acidente, descricao='', gravidade='leve'):
    """Register a new accident, resetting the days counter."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO acidentes (data, descricao, gravidade) VALUES (?, ?, ?)",
        (data_acidente, descricao, gravidade)
    )
    # Also update the config
    cursor.execute(
        "INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES ('data_ultimo_acidente', ?)",
        (data_acidente,)
    )
    conn.commit()
    conn.close()


def get_absenteismo_dia(data=None):
    """Get absenteeism data for a specific date.

    Returns dict with: data, registros (list), taxa_geral
    """
    if data is None:
        data = date.today().strftime('%Y-%m-%d')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM absenteismo WHERE data = ? ORDER BY setor",
        (data,)
    )
    rows = cursor.fetchall()
    conn.close()

    registros = [dict(r) for r in rows]

    total_previstos = sum(r['funcionarios_previstos'] for r in registros)
    total_presentes = sum(r['funcionarios_presentes'] for r in registros)

    if total_previstos > 0:
        taxa_geral = ((total_previstos - total_presentes) / total_previstos) * 100
    else:
        taxa_geral = 0

    return {
        'data': data,
        'registros': registros,
        'total_previstos': total_previstos,
        'total_presentes': total_presentes,
        'total_ausentes': total_previstos - total_presentes,
        'taxa_geral': round(taxa_geral, 1)
    }


def salvar_absenteismo(data, setor, previstos, presentes, observacao=''):
    """Save or update absenteeism record for a date/sector."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO absenteismo
            (data, setor, funcionarios_previstos, funcionarios_presentes, observacao)
        VALUES (?, ?, ?, ?, ?)
    """, (data, setor, previstos, presentes, observacao))
    conn.commit()
    conn.close()


def get_absenteismo_semana(data_ref=None):
    """Get absenteeism data for the current week."""
    from datetime import timedelta

    if data_ref is None:
        data_ref = date.today()
    elif isinstance(data_ref, str):
        data_ref = datetime.strptime(data_ref, '%Y-%m-%d').date()

    start = data_ref - timedelta(days=data_ref.weekday())
    dias_semana = ['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB', 'DOM']
    result = []

    for i in range(7):
        day = start + timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        dados = get_absenteismo_dia(day_str)
        dados['dia_semana'] = dias_semana[i]
        result.append(dados)

    return result


def get_historico_acidentes(limit=10):
    """Get recent accident history."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM acidentes ORDER BY data DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_config(chave, default=None):
    """Get a configuration value."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
    row = cursor.fetchone()
    conn.close()
    return row['valor'] if row else default


def set_config(chave, valor):
    """Set a configuration value."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)",
        (chave, valor)
    )
    conn.commit()
    conn.close()
