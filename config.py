import os

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCAO_DIR = os.path.dirname(BASE_DIR)

# Excel file for Automatic Line
EXCEL_FOLDER = os.path.join(PRODUCAO_DIR, 'Acompanhamento Produtividade')

# SQLite database for Manual Line (existing system)
SISTEMA_PRODUCAO_DB = os.path.join(PRODUCAO_DIR, 'sistema_producao', 'producao.db')

# Local dashboard database
DASHBOARD_DB = os.path.join(BASE_DIR, 'dashboard.db')

# Production targets
META_LINHA_AUTOMATICA = 25000  # units/day
META_LINHA_MANUAL = 3000       # units/day
META_SLEEVE = 0                # default (0 = not tracked)

# Dashboard settings
AUTO_REFRESH_SECONDS = 300  # 5 minutes
FLASK_PORT = int(os.environ.get('FLASK_PORT', 5051))

# Excel cache TTL (seconds)
EXCEL_CACHE_TTL = 120  # 2 minutes

def get_meta_periodo(ano, mes, data_str=None):
    """Get metas for a date. Checks daily override first, then monthly, then defaults."""
    from database import get_db
    conn = get_db()

    # 1. Check daily override
    if data_str:
        row = conn.execute('SELECT * FROM metas_diarias WHERE data=?', (data_str,)).fetchone()
        if row:
            # For NULL fields in daily override, fall back to monthly meta (not config defaults)
            monthly = conn.execute('SELECT * FROM metas_periodo WHERE ano=? AND mes=?', (ano, mes)).fetchone()
            fallback_auto = monthly['meta_automatica'] if monthly else META_LINHA_AUTOMATICA
            fallback_manual = monthly['meta_manual'] if monthly else META_LINHA_MANUAL
            fallback_sleeve = (monthly['meta_sleeve'] if monthly and 'meta_sleeve' in monthly.keys() else META_SLEEVE)

            result = {
                'auto': row['meta_automatica'] if row['meta_automatica'] is not None else fallback_auto,
                'manual': row['meta_manual'] if row['meta_manual'] is not None else fallback_manual,
                'sleeve': row['meta_sleeve'] if row['meta_sleeve'] is not None else fallback_sleeve,
                'obs': row['observacao'] or '',
            }
            conn.close()
            return result

    # 2. Check monthly meta
    row = conn.execute('SELECT * FROM metas_periodo WHERE ano=? AND mes=?', (ano, mes)).fetchone()
    conn.close()
    if row:
        return {
            'auto': row['meta_automatica'],
            'manual': row['meta_manual'],
            'sleeve': row['meta_sleeve'] if 'meta_sleeve' in row.keys() else META_SLEEVE,
            'obs': '',
        }
    return {'auto': META_LINHA_AUTOMATICA, 'manual': META_LINHA_MANUAL, 'sleeve': META_SLEEVE, 'obs': ''}

