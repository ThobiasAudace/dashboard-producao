"""
Dashboard Diretoria — Flask Application

Independent web application for executive production monitoring.
Consolidates data from Automatic Line (Excel), Manual Line (SQLite),
absenteeism, and safety metrics (days without accidents).
"""

import os
import sys

# Ensure the dashboard_diretoria directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta, date

from database import init_db, DATABASE_URL
from data_sources import excel_reader, manual_line, factory_metrics, whatsapp_sender
from config import META_LINHA_AUTOMATICA, META_LINHA_MANUAL, AUTO_REFRESH_SECONDS, FLASK_PORT, get_meta_periodo

# SQL param placeholder: ? for SQLite, %s for PostgreSQL
P = '%s' if DATABASE_URL else '?'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Initialize dashboard database
init_db()

DIAS_SEMANA_PT = {
    0: 'Segunda', 1: 'Terça', 2: 'Quarta',
    3: 'Quinta', 4: 'Sexta', 5: 'Sábado', 6: 'Domingo'
}

# Reference: 30/09/2026 = Caio. Alternates daily.
TURNO_REF_DATE = date(2026, 9, 30)  # Caio
TURNOS = ['Caio', 'Douglas']


def get_turno_do_dia(data_ref=None):
    """Determine which shift (Caio/Douglas) for a given date."""
    if data_ref is None:
        data_ref = date.today()
    elif isinstance(data_ref, str):
        data_ref = datetime.strptime(data_ref, '%Y-%m-%d').date()
    elif isinstance(data_ref, datetime):
        data_ref = data_ref.date()
    delta = (data_ref - TURNO_REF_DATE).days
    # Even delta = Caio, Odd = Douglas
    return TURNOS[abs(delta) % 2]


def format_number(value):
    """Format number with Brazilian thousands separator."""
    try:
        n = int(value)
        return f'{n:,}'.replace(',', '.')
    except (ValueError, TypeError):
        return value


app.jinja_env.filters['fmt'] = format_number
app.jinja_env.globals['auto_refresh'] = AUTO_REFRESH_SECONDS


# ========== MAIN DASHBOARD ==========

