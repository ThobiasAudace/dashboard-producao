import datetime
from data_sources import excel_reader, manual_line, factory_metrics
from config import get_meta_periodo

DIAS_SEMANA_PT = {
    0: 'Segunda', 1: 'Terça', 2: 'Quarta',
    3: 'Quinta', 4: 'Sexta', 5: 'Sábado', 6: 'Domingo'
}
TURNO_REF_DATE = datetime.date(2026, 9, 30)
TURNOS = ['Caio', 'Douglas']

def get_turno_do_dia(data_ref):
    if isinstance(data_ref, str):
        data_ref = datetime.datetime.strptime(data_ref, '%Y-%m-%d').date()
    elif isinstance(data_ref, datetime.datetime):
        data_ref = data_ref.date()
    delta = (data_ref - TURNO_REF_DATE).days
    return TURNOS[abs(delta) % 2]

def format_number(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except:
        return value

def gerar_mensagem_whatsapp(data_str):
    data_ref = datetime.datetime.strptime(data_str, '%Y-%m-%d')
    dia_semana = DIAS_SEMANA_PT.get(data_ref.weekday(), '')
    turno = get_turno_do_dia(data_str)
    
    # Auto
    auto_hoje = excel_reader.get_dados_dia(data_ref.date())
    # Manual
    manual_hoje = manual_line.get_dados_dia(data_str)
    # Metas
    metas_mes = get_meta_periodo(data_ref.year, data_ref.month)
    meta_auto = metas_mes['auto']
    meta_manual = metas_mes['manual']
    
    # Calc var auto
    var_auto = ((auto_hoje['producao'] - meta_auto) / meta_auto * 100) if meta_auto > 0 else 0
    icone_auto = "✅" if var_auto >= 0 else "🔴"
    sinal_auto = "+" if var_auto >= 0 else ""
    
    # Calc var manual
    var_manual = ((manual_hoje['finalizados'] - meta_manual) / meta_manual * 100) if meta_manual > 0 else 0
    icone_manual = "✅" if var_manual >= 0 else "🔴"
    sinal_manual = "+" if var_manual >= 0 else ""
    
    # Absenteismo
    absenteismo_hoje = factory_metrics.get_absenteismo_dia(data_str)
    presentes = absenteismo_hoje.get('total_presentes', 0)
    previstos = absenteismo_hoje.get('total_previstos', 0)
    taxa_abs = absenteismo_hoje.get('taxa_geral', 0)
    
    # Segurança
    seguranca = factory_metrics.get_dias_sem_acidente()
    dias_seg = seguranca.get('dias', 0)
    
    # Justificativas
    abaixo_meta = (auto_hoje['producao'] > 0 and auto_hoje['producao'] < meta_auto) or \
                  (manual_hoje['finalizados'] > 0 and manual_hoje['finalizados'] < meta_manual)
    observacoes_dia = excel_reader.get_observacoes_dia(data_str) if abaixo_meta else []
    
    data_display = data_ref.strftime('%d/%m/%Y')
    
    msg = f"🏭 *RELATÓRIO DE PRODUÇÃO*\n"
    msg += f"📅 {data_display} ({dia_semana}) | Turno: {turno}\n\n"
    
    msg += f"🔵 *LINHA AUTOMÁTICA*\n"
    msg += f"Produção: {format_number(auto_hoje['producao'])} un\n"
    msg += f"Meta: {format_number(meta_auto)} un\n"
    msg += f"Resultado: {icone_auto} {sinal_auto}{var_auto:.1f}%\n\n".replace('.', ',')
    
    msg += f"🟢 *LINHA MANUAL*\n"
    msg += f"Finalizados: {format_number(manual_hoje['finalizados'])} un\n"
    msg += f"Envasados: {format_number(manual_hoje['envasados'])} un\n"
    msg += f"Meta: {format_number(meta_manual)} un\n"
    msg += f"Resultado: {icone_manual} {sinal_manual}{var_manual:.1f}%\n\n".replace('.', ',')
    
    msg += f"👥 *ABSENTEÍSMO*\n"
    msg += f"Presentes: {presentes} de {previstos} ({taxa_abs:.1f}%)\n\n".replace('.', ',')
    
    msg += f"🛡️ Dias sem acidente: {dias_seg}\n"
    
    if observacoes_dia:
        msg += f"\n⚠️ *JUSTIFICATIVAS:*\n"
        for obs in observacoes_dia:
            msg += f"- {obs['setor']}: {obs['obs']}\n"
            
    return msg
