"""
Reads production data for the Automatic Line from the Excel spreadsheet.

The spreadsheet is located in the 'Acompanhamento Produtividade' folder and
contains a 'Consolidado' sheet with columns:
  B: Data (date)
  C: Produção (production units)
  D: Embalagem (packaging units)
  E: Sleeve (sleeve units)
  F: Celofane (cellophane units)
"""

import os
import glob
import time
from datetime import datetime, timedelta

import pandas as pd

from config import EXCEL_FOLDER, META_LINHA_AUTOMATICA, EXCEL_CACHE_TTL


# In-memory cache
_cache = {
    'data': None,
    'timestamp': 0,
    'file_path': None,
}

_obs_cache = {
    'data': None,
    'timestamp': 0,
}


def _find_latest_excel():
    """Find Produtividade*.xlsx files, sorted by most recent first."""
    pattern = os.path.join(EXCEL_FOLDER, 'Produtividade*.xlsx')
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith('~$')]
    if not files:
        # Fallback: try any xlsx but skip temp files (~$)
        pattern = os.path.join(EXCEL_FOLDER, '*.xlsx')
        files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith('~$')]
    if not files:
        return []
    # Sort by modification time, newest first
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _load_excel_data(force=False):
    """Load data from Produtividade_Geral.xlsx (single source) or fallback to old files."""
    now = time.time()

    if not force and _cache['data'] is not None:
        if (now - _cache['timestamp']) < EXCEL_CACHE_TTL:
            return _cache['data']

    # ---- Try Produtividade_Geral.xlsx (unified file) ----
    geral_file = os.path.join(EXCEL_FOLDER, 'Produtividade_Geral.xlsx')
    if os.path.exists(geral_file):
        try:
            df = pd.read_excel(geral_file, sheet_name='Consolidado')

            # Flexible column mapping (handles encoding issues)
            target_map = {
                'data': ['Data'],
                'producao': ['Produção', 'Producao', 'Produ'],
                'embalagem': ['Embalagem'],
                'sleeve': ['Sleeve'],
                'celofane': ['Celofane'],
                'manual_fin': ['Manual Fin.', 'Manual Fin'],
                'manual_env': ['Manual Env.', 'Manual Env'],
                'turno': ['Turno'],
                'total_colab': ['Total Colab.', 'Total Colab'],
                'ausentes': ['Ausentes'],
                'presentes': ['Presentes'],
                'taxa_abs': ['Absenteísmo %', 'Absenteismo %', 'Absenteis'],
            }
            rename = {}
            for target, candidates_list in target_map.items():
                found = False
                for orig_col in df.columns:
                    if orig_col in rename:
                        continue  # already mapped to another target
                    for candidate in candidates_list:
                        if candidate.lower() in orig_col.lower():
                            rename[orig_col] = target
                            found = True
                            break
                    if found:
                        break
            df = df.rename(columns=rename)

            df['data'] = df['data'].apply(_parse_date)
            df = df.dropna(subset=['data'])

            for col in ['producao', 'embalagem', 'sleeve', 'celofane',
                        'manual_fin', 'manual_env', 'total_colab', 'ausentes', 'presentes']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
                else:
                    df[col] = 0
            if 'taxa_abs' not in df.columns:
                df['taxa_abs'] = 0.0
            df['taxa_abs'] = pd.to_numeric(df['taxa_abs'], errors='coerce').fillna(0.0)
            if 'turno' not in df.columns:
                df['turno'] = ''
            df['turno'] = df['turno'].fillna('').astype(str)

            # Keep rows with production OR absenteeism data
            df = df[(df['producao'] > 0) | (df['total_colab'] > 0)]
            if not df.empty:
                df = df.sort_values('data').reset_index(drop=True)
                print(f"[excel_reader] Loaded {len(df)} rows from Produtividade_Geral.xlsx")
                _cache['data'] = df
                _cache['timestamp'] = now
                _cache['file_path'] = geral_file
                return df
        except Exception as e:
            print(f"[excel_reader] Geral error: {e}")

    # ---- Fallback: old Produtividade*.xlsx files ----
    candidates = _find_latest_excel()
    all_dfs = []

    for file_path in candidates:
        try:
            df_raw = pd.read_excel(file_path, sheet_name='Consolidado', header=None)
            header_row = None
            for i, row in df_raw.iterrows():
                if str(row.iloc[1]).strip().lower() == 'data':
                    header_row = i
                    break
            if header_row is None:
                continue
            df = df_raw.iloc[header_row + 1:, 1:6].copy()
            df.columns = ['data', 'producao', 'embalagem', 'sleeve', 'celofane']
            df['data'] = df['data'].apply(_parse_date)
            df = df.dropna(subset=['data'])
            for col in ['producao', 'embalagem', 'sleeve', 'celofane']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            for col in ['manual_fin', 'manual_env', 'total_colab', 'ausentes', 'presentes']:
                df[col] = 0
            df['taxa_abs'] = 0.0
            df['turno'] = ''
            df = df[df['producao'] > 0]
            if not df.empty:
                all_dfs.append(df)
                print(f"[excel_reader] Fallback: {len(df)} rows from {os.path.basename(file_path)}")
        except Exception as e:
            print(f"[excel_reader] Error: {os.path.basename(file_path)} - {e}")
            continue

    if not all_dfs:
        print("[excel_reader] No data loaded")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=['data'], keep='first')
    combined = combined.sort_values('data').reset_index(drop=True)
    print(f"[excel_reader] Total: {len(combined)} days (fallback)")

    _cache['data'] = combined
    _cache['timestamp'] = now
    _cache['file_path'] = 'fallback'

    return combined