@app.route('/')
def dashboard():
    """Main executive dashboard page."""
    hoje_real = datetime.now()

    # Date filter: ?data=YYYY-MM-DD (defaults to today)
    data_param = request.args.get('data')
    if data_param:
        try:
            data_ref = datetime.strptime(data_param, '%Y-%m-%d')
        except ValueError:
            data_ref = hoje_real
    else:
        data_ref = hoje_real

    data_str = data_ref.strftime('%Y-%m-%d')
    data_display = data_ref.strftime('%d/%m/%Y')
    dia_semana = DIAS_SEMANA_PT.get(data_ref.weekday(), '')
    data_input = data_ref.strftime('%Y-%m-%d')  # for the date picker

    # -- KPI: Days without accidents (always from today) --
    seguranca = factory_metrics.get_dias_sem_acidente()

    # -- KPI: Automatic line (selected date) --
    auto_hoje = excel_reader.get_dados_dia(data_ref.date())
    auto_semana = excel_reader.get_dados_semana(data_ref.date())
    auto_resumo_mes = excel_reader.get_resumo_mes(data_ref.year, data_ref.month)

    if data_ref.month == 1:
        prev_year, prev_month = data_ref.year - 1, 12
    else:
        prev_year, prev_month = data_ref.year, data_ref.month - 1
    auto_resumo_mes_anterior = excel_reader.get_resumo_mes(prev_year, prev_month)
    
    dias_decorridos = data_ref.day
    auto_mes_anterior = excel_reader.get_dados_mes(prev_year, prev_month)
    def _get_day(dt):
        if hasattr(dt, 'day'):
            return dt.day
        try:
            return int(str(dt)[8:10])
        except:
            return 0
    mes_ant_mesmo_periodo = sum(d['producao'] for d in auto_mes_anterior if _get_day(d['data']) <= dias_decorridos)
    # Projection calculation for auto
    dias_trabalhados_auto = auto_resumo_mes.get('dias_trabalhados', 0)
    total_prod_atual_auto = auto_resumo_mes.get('total_producao', 0)
    if dias_trabalhados_auto > 0:
        projecao_mes_auto = (total_prod_atual_auto / dias_trabalhados_auto) * 22
    else:
        projecao_mes_auto = 0

    # -- KPI: Manual line (selected date) --
    manual_hoje = manual_line.get_dados_dia(data_str)
    manual_semana = manual_line.get_dados_semana(data_ref.date())
    manual_resumo_mes = manual_line.get_resumo_mes(data_ref.year, data_ref.month)
    manual_produtos = manual_line.get_produtos_dia(data_str)

    # Enrich weekly data with per-day metas
    for d in manual_semana:
        d_str = d.get('data', '')
        if d_str:
            m = get_meta_periodo(int(d_str[:4]), int(d_str[5:7]), data_str=d_str)
            d['meta_dia'] = m['manual']
        else:
            d['meta_dia'] = meta_manual

    for d in auto_semana:
        d_str = d.get('data', '')
        if d_str:
            m = get_meta_periodo(int(d_str[:4]), int(d_str[5:7]), data_str=d_str)
            d['meta_dia'] = m['auto']
        else:
            d['meta_dia'] = meta_auto

    # -- KPI: Absenteeism (selected date, from Excel) --
    absenteismo_hoje = excel_reader.get_absenteismo_dia(data_str)
    absenteismo_semana = excel_reader.get_absenteismo_semana(data_ref.date())

    metas_mes = get_meta_periodo(data_ref.year, data_ref.month, data_str=data_str)
    meta_auto = metas_mes['auto']
    meta_manual = metas_mes['manual']
    meta_sleeve = metas_mes.get('sleeve', 0)

    # -- Observations/Justifications (when below target) --
    abaixo_meta = (auto_hoje['producao'] > 0 and auto_hoje['producao'] < meta_auto) or \
                  (manual_hoje['finalizados'] > 0 and manual_hoje['finalizados'] < meta_manual)
    observacoes_dia = excel_reader.get_observacoes_dia(data_str) if abaixo_meta else []

    # -- Full month table with production per person --
    auto_mes = excel_reader.get_dados_mes(data_ref.year, data_ref.month)
    historico_completo = []
    
    turno_comparativo = {
        'Caio': {'dias': 0, 'total': 0, 'media': 0, 'melhor_dia': {'producao': 0, 'data': ''}, 'pior_dia': {'producao': float('inf'), 'data': ''}, 'historico': []},
        'Douglas': {'dias': 0, 'total': 0, 'media': 0, 'melhor_dia': {'producao': 0, 'data': ''}, 'pior_dia': {'producao': float('inf'), 'data': ''}, 'historico': []},
    }
    
    for d in auto_mes:
        dt = d['data']
        if hasattr(dt, 'strftime'):
            dt_str = dt.strftime('%Y-%m-%d')
        else:
            dt_str = str(dt)[:10]
        turno = get_turno_do_dia(dt_str)

        # Get absenteeism from Excel Consolidado
        abs_dia = excel_reader.get_absenteismo_dia(dt_str)
        presentes = abs_dia.get('total_presentes', 0)
        producao = d['producao']
        prod_por_pessoa = round(producao / presentes, 1) if presentes > 0 else None
        
        if producao > 0:
            turno_comparativo[turno]['dias'] += 1
            turno_comparativo[turno]['total'] += producao
            if producao > turno_comparativo[turno]['melhor_dia']['producao']:
                turno_comparativo[turno]['melhor_dia'] = {'producao': producao, 'data': dt_str[8:] + '/' + dt_str[5:7]}
            if producao < turno_comparativo[turno]['pior_dia']['producao']:
                turno_comparativo[turno]['pior_dia'] = {'producao': producao, 'data': dt_str[8:] + '/' + dt_str[5:7]}

        # Get per-day sleeve meta
        d_meta = get_meta_periodo(int(dt_str[:4]), int(dt_str[5:7]), data_str=dt_str)
        sleeve_meta = d_meta.get('sleeve', 0)
        sleeve_val = d['sleeve']
        sleeve_efi = round(sleeve_val / sleeve_meta * 100, 1) if sleeve_meta > 0 and sleeve_val > 0 else 0

        # Get Sleeve observation if below meta
        sleeve_obs = ''
        if sleeve_meta > 0 and sleeve_val < sleeve_meta:
            obs_dia = excel_reader.get_observacoes_dia(dt_str)
            sleeve_obs_list = [o['obs'] for o in obs_dia if o.get('setor') == 'Sleeve']
            sleeve_obs = '; '.join(sleeve_obs_list) if sleeve_obs_list else ''

        historico_completo.append({
            'data': dt_str,
            'dia_semana': DIAS_SEMANA_PT.get(datetime.strptime(dt_str, '%Y-%m-%d').weekday(), ''),
            'turno': turno,
            'producao': producao,
            'embalagem': d['embalagem'],
            'sleeve': sleeve_val,
            'celofane': d['celofane'],
            'meta': d['meta'],
            'eficiencia': d['eficiencia'],
            'presentes': presentes,
            'prod_por_pessoa': prod_por_pessoa,
            'sleeve_meta': sleeve_meta,
            'sleeve_eficiencia': sleeve_efi,
            'sleeve_obs': sleeve_obs,
        })
        
    for t in ['Caio', 'Douglas']:
        if turno_comparativo[t]['dias'] > 0:
            turno_comparativo[t]['media'] = int(turno_comparativo[t]['total'] / turno_comparativo[t]['dias'])

    pareto_problemas = excel_reader.get_pareto_problemas(data_ref.year, data_ref.month)

    # Build per-day metas map for the month (for charts)
    import calendar
    dias_no_mes = calendar.monthrange(data_ref.year, data_ref.month)[1]
    metas_por_dia = {}
    for day in range(1, dias_no_mes + 1):
        ds = f'{data_ref.year}-{data_ref.month:02d}-{day:02d}'
        m = get_meta_periodo(data_ref.year, data_ref.month, data_str=ds)
        metas_por_dia[ds] = {'auto': m['auto'], 'manual': m['manual'], 'sleeve': m.get('sleeve', 0)}

    return render_template(
        'dashboard.html',
        data_display=data_display,
        dia_semana=dia_semana,
        data_input=data_input,
        data_hoje=hoje_real.strftime('%Y-%m-%d'),
        turno_dia=get_turno_do_dia(data_ref),
        seguranca=seguranca,
        auto_hoje=auto_hoje,
        auto_semana=auto_semana,
        auto_resumo_mes=auto_resumo_mes,
        auto_resumo_mes_anterior=auto_resumo_mes_anterior,
        mes_anterior_mesmo_periodo=mes_ant_mesmo_periodo,
        dias_decorridos=dias_decorridos,
        projecao_mes_auto=projecao_mes_auto,
        manual_hoje=manual_hoje,
        manual_semana=manual_semana,
        manual_resumo_mes=manual_resumo_mes,
        manual_produtos=manual_produtos,
        absenteismo_hoje=absenteismo_hoje,
        absenteismo_semana=absenteismo_semana,
        meta_auto=meta_auto,
        meta_manual=meta_manual,
        metas_por_dia=metas_por_dia,
        historico_completo=historico_completo,
        observacoes_dia=observacoes_dia,
        prev_month_name=['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'][prev_month - 1],
        curr_month_name=['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'][data_ref.month - 1],
        turno_comparativo=turno_comparativo,
        pareto_problemas=pareto_problemas,
    )


