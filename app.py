import sys
import os
import math
import json
import pandas as pd
import plotly.express as px

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from engine.planner import PlanificadorProduccion
from engine.exporter import generar_excel_plan

st.set_page_config(page_title="Plan de Producción Semanal MPS", layout="wide")

st.title("🏭 Planificador de Producción (Con Persistencia de Configuración)")

# --- FUNCIONES DE ARCHIVO DE CONFIGURACIÓN ---
CONFIG_FILE = os.path.join("config", "lineas_config.json")

def cargar_config_lineas():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def guardar_config_lineas(config_dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=4, ensure_ascii=False)

config_guardada = cargar_config_lineas()

# --- SIDEBAR ---
st.sidebar.header("🗓️ Configuración de Planificación")
semana_sel = st.sidebar.selectbox("Seleccionar Semana a Planificar", [1, 2, 3, 4, 5], index=0, format_func=lambda x: f"Semana {x}")

col_sb1, col_sb2 = st.sidebar.columns(2)
dias_objetivo = col_sb1.number_input("Días Mín. Objetivo", min_value=5, max_value=60, value=15)
dias_maximos = col_sb2.number_input("Días Máx. Stock", min_value=10, max_value=90, value=30)

# Carga de Datos
file_path_default = os.path.join("data", "datos_entrada.csv")
uploaded_file = st.file_uploader("Cargar archivo de entrada (CSV o Excel)", type=["csv", "xlsx"])

df_raw = None
if uploaded_file is not None:
    df_raw = pd.read_csv(uploaded_file, sep=None, engine='python') if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
elif os.path.exists(file_path_default):
    df_raw = pd.read_csv(file_path_default, sep=None, engine='python')
    st.info("ℹ️ Cargando automáticamente datos desde `data/datos_entrada.csv`.")