def _parse_date(val):
    """Parse dates robustly, handling irregular text like '28/092026'."""
    if pd.isna(val):
        return pd.NaT
    if isinstance(val, (pd.Timestamp, datetime)):
        return val
    s = str(val).strip()
    import re
    # Handle format like '28/092026' (dd/mmyyyy - missing second /)
    m = re.match(r'^(\d{1,2})/(\d{2})(\d{4})$', s)
    if m:
        try:
            return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except (ValueError, TypeError):
            pass
    # Handle 'dd/mm/yyyy'
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        try:
            return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except (ValueError, TypeError):
            pass
    # Fallback: let pandas try
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def get_dados_dia(data=None):
    """Get automatic line production data for a specific date.

    Checks database (producao_diaria) first, then falls back to Excel.
    Returns dict with keys: data, producao, embalagem, sleeve, celofane, meta, eficiencia
    """
    if data is None:
        data = datetime.now().date()
    elif isinstance(data, str):
        data = datetime.strptime(data, '%Y-%m-%d').date()

    data_str = data.strftime('%Y-%m-%d')
    meta = META_LINHA_AUTOMATICA

    # Check database first
    try:
        from database import get_db
        conn = get_db()
        row = conn.execute('SELECT * FROM producao_diaria WHERE data=?', (data_str,)).fetchone()
        conn.close()
        if row and (row['producao'] or 0) > 0:
            producao = row['producao'] or 0
            eficiencia = (producao / meta * 100) if meta > 0 else 0
            return {
                'data': data_str,
                'producao': producao,
                'embalagem': row['embalagem'] or 0,
                'sleeve': row['sleeve'] or 0,
                'celofane': row['celofane'] or 0,
                'meta': meta,
                'eficiencia': round(eficiencia, 1)
            }
    except Exception:
        pass

    # Fall back to Excel
    df = _load_excel_data()
    if df.empty:
        return {
            'data': data_str,
            'producao': 0, 'embalagem': 0, 'sleeve': 0, 'celofane': 0,
            'meta': meta, 'eficiencia': 0
        }

    mask = df['data'].dt.date == data
    row = df[mask]

    if row.empty:
        return {
            'data': data_str,
            'producao': 0, 'embalagem': 0, 'sleeve': 0, 'celofane': 0,
            'meta': meta, 'eficiencia': 0
        }

    r = row.iloc[0]
    producao = int(r['producao'])
    eficiencia = (producao / meta * 100) if meta > 0 else 0

    return {
        'data': data_str,
        'producao': producao,
        'embalagem': int(r['embalagem']),
        'sleeve': int(r['sleeve']),
        'celofane': int(r['celofane']),
        'meta': meta,
        'eficiencia': round(eficiencia, 1)
    }