@app.route('/relatorio-pdf')
def relatorio_pdf():
    hoje_real = datetime.now()
    data_param = request.args.get('data')
    if data_param:
        try:
            data_ref = datetime.strptime(data_param, '%Y-%m-%d')
        except ValueError:
            data_ref = hoje_real
    else:
        data_ref = hoje_real

    data_str = data_ref.strftime('%Y-%m-%d')
    
    seguranca = factory_metrics.get_dias_sem_acidente()
    auto_resumo_mes = excel_reader.get_resumo_mes(data_ref.year, data_ref.month)
    manual_resumo_mes = manual_line.get_resumo_mes(data_ref.year, data_ref.month)
    
    metas_mes = get_meta_periodo(data_ref.year, data_ref.month)
    meta_auto = metas_mes['auto']
    meta_manual = metas_mes['manual']

    auto_mes = excel_reader.get_dados_mes(data_ref.year, data_ref.month)
    historico_completo = []
    for d in auto_mes:
        dt = d['data']
        if hasattr(dt, 'strftime'):
            dt_str = dt.strftime('%Y-%m-%d')
        else:
            dt_str = str(dt)[:10]
        turno = get_turno_do_dia(dt_str)
        abs_dia = excel_reader.get_absenteismo_dia(dt_str)
        presentes = abs_dia.get('total_presentes', 0)
        historico_completo.append({
            'data': dt_str,
            'dia_semana': DIAS_SEMANA_PT.get(datetime.strptime(dt_str, '%Y-%m-%d').weekday(), ''),
            'turno': turno,
            'producao': d['producao'],
            'presentes': presentes,
            'meta': d['meta']
        })

    response = render_template(
        'relatorio.html',
        data_ref=data_ref,
        mes_nome=['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'][data_ref.month - 1],
        seguranca=seguranca,
        auto_resumo_mes=auto_resumo_mes,
        manual_resumo_mes=manual_resumo_mes,
        meta_auto=meta_auto,
        meta_manual=meta_manual,
        historico_completo=historico_completo
    )
    
    filename = f"relatorio_{data_ref.year}_{data_ref.month:02d}.html"
    return response, 200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