if df_raw is not None:
    lineas_disponibles = sorted(list(df_raw['Linea_Produccion'].astype(str).unique()))
    
    if 'pedidos_especiales' not in st.session_state:
        st.session_state['pedidos_especiales'] = []

    # --- SECCIÓN DE PEDIDOS ESPECIALES MANUALES ---
    with st.expander("📝 Inserción de Pedidos Especiales Manuales (Fuera de Demanda)", expanded=False):
        col_m1, col_m2, col_m3, col_m4 = st.columns([3, 2, 2, 1])
        sku_m_sel = col_m1.selectbox("Seleccionar SKU", options=sorted(df_raw['SKU'].astype(str).unique()), key="m_sku")
        linea_m_sel = col_m2.selectbox("Línea Asignada", options=lineas_disponibles, key="m_lin")
        cant_m_val = col_m3.number_input("Cantidad Extra (Unid)", min_value=100, value=5000, step=500, key="m_cant")
        
        if col_m4.button("➕ Agregar"):
            st.session_state['pedidos_especiales'].append({
                'SKU': sku_m_sel,
                'Linea': linea_m_sel,
                'Cantidad': cant_m_val
            })
            st.success(f"Pedido agregado: SKU {sku_m_sel} ({cant_m_val:,.0f} unid en {linea_m_sel})")

        if len(st.session_state['pedidos_especiales']) > 0:
            st.markdown("**Pedidos Especiales Agregados:**")
            df_m_disp = pd.DataFrame(st.session_state['pedidos_especiales'])
            st.dataframe(df_m_disp, use_container_width=True)
            if st.button("🗑️ Limpiar Pedidos Especiales"):
                st.session_state['pedidos_especiales'] = []
                st.rerun()

    # --- CONFIGURACIÓN OPERATIVA INDIVIDUAL POR LÍNEA ---
    with st.expander("⚙️ Configuración Operativa, Turnos y Tiempos de Setup por Línea", expanded=True):
        st.markdown("Configura los turnos, paros y los **tiempos de cambio (Setups) específicos** de cada línea de producción:")
        
        horas_lineas = {}
        paros_manuales = {}
        dias_lab_por_linea = {}
        setups_formato = {}
        setups_referencia = {}
        
        config_para_guardar = {}
        
        cols_l = st.columns(min(4, len(lineas_disponibles)))
        for idx, linea in enumerate(lineas_disponibles):
            c_lin = config_guardada.get(linea, {})
            
            with cols_l[idx % len(cols_l)]:
                st.subheader(f"📍 {linea}")
                
                # Valores por defecto leídos del JSON guardado (o valores base)
                def_dias = int(c_lin.get("dias_op", 5))
                def_turnos = int(c_lin.get("turnos_dia", 2))
                def_hrs = float(c_lin.get("hrs_turno", 8.0))
                def_sfmt = float(c_lin.get("s_fmt", 2.0))
                def_sref = float(c_lin.get("s_ref", 0.5))
                def_hm = float(c_lin.get("h_mant", 0.0))
                def_hc = float(c_lin.get("h_cap", 0.0))
                def_hf = float(c_lin.get("h_fer", 0.0))
                def_ho = float(c_lin.get("h_otr", 0.0))
                
                dias_op = st.number_input(f"Días laborables ({linea})", min_value=1, max_value=7, value=def_dias, key=f"d_{linea}")
                turnos_dia = st.number_input(f"Turnos por día ({linea})", min_value=1, max_value=3, value=def_turnos, key=f"t_{linea}")
                hrs_turno = st.selectbox(f"Horas por turno ({linea})", [8.0, 10.0, 12.0], index=[8.0, 10.0, 12.0].index(def_hrs) if def_hrs in [8.0, 10.0, 12.0] else 0, key=f"ht_{linea}")
                
                cap_bruta = dias_op * turnos_dia * hrs_turno
                st.markdown(f"🔹 **Cap. Bruta:** `{cap_bruta:.0f} hrs` *({dias_op}d × {turnos_dia}t × {hrs_turno:.0f}h)*")
                
                s_fmt = st.number_input(f"Cambio Formato ({linea}) h", min_value=0.0, max_value=12.0, value=def_sfmt, step=0.5, key=f"sfmt_{linea}")
                s_ref = st.number_input(f"Limpieza/Ref ({linea}) h", min_value=0.0, max_value=6.0, value=def_sref, step=0.1, key=f"sref_{linea}")
                
                h_mant = st.number_input(f"Mantenimiento ({linea}) h", min_value=0.0, value=def_hm, step=1.0, key=f"hm_{linea}")
                h_cap = st.number_input(f"Capacitaciones ({linea}) h", min_value=0.0, value=def_hc, step=1.0, key=f"hc_{linea}")
                h_fer = st.number_input(f"Feriados ({linea}) h", min_value=0.0, value=def_hf, step=1.0, key=f"hf_{linea}")
                h_otr = st.number_input(f"Otros Paros ({linea}) h", min_value=0.0, value=def_ho, step=1.0, key=f"ho_{linea}")
                
                paros_tot = h_mant + h_cap + h_fer + h_otr
                cap_neta = max(0.0, cap_bruta - paros_tot)
                
                horas_lineas[linea] = cap_bruta
                paros_manuales[linea] = paros_tot
                dias_lab_por_linea[linea] = dias_op
                setups_formato[linea] = s_fmt
                setups_referencia[linea] = s_ref
                
                config_para_guardar[linea] = {
                    "dias_op": dias_op,
                    "turnos_dia": turnos_dia,
                    "hrs_turno": hrs_turno,
                    "s_fmt": s_fmt,
                    "s_ref": s_ref,
                    "h_mant": h_mant,
                    "h_cap": h_cap,
                    "h_fer": h_fer,
                    "h_otr": h_otr
                }
                
                st.success(f"🟢 **Cap. Neta:** `{cap_neta:.1f} hrs`")

        st.divider()
        if st.button("💾 Guardar esta Configuración como Predeterminada"):
            guardar_config_lineas(config_para_guardar)
            st.success("✅ Configuración de líneas guardada permanentemente en `config/lineas_config.json`.")

    planificador = PlanificadorProduccion(
        dias_objetivo_stock=dias_objetivo,
        dias_maximos_stock=dias_maximos
    )
    
    df_res, horas_usadas = planificador.calcular_plan(
        df_raw,
        semana_seleccionada=semana_sel,
        horas_por_linea=horas_lineas,
        paros_manuales=paros_manuales,
        dias_laborables_por_linea=dias_lab_por_linea,
        setup_formato_por_linea=setups_formato,
        setup_referencia_por_linea=setups_referencia,
        ordenes_manuales=st.session_state['pedidos_especiales']
    )

    # KPIS METRICAS
    st.divider()
    col1, col2, col3, col4, col5 = st.columns(5)
    total_skus = len(df_res)
    skus_criticos = len(df_res[df_res['Prioridad_Num'] == 1])
    pedidos_esp = len(df_res[df_res['Prioridad_Num'] == 0])
    total_unidades = df_res['Sugerido_Final_Ajustado'].sum()
    total_hrs_prod = df_res['Horas_Asignadas'].sum()
    total_hrs_setups = df_res['Horas_Setup_Formato'].sum() + df_res['Horas_Setup_Referencia'].sum()

    col1.metric("SKUs Procesados", total_skus)
    col2.metric("Pedidos Especiales ⭐", pedidos_esp)
    col3.metric("Unidades a Fabricar", f"{total_unidades:,.0f}")
    col4.metric("Horas Producción Netas", f"{total_hrs_prod:.1f} h")
    col5.metric("Horas Totales Setups", f"{total_hrs_setups:.1f} h", delta_color="inverse")

    # TABLA CAPACIDAD
    st.subheader("⏱️ Resumen de Carga y Balanceo por Línea")
    cap_rows = []
    for linea in lineas_disponibles:
        h_bruta = horas_lineas[linea]
        paros = paros_manuales[linea]
        h_neta = max(0.0, h_bruta - paros)
        
        df_lin = df_res[df_res['Linea_Produccion'] == linea]
        h_prod = df_lin['Horas_Asignadas'].sum()
        h_setup = df_lin['Horas_Setup_Formato'].sum() + df_lin['Horas_Setup_Referencia'].sum()
        h_ocupadas_totales = h_prod + h_setup + paros
        
        pct_uso = (h_ocupadas_totales / h_bruta * 100) if h_bruta > 0 else 0.0
        
        cap_rows.append({
            "Línea": linea,
            "Capacidad Bruta (h)": h_bruta,
            "Paros Programados (h)": paros,
            "Capacidad Neta (h)": h_neta,
            "Horas Producción (h)": round(h_prod, 1),
            "Horas Setups (h)": round(h_setup, 1),
            "Ocupación Total (h)": round(h_ocupadas_totales, 1),
            "Ocupación (%)": f"{min(100.0, pct_uso):.1f}%",
            "Estado Capacidad": "🔴 Sobrecargada" if h_ocupadas_totales > h_bruta else "🟢 Disponible"
        })
        
    st.dataframe(pd.DataFrame(cap_rows), use_container_width=True)

    # TABLA SKUS QUE EXCEDEN CAPACIDAD
    df_excedidos = df_res[df_res['Estado_Produccion'] == 'Excede Capacidad'].copy()
    if len(df_excedidos) > 0:
        st.error(f"⚠️ **ATENCIÓN: Se detectaron {len(df_excedidos)} SKUs necesarios que EXCEDEN la capacidad de las líneas.**")
        
        df_excedidos['Acción Sugerida'] = df_excedidos.apply(
            lambda r: f"Programar Turno Extra el Sábado ({math.ceil(r['Horas_Requeridas'])}h)", axis=1
        )
        
        cols_exc = ['SKU', 'DESCRIPCION', 'Linea_Produccion', 'FORMATO', 'Prioridad_Nivel',
                    'Sugerido_Produccion_Lote', 'Horas_Requeridas', 'Acción Sugerida']
        
        st.dataframe(df_excedidos[cols_exc].style.format({
            'Sugerido_Produccion_Lote': '{:,.0f}',
            'Horas_Requeridas': '{:.1f}'
        }), use_container_width=True)

    # TABLA SECUENCIADA DE PRODUCCIÓN
    st.subheader(f"📋 Orden de Secuencia de Producción - Semana {semana_sel}")
    
    cols_mostrar = [
        'Orden_Secuencia', 'Linea_Produccion', 'SKU', 'DESCRIPCION', 'FORMATO', 'Prioridad_Nivel',
        'Hora_Inicio_Proyectada', 'Hora_Fin_Proyectada', 'Sugerido_Final_Ajustado',
        'Horas_Asignadas', 'Horas_Setup_Formato', 'Horas_Setup_Referencia', 'Estado_Produccion',
        'Inventario_Bodega', 'Produccion_EnCurso', 'Inventario_Final',
        'Demanda_Mensual', f'Demanda_Semana_{semana_sel}',
        'Dias_Stock_Actual_Mensual', 'Dias_Stock_Final_Mensual', 'Cumplimiento_Demanda_Mensual_%'
    ]
    
    df_programados = df_res[df_res['Sugerido_Final_Ajustado'] > 0].copy()

    st.dataframe(
        df_programados[cols_mostrar].style.format({
            'Orden_Secuencia': '{:.0f}',
            'Hora_Inicio_Proyectada': '{:.1f} h',
            'Hora_Fin_Proyectada': '{:.1f} h',
            'Inventario_Bodega': '{:,.0f}',
            'Produccion_EnCurso': '{:,.0f}',
            'Inventario_Final': '{:,.0f}',
            'Demanda_Mensual': '{:,.0f}',
            f'Demanda_Semana_{semana_sel}': '{:,.0f}',
            'Sugerido_Final_Ajustado': '{:,.0f}',
            'Horas_Asignadas': '{:.1f}',
            'Horas_Setup_Formato': '{:.1f}',
            'Horas_Setup_Referencia': '{:.1f}',
            'Dias_Stock_Actual_Mensual': '{:.1f}',
            'Dias_Stock_Final_Mensual': '{:.1f}',
            'Cumplimiento_Demanda_Mensual_%': '{:.1f}%'
        }),
        use_container_width=True
    )

    # BOTÓN DE DESCARGA A EXCEL
    excel_bytes = generar_excel_plan(df_res, horas_lineas)
    st.download_button(
        label="📊 Descargar Plan Completo en Excel (.xlsx)",
        data=excel_bytes,
        file_name=f"Plan_Produccion_Semana_{semana_sel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.warning("⚠️ No se encontraron datos. Sube tu archivo CSV/Excel o guarda `datos_entrada.csv` en la carpeta `data/`.")