def get_dados_semana(data_ref=None, dias=7):
    """Get automatic line data for the last N days.

    Returns list of dicts, one per day.
    """
    if data_ref is None:
        data_ref = datetime.now().date()
    elif isinstance(data_ref, str):
        data_ref = datetime.strptime(data_ref, '%Y-%m-%d').date()

    df = _load_excel_data()
    result = []

    start = data_ref - timedelta(days=dias - 1)
    for i in range(dias):
        day = start + timedelta(days=i)
        day_data = get_dados_dia(day)
        dia_semana = ['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB', 'DOM'][day.weekday()]
        day_data['dia_semana'] = dia_semana
        day_data['data'] = day.strftime('%Y-%m-%d')
        result.append(day_data)

    return result


def get_dados_mes(ano=None, mes=None):
    """Get automatic line data for the entire month.

    Returns list of dicts, one per day with data.
    """
    if ano is None or mes is None:
        hoje = datetime.now().date()
        ano = hoje.year
        mes = hoje.month

    # Try database first
    try:
        from database import get_db
        conn = get_db()
        prefix = f'{ano:04d}-{mes:02d}'
        rows = conn.execute(
            "SELECT * FROM producao_diaria WHERE data LIKE ? ORDER BY data ASC",
            (prefix + '%',)
        ).fetchall()
        conn.close()
        if rows:
            result = []
            for row in rows:
                producao = row['producao'] or 0
                if producao == 0:
                    continue
                meta = META_LINHA_AUTOMATICA
                eficiencia = (producao / meta * 100) if meta > 0 else 0
                result.append({
                    'data': row['data'],
                    'producao': producao,
                    'embalagem': row['embalagem'] or 0,
                    'sleeve': row['sleeve'] or 0,
                    'celofane': row['celofane'] or 0,
                    'meta': meta,
                    'eficiencia': round(eficiencia, 1)
                })
            if result:
                return result
    except Exception as e:
        print(f'[excel_reader] DB get_dados_mes error: {e}')

    # Fall back to Excel
    df = _load_excel_data()
    if df.empty:
        return []

    mask = (df['data'].dt.year == ano) & (df['data'].dt.month == mes)
    df_mes = df[mask].copy()

    result = []
    for _, r in df_mes.iterrows():
        producao = int(r['producao'])
        meta = META_LINHA_AUTOMATICA
        eficiencia = (producao / meta * 100) if meta > 0 else 0

        result.append({
            'data': r['data'].strftime('%Y-%m-%d'),
            'producao': producao,
            'embalagem': int(r['embalagem']),
            'sleeve': int(r['sleeve']),
            'celofane': int(r['celofane']),
            'meta': meta,
            'eficiencia': round(eficiencia, 1)
        })

    return result


def get_resumo_mes(ano=None, mes=None):
    """Get monthly summary for automatic line."""
    dados = get_dados_mes(ano, mes)
    if not dados:
        return {
            'total_producao': 0, 'total_meta': 0, 'eficiencia_media': 0,
            'dias_trabalhados': 0, 'melhor_dia': None, 'pior_dia': None
        }

    total_prod = sum(d['producao'] for d in dados)
    dias = len([d for d in dados if d['producao'] > 0])
    total_meta = dias * META_LINHA_AUTOMATICA
    eficiencia = (total_prod / total_meta * 100) if total_meta > 0 else 0

    dados_com_prod = [d for d in dados if d['producao'] > 0]
    melhor = max(dados_com_prod, key=lambda x: x['producao']) if dados_com_prod else None
    pior = min(dados_com_prod, key=lambda x: x['producao']) if dados_com_prod else None

    return {
        'total_producao': total_prod,
        'total_meta': total_meta,
        'eficiencia_media': round(eficiencia, 1),
        'dias_trabalhados': dias,
        'melhor_dia': melhor,
        'pior_dia': pior
    }


def get_absenteismo_dia(data=None):
    """Get absenteeism data for a specific date. Checks DB first, then Excel."""
    if data is None:
        data = datetime.now().date()
    elif isinstance(data, str):
        data = datetime.strptime(data, '%Y-%m-%d').date()

    data_str = data.strftime('%Y-%m-%d')
    empty = {
        'total_previstos': 0, 'total_ausentes': 0, 'total_presentes': 0,
        'taxa_geral': 0.0, 'turno': ''
    }

    # Check database first
    try:
        from database import get_db
        conn = get_db()
        row = conn.execute('SELECT * FROM producao_diaria WHERE data=?', (data_str,)).fetchone()
        conn.close()
        if row and row['total_colab'] and row['total_colab'] > 0:
            total = row['total_colab']
            ausentes = row['ausentes'] or 0
            return {
                'total_previstos': total,
                'total_ausentes': ausentes,
                'total_presentes': total - ausentes,
                'taxa_geral': round(ausentes / total * 100, 1) if total > 0 else 0.0,
                'turno': row['turno'] or '',
            }
    except Exception:
        pass

    # Fall back to Excel
    df = _load_excel_data()
    if df.empty:
        return empty

    mask = df['data'].dt.date == data
    row = df[mask]
    if row.empty:
        return empty

    r = row.iloc[0]
    total = int(r['total_colab'])
    ausentes = int(r['ausentes'])
    if total == 0:
        return empty

    return {
        'total_previstos': total,
        'total_ausentes': ausentes,
        'total_presentes': total - ausentes,
        'taxa_geral': round(ausentes / total * 100, 1) if total > 0 else 0.0,
        'turno': str(r['turno']),
    }