# ========== API ENDPOINTS (for AJAX auto-refresh) ==========

def _parse_data_param():
    """Parse ?data= query parameter, defaulting to today."""
    data_param = request.args.get('data')
    if data_param:
        try:
            return datetime.strptime(data_param, '%Y-%m-%d')
        except ValueError:
            pass
    return datetime.now()


@app.route('/api/whatsapp-message')
def api_whatsapp_message():
    """JSON endpoint returning formatted WhatsApp message."""
    data_ref = _parse_data_param()
    data_str = data_ref.strftime('%Y-%m-%d')
    try:
        msg = whatsapp_sender.gerar_mensagem_whatsapp(data_str)
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/semana')
def api_semana():
    """JSON endpoint returning weekly data for auto + manual lines, with configurable period."""
    data_ref = _parse_data_param()
    dias = request.args.get('dias', 7, type=int)
    if dias not in (7, 15, 30):
        dias = 7

    auto_sem = excel_reader.get_dados_semana(data_ref.date(), dias=dias)
    manual_sem = manual_line.get_dados_semana(data_ref.date(), dias=dias)

    # Enrich with per-day metas
    for d in auto_sem:
        d_str = d.get('data', '')
        if d_str:
            m = get_meta_periodo(int(d_str[:4]), int(d_str[5:7]), data_str=d_str)
            d['meta_dia'] = m['auto']

    for d in manual_sem:
        d_str = d.get('data', '')
        if d_str:
            m = get_meta_periodo(int(d_str[:4]), int(d_str[5:7]), data_str=d_str)
            d['meta_dia'] = m['manual']

    return jsonify({'auto_semana': auto_sem, 'manual_semana': manual_sem, 'dias': dias})


@app.route('/api/dados-dia')
def api_dados_dia():
    """JSON endpoint with data for a specific date."""
    data_ref = _parse_data_param()
    data_str = data_ref.strftime('%Y-%m-%d')

    return jsonify({
        'data': data_str,
        'seguranca': factory_metrics.get_dias_sem_acidente(),
        'linha_automatica': excel_reader.get_dados_dia(data_ref.date()),
        'linha_manual': manual_line.get_dados_dia(data_str),
        'absenteismo': factory_metrics.get_absenteismo_dia(data_str),
    })


@app.route('/api/historico')
def api_historico():
    """JSON endpoint with weekly/monthly history for the selected date."""
    data_ref = _parse_data_param()

    return jsonify({
        'auto_semana': excel_reader.get_dados_semana(data_ref.date()),
        'manual_semana': manual_line.get_dados_semana(data_ref.date()),
        'auto_mes': excel_reader.get_dados_mes(data_ref.year, data_ref.month),
        'manual_mes': manual_line.get_dados_mes(data_ref.year, data_ref.month),
        'absenteismo_semana': factory_metrics.get_absenteismo_semana(data_ref.date()),
    })