def get_absenteismo_semana(data_ref=None):
    """Get absenteeism data for the week from Excel Consolidado."""
    if data_ref is None:
        data_ref = datetime.now().date()
    elif isinstance(data_ref, str):
        data_ref = datetime.strptime(data_ref, '%Y-%m-%d').date()

    DIAS_SEMANA = {0: 'SEG', 1: 'TER', 2: 'QUA', 3: 'QUI', 4: 'SEX', 5: 'SÁB', 6: 'DOM'}
    start = data_ref - timedelta(days=data_ref.weekday())
    result = []

    for i in range(7):
        dia = start + timedelta(days=i)
        abs_dia = get_absenteismo_dia(dia)
        result.append({
            'data': dia.strftime('%Y-%m-%d'),
            'dia_semana': DIAS_SEMANA.get(dia.weekday(), ''),
            'taxa_geral': abs_dia['taxa_geral'],
            'total_previstos': abs_dia['total_previstos'],
            'total_ausentes': abs_dia['total_ausentes'],
            'total_presentes': abs_dia['total_presentes'],
            'turno': abs_dia['turno'],
        })

    return result


def _load_observations(force=False):
    """Load observations/justifications from sector tabs. Cached with TTL."""
    import openpyxl
    from collections import defaultdict

    now = time.time()
    if not force and _obs_cache['data'] is not None:
        if (now - _obs_cache['timestamp']) < EXCEL_CACHE_TTL:
            return _obs_cache['data']

    candidates = _find_latest_excel()
    if not candidates:
        return {}

    SECTOR_CONFIG = {
        'Envase': {'date_col': 2, 'obs_col': 6, 'label': 'Envase'},
        'Embalagem': {'date_col': 2, 'obs_col': 4, 'label': 'Embalagem'},
        'Sleeve': {'date_col': 2, 'obs_col': 4, 'label': 'Sleeve'},
        'celofane': {'date_col': 2, 'obs_col': 4, 'label': 'Celofane'},
        'Envase Manual': {'date_col': 1, 'obs_col': 7, 'label': 'Envase Manual'},
    }

    obs_by_date = defaultdict(list)

    for file_path in candidates:
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
            for tab_name, config in SECTOR_CONFIG.items():
                if tab_name not in wb.sheetnames:
                    continue
                ws = wb[tab_name]
                seen = set()
                for row in ws.iter_rows(min_row=2, values_only=False):
                    if len(row) < config['obs_col']:
                        continue
                    date_cell = row[config['date_col'] - 1]
                    obs_cell = row[config['obs_col'] - 1]
                    if date_cell.value is None:
                        continue
                    dt = date_cell.value
                    if isinstance(dt, str):
                        try:
                            dt = datetime.strptime(dt, '%Y-%m-%d')
                        except ValueError:
                            continue
                    if not hasattr(dt, 'strftime'):
                        continue
                    date_str = dt.strftime('%Y-%m-%d')
                    obs_text = str(obs_cell.value).strip() if obs_cell.value else ''
                    if not obs_text or obs_text.lower() in ('none', 'nan', ''):
                        continue
                    if obs_text.lower() in ('envase 01 e 02', 'envase 1 e 2'):
                        continue
                    key = (date_str, config['label'], obs_text)
                    if key in seen:
                        continue
                    seen.add(key)
                    obs_by_date[date_str].append({
                        'setor': config['label'],
                        'obs': obs_text,
                    })
            wb.close()
        except Exception as e:
            print(f"[excel_reader] Obs error: {os.path.basename(file_path)} - {e}")
            continue

    # Deduplicate across files
    result = {}
    for date_str, obs_list in obs_by_date.items():
        seen = set()
        unique = []
        for o in obs_list:
            k = (o['setor'], o['obs'])
            if k not in seen:
                seen.add(k)
                unique.append(o)
        result[date_str] = unique

    _obs_cache['data'] = result
    _obs_cache['timestamp'] = now
    return result


def get_observacoes_dia(data=None):
    """Get observations/justifications for a specific date. Merges DB + Excel."""
    if data is None:
        data = datetime.now().strftime('%Y-%m-%d')
    elif hasattr(data, 'strftime'):
        data = data.strftime('%Y-%m-%d')

    result = []
    seen = set()

    # Check database first
    try:
        from database import get_db
        conn = get_db()
        rows = conn.execute('SELECT * FROM observacoes_diarias WHERE data=?', (data,)).fetchall()
        conn.close()
        for r in rows:
            if r['observacao'] and r['observacao'].strip():
                key = (r['setor'], r['observacao'])
                seen.add(key)
                result.append({'setor': r['setor'], 'obs': r['observacao']})
    except Exception:
        pass

    # Also load from Excel (for historical data)
    obs_excel = _load_observations()
    for o in obs_excel.get(data, []):
        key = (o['setor'], o['obs'])
        if key not in seen:
            seen.add(key)
            result.append(o)

    return result


def get_pareto_problemas(ano, mes):
    """
    Reads ALL observations for the given month and classifies them into categories.
    Returns a list of dicts: [{'categoria': 'X', 'ocorrencias': N, 'percentual': P}]
    sorted descending by ocorrencias.
    """
    target_prefix = f"{ano:04d}-{mes:02d}"

    categorias_count = {
        'Maquinário / Manutenção': 0,
        'Falta de Material': 0,
        'Setup / Troca': 0,
        'Absenteismo': 0,
        'Qualidade': 0,
        'Outros': 0
    }

    total_obs = 0
    seen = set()

    def _classify_and_count(texto):
        nonlocal total_obs
        total_obs += 1
        if any(kw in texto for kw in ['maquin', 'equipamento', 'quebr', 'manuten', 'pane', 'falha', 'defeito', 'motor']):
            categorias_count['Maquinário / Manutenção'] += 1
        elif any(kw in texto for kw in ['material', 'falta de', 'insumo', 'embalagem', 'frasco', 'tampa']):
            categorias_count['Falta de Material'] += 1
        elif any(kw in texto for kw in ['setup', 'troca', 'ajust', 'regulagem']):
            categorias_count['Setup / Troca'] += 1
        elif any(kw in texto for kw in ['falt', 'ausent', 'atestado']):
            categorias_count['Absenteismo'] += 1
        elif any(kw in texto for kw in ['qualidade', 'retrabalh', 'rejeita', 'devolu']):
            categorias_count['Qualidade'] += 1
        else:
            categorias_count['Outros'] += 1

    # Check database observations first
    try:
        from database import get_db
        conn = get_db()
        db_rows = conn.execute(
            "SELECT * FROM observacoes_diarias WHERE data LIKE ?",
            (target_prefix + '%',)
        ).fetchall()
        conn.close()
        for r in db_rows:
            obs_text = (r['observacao'] or '').strip()
            if not obs_text:
                continue
            key = (r['data'], r['setor'], obs_text)
            if key in seen:
                continue
            seen.add(key)
            _classify_and_count(obs_text.lower())
    except Exception as e:
        print(f"[excel_reader] DB get_pareto_problemas error: {e}")

    # Fall back / merge with Excel observations
    obs_all = _load_observations()
    for date_str, obs_list in obs_all.items():
        if date_str.startswith(target_prefix):
            for o in obs_list:
                obs_text = (o.get('obs') or '').strip()
                if not obs_text:
                    continue
                key = (date_str, o.get('setor', ''), obs_text)
                if key in seen:
                    continue
                seen.add(key)
                _classify_and_count(obs_text.lower())

    # Format result
    result = []
    for cat, count in categorias_count.items():
        if count > 0:
            result.append({
                'categoria': cat,
                'ocorrencias': count,
                'percentual': round((count / total_obs * 100), 1) if total_obs > 0 else 0.0
            })

    # Sort descending
    result.sort(key=lambda x: x['ocorrencias'], reverse=True)

    return result