# ========== ADMIN PAGE ==========

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """Admin page for recording absenteeism, accidents, and manual line production."""
    hoje = datetime.now().strftime('%Y-%m-%d')

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'absenteismo':
            data = request.form.get('data', hoje)
            turno = get_turno_do_dia(data)
            total_turno = int(request.form.get('total_turno', 0))
            ausentes = int(request.form.get('ausentes', 0))
            presentes = total_turno - ausentes
            observacao = request.form.get('observacao', '')

            factory_metrics.salvar_absenteismo(data, turno, total_turno, presentes, observacao)
            flash(f'Absenteísmo registrado! Turno {turno}: {ausentes} ausente(s) de {total_turno}.', 'success')

        elif form_type == 'acidente':
            data = request.form.get('data_acidente', hoje)
            descricao = request.form.get('descricao', '')
            gravidade = request.form.get('gravidade', 'leve')

            factory_metrics.registrar_acidente(data, descricao, gravidade)
            flash('Acidente registrado. Contador de dias resetado.', 'warning')

        elif form_type == 'envase_manual':
            data = request.form.get('data', hoje)
            mensagem = request.form.get('mensagem', '')

            if mensagem.strip():
                # Parse WhatsApp message
                parsed = manual_line.parse_whatsapp_message(mensagem)

                # Use date from message header if available
                if parsed.get('data_extraida'):
                    data = parsed['data_extraida']

                if parsed['produtos'] or parsed['total_envasados'] > 0 or parsed['total_finalizados'] > 0 or parsed['total_retrabalhadas'] > 0:
                    manual_line.salvar_producao_manual(
                        data,
                        parsed['produtos'],
                        parsed['total_envasados'],
                        parsed['total_finalizados'],
                        observacao=mensagem[:200],
                        total_retrabalhadas=parsed['total_retrabalhadas'],
                    )

                    # Save extracted observation to observacoes_diarias
                    obs_texto = parsed.get('observacao')
                    if obs_texto:
                        from database import get_db
                        conn = get_db()
                        conn.execute(
                            'INSERT OR IGNORE INTO observacoes_diarias (data, setor, observacao) VALUES (?, ?, ?)',
                            (data, 'Envase Manual', obs_texto)
                        )
                        conn.commit()
                        conn.close()

                    data_display = f"{data[8:]}/{data[5:7]}/{data[:4]}"
                    retrab_msg = f', Retrabalhadas: {parsed["total_retrabalhadas"]:,}'.replace(',', '.') if parsed['total_retrabalhadas'] > 0 else ''
                    obs_msg = f' | Obs: {obs_texto}' if obs_texto else ''
                    flash(
                        f'Envase Manual registrado para {data_display}! '
                        f'{len(parsed["produtos"])} produto(s), '
                        f'Envasados: {parsed["total_envasados"]:,}, '
                        f'Finalizados: {parsed["total_finalizados"]:,}{retrab_msg}{obs_msg}'.replace(',', '.'),
                        'success'
                    )
                else:
                    flash('Não foi possível extrair dados da mensagem. Verifique o formato.', 'danger')
            else:
                # Manual input (without WhatsApp message)
                total_env = int(request.form.get('total_envasados', 0))
                total_fin = int(request.form.get('total_finalizados', 0))
                manual_line.salvar_producao_manual(data, [], total_env, total_fin)
                flash(f'Totais registrados manualmente!', 'success')

        elif form_type == 'metas_periodo':
            ano = int(request.form.get('ano', datetime.now().year))
            from database import get_db
            conn = get_db()
            for mes in range(1, 13):
                auto = request.form.get(f'meta_auto_{mes}')
                manual = request.form.get(f'meta_manual_{mes}')
                sleeve = request.form.get(f'meta_sleeve_{mes}', '0')
                if auto and manual:
                    try:
                        conn.execute('''
                            INSERT INTO metas_periodo (ano, mes, meta_automatica, meta_manual, meta_sleeve)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(ano, mes) DO UPDATE SET
                                meta_automatica=excluded.meta_automatica,
                                meta_manual=excluded.meta_manual,
                                meta_sleeve=excluded.meta_sleeve
                        ''', (ano, mes, int(auto), int(manual), int(sleeve or 0)))
                    except Exception as e:
                        print("Error updating metas:", e)
            conn.commit()
            conn.close()
            flash('Metas atualizadas com sucesso!', 'success')

        return redirect(url_for('admin'))

    # GET
    seguranca = factory_metrics.get_dias_sem_acidente()
    absenteismo = factory_metrics.get_absenteismo_dia(hoje)
    historico_acidentes = factory_metrics.get_historico_acidentes()

    # Manual line: recent records
    manual_hoje = manual_line.get_dados_dia(hoje)
    manual_produtos_hoje = manual_line.get_produtos_dia(hoje)

    turno_hoje = get_turno_do_dia()

    # Metas
    ano_atual = datetime.now().year
    metas_ano = []
    for m in range(1, 13):
        metas_ano.append(get_meta_periodo(ano_atual, m))

    return render_template(
        'admin.html',
        hoje=hoje,
        turno_hoje=turno_hoje,
        seguranca=seguranca,
        absenteismo=absenteismo,
        historico_acidentes=historico_acidentes,
        manual_hoje=manual_hoje,
        manual_produtos_hoje=manual_produtos_hoje,
        ano_atual=ano_atual,
        metas_ano=metas_ano,
    )


@app.route('/admin/delete-manual/<data>', methods=['POST'])
def delete_manual(data):
    """Delete manual line records for a specific date."""
    manual_line.deletar_producao_dia(data)
    flash(f'Registros do envase manual de {data} excluídos.', 'info')
    return redirect(url_for('admin'))


# ===== LANCAMENTO (Production Data Entry) =====
@app.route('/lancamento', methods=['GET', 'POST'])
def lancamento():
    """Mobile-friendly form for shift leaders to enter daily production data."""
    from database import get_db
    import json

    if request.method == 'POST':
        data = request.form.get('data')
        turno = request.form.get('turno', '')

        def parse_int(val):
            """Parse int from form, handling Brazilian format (20.000 → 20000)."""
            if not val:
                return 0
            return int(str(val).replace('.', '').replace(',', '').strip() or 0)

        # Auto line
        producao = parse_int(request.form.get('producao'))
        embalagem_val = parse_int(request.form.get('embalagem'))
        sleeve_val = parse_int(request.form.get('sleeve'))
        celofane_val = parse_int(request.form.get('celofane'))

        # Absenteeism
        total_colab = parse_int(request.form.get('total_colab'))
        ausentes_val = parse_int(request.form.get('ausentes'))

        conn = get_db()
        try:
            # Save automatic line + absenteeism (upsert)
            if DATABASE_URL:
                conn.cursor().execute(f'''
                    INSERT INTO producao_diaria 
                    (data, producao, embalagem, sleeve, celofane, turno, total_colab, ausentes, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                    ON CONFLICT (data) DO UPDATE SET
                    producao=EXCLUDED.producao, embalagem=EXCLUDED.embalagem, sleeve=EXCLUDED.sleeve,
                    celofane=EXCLUDED.celofane, turno=EXCLUDED.turno, total_colab=EXCLUDED.total_colab,
                    ausentes=EXCLUDED.ausentes, updated_at=CURRENT_TIMESTAMP
                ''', (data, producao, embalagem_val, sleeve_val, celofane_val, turno,
                      total_colab if total_colab > 0 else None,
                      ausentes_val if total_colab > 0 else None))
            else:
                conn.execute('''
                    INSERT OR REPLACE INTO producao_diaria 
                    (data, producao, embalagem, sleeve, celofane, turno, total_colab, ausentes, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ''', (data, producao, embalagem_val, sleeve_val, celofane_val, turno,
                      total_colab if total_colab > 0 else None,
                      ausentes_val if total_colab > 0 else None))

            # Save manual line products
            manual_json = request.form.get('manual_produtos_json', '[]')
            produtos = json.loads(manual_json) if manual_json else []

            if produtos:
                conn.execute(f"DELETE FROM producao_manual WHERE data={P}", (data,))
                conn.execute(f"DELETE FROM producao_manual_totais WHERE data={P}", (data,))

                total_env = 0
                total_fin = 0
                for p in produtos:
                    nome = p.get('produto', '').strip()
                    env = parse_int(p.get('envasados'))
                    fin = parse_int(p.get('finalizados'))
                    if nome and (env > 0 or fin > 0):
                        conn.execute(f'''
                            INSERT INTO producao_manual (data, produto, envasados, finalizados)
                            VALUES ({P},{P},{P},{P})
                        ''', (data, nome, env, fin))
                        total_env += env
                        total_fin += fin

                if total_env > 0 or total_fin > 0:
                    if DATABASE_URL:
                        conn.cursor().execute('''
                            INSERT INTO producao_manual_totais (data, total_envasados, total_finalizados)
                            VALUES (%s,%s,%s) ON CONFLICT (data) DO UPDATE SET
                            total_envasados=EXCLUDED.total_envasados, total_finalizados=EXCLUDED.total_finalizados
                        ''', (data, total_env, total_fin))
                    else:
                        conn.execute('''
                            INSERT OR REPLACE INTO producao_manual_totais 
                            (data, total_envasados, total_finalizados) VALUES (?,?,?)
                        ''', (data, total_env, total_fin))

            # Save observations
            setores_obs = ['Envase', 'Embalagem', 'Sleeve', 'Celofane', 'Envase Manual']
            for setor in setores_obs:
                obs_val = request.form.get(f'obs_{setor.lower().replace(" ", "_")}', '').strip()
                if obs_val:
                    if DATABASE_URL:
                        conn.cursor().execute('''
                            INSERT INTO observacoes_diarias (data, setor, observacao)
                            VALUES (%s,%s,%s) ON CONFLICT (data, setor) DO UPDATE SET observacao=EXCLUDED.observacao
                        ''', (data, setor, obs_val))
                    else:
                        conn.execute('''
                            INSERT OR REPLACE INTO observacoes_diarias (data, setor, observacao)
                            VALUES (?,?,?)
                        ''', (data, setor, obs_val))

            conn.commit()
            flash(f'Produção de {data[8:]}/{data[5:7]} salva com sucesso!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao salvar: {str(e)}', 'danger')
        finally:
            conn.close()

        return redirect(url_for('lancamento', data=data))

    # GET - show form
    data_param = request.args.get('data', datetime.now().strftime('%Y-%m-%d'))

    # Load existing data for this date
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM producao_diaria WHERE data={P}', (data_param,))
    existing = cur.fetchone()
    cur.execute(f'SELECT * FROM producao_manual WHERE data={P} ORDER BY id', (data_param,))
    manual_prods = cur.fetchall()
    cur.execute(f'SELECT * FROM observacoes_diarias WHERE data={P}', (data_param,))
    obs_rows = cur.fetchall()
    conn.close()

    if DATABASE_URL:
        import psycopg2.extras
        obs_dict = {r['setor']: r['observacao'] for r in obs_rows} if obs_rows else {}
        existing = dict(existing) if existing else None
        manual_prods = [dict(r) for r in manual_prods] if manual_prods else []
    else:
        obs_dict = {r['setor']: r['observacao'] for r in obs_rows}
        manual_prods = [dict(r) for r in manual_prods]

    return render_template('lancamento.html',
        data_input=data_param,
        existing=existing,
        manual_prods=manual_prods,
        obs_dict=obs_dict,
    )


if __name__ == '__main__':
    print(f"\n{'='*60}")
    print(f"  Dashboard Diretoria - Fábrica de Perfumes")
    print(f"  Acesse: http://localhost:{FLASK_PORT}")
    print(f"  Admin:  http://localhost:{FLASK_PORT}/admin")
    print(f"  Lançamento: http://localhost:{FLASK_PORT}/lancamento")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=True)
