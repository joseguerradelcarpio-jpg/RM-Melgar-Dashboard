import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import io
import statsmodels.api as sm # <-- NUEVA LÍNEA
import os # Añade esto junto a tus otros imports al inicio (pandas, numpy, etc.)
# =========================================================
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTADO DE SESIÓN
# =========================================================
st.set_page_config(page_title="FBC Melgar - Revenue Management Dashboard", layout="wide")

# Parámetros base con bono de novedad directo al IPM
default_params = {
    'h1': 0.40, 'h2': 0.25, 'h3': 0.15, 'h4': 0.10, 'h5': 0.10,
    'res_g': 1.0, 'res_e': 0.5, 'res_p': 0.0,
    'mod_visita_g': 0.15, 'mod_visita_e': 0.15, 'mod_local_e': -0.15, 'mod_local_p': -0.30,
    'premio_n3_g': 0.30, 'premio_n3_e': 0.15, 'castigo_n1_p': -0.30, 'castigo_n1_e': -0.15,
    'gol_activo': True, 'gol_umbral': 3, 'gol_bono': 0.10,
    'novedad_activo': True, 'novedad_bono': 0.15, 'novedad_limite': 1.05
}

if 'inicializado' not in st.session_state:
    for key, value in default_params.items():
        st.session_state[key] = value
    st.session_state['inicializado'] = True

def restablecer_valores():
    for key, value in default_params.items():
        st.session_state[key] = value

# =========================================================
# 2. PANEL LATERAL (CONTROLES Y PARAMETRIZACIÓN)
# =========================================================
st.sidebar.title("⚙️ Calibración del Modelo")
archivo_cargado = st.sidebar.file_uploader("Cargar Dataset Maestro (A-AY)", type=["xlsx"])
st.sidebar.button("🔄 Restablecer a Fórmula Base", on_click=restablecer_valores)

with st.sidebar.expander("1. Memoria de Corto Plazo (Pesos H1-H5)"):
    st.session_state.h1 = st.number_input("Peso H1 (Reciente)", value=st.session_state.h1, step=0.05)
    st.session_state.h2 = st.number_input("Peso H2", value=st.session_state.h2, step=0.05)
    st.session_state.h3 = st.number_input("Peso H3", value=st.session_state.h3, step=0.05)
    st.session_state.h4 = st.number_input("Peso H4", value=st.session_state.h4, step=0.05)
    st.session_state.h5 = st.number_input("Peso H5", value=st.session_state.h5, step=0.05)
    if round(sum([st.session_state.h1, st.session_state.h2, st.session_state.h3, st.session_state.h4, st.session_state.h5]), 2) != 1.0:
        st.sidebar.error("La suma de pesos debe ser 1.00")
        st.stop()

with st.sidebar.expander("2. Resultados Base y Condición"):
    st.session_state.res_g = st.number_input("Puntos por Victoria", value=st.session_state.res_g)
    st.session_state.res_e = st.number_input("Puntos por Empate", value=st.session_state.res_e)
    st.session_state.res_p = st.number_input("Puntos por Derrota", value=st.session_state.res_p)
    st.markdown("---")
    st.session_state.mod_visita_g = st.number_input("Bono Victoria Visita", value=st.session_state.mod_visita_g)
    st.session_state.mod_visita_e = st.number_input("Bono Empate Visita", value=st.session_state.mod_visita_e)
    st.session_state.mod_local_e = st.number_input("Castigo Empate Local", value=st.session_state.mod_local_e)
    st.session_state.mod_local_p = st.number_input("Castigo Derrota Local", value=st.session_state.mod_local_p)

with st.sidebar.expander("3. Modificadores por Nivel (Titanes vs Chicos)"):
    st.session_state.premio_n3_g = st.number_input("Bono Victoria vs Nivel 3", value=st.session_state.premio_n3_g)
    st.session_state.premio_n3_e = st.number_input("Bono Empate vs Nivel 3", value=st.session_state.premio_n3_e)
    st.session_state.castigo_n1_p = st.number_input("Castigo Derrota vs Nivel 1", value=st.session_state.castigo_n1_p)
    st.session_state.castigo_n1_e = st.number_input("Castigo Empate vs Nivel 1", value=st.session_state.castigo_n1_e)

with st.sidebar.expander("4. Modificadores Especiales"):
    st.session_state.gol_activo = st.checkbox("Activar Bono por Goleada", value=st.session_state.gol_activo)
    st.session_state.gol_umbral = st.number_input("Dif. de Goles Mínima", value=st.session_state.gol_umbral, step=1)
    st.session_state.gol_bono = st.number_input("Valor del Bono/Castigo Goleada", value=st.session_state.gol_bono, step=0.05)
    st.markdown("---")
    st.session_state.novedad_activo = st.checkbox("Activar Bono Debut Local", value=st.session_state.novedad_activo)
    st.session_state.novedad_bono = st.number_input("Bono Directo al IPM (Debut)", value=st.session_state.novedad_bono, step=0.05)
    st.session_state.novedad_limite = st.number_input("Límite/Techo Máximo", value=st.session_state.novedad_limite, step=0.05)

# =========================================================
# 3. MOTOR DE CÁLCULO DINÁMICO (IPM)
# =========================================================
@st.cache_data
def procesar_datos(df_raw, params):
    df = df_raw.copy()
    
    # 1. Limpieza RIGUROSA de todas las variables que se van a recalcular
    cols_a_borrar = [
        'local_H1', 'local_H2', 'local_H3', 'local_H4', 'local_H5',
        'visita_H1', 'visita_H2', 'visita_H3', 'visita_H4', 'visita_H5',
        'irr_local', 'irr_visita', 'ipm_local_5', 'ipm_visita_5', 
        'nivel_local', 'nivel_visita', 'goles_local', 'goles_visitante', 
        'res_local', 'res_visita'
    ]
    df = df.drop(columns=[c for c in cols_a_borrar if c in df.columns], errors='ignore')
    
    df = df.sort_values(by='fecha_real').reset_index(drop=True)
    df[['goles_local', 'goles_visitante']] = df['resultado'].str.split('-', expand=True)
    df['goles_local'] = pd.to_numeric(df['goles_local'].str.strip(), errors='coerce')
    df['goles_visitante'] = pd.to_numeric(df['goles_visitante'].str.strip(), errors='coerce')
    
    df['res_local'] = np.where(df['goles_local'] > df['goles_visitante'], 'G', np.where(df['goles_local'] == df['goles_visitante'], 'E', 'P'))
    df['res_visita'] = np.where(df['goles_visitante'] > df['goles_local'], 'G', np.where(df['goles_visitante'] == df['goles_local'], 'E', 'P'))

    # Tabla en la Sombra
    puntos = {}
    nivel_l, nivel_v = [], []
    titanes = ['Universitario', 'Alianza Lima', 'Sporting Cristal', 'Cienciano']
    
    for i, row in df.iterrows():
        y, loc, vis = row['año'], str(row['local']).strip(), str(row['visitante']).strip()
        if y not in puntos: puntos[y] = {}
        if loc not in puntos[y]: puntos[y][loc] = 0
        if vis not in puntos[y]: puntos[y][vis] = 0
        
        ranking = [x[0] for x in sorted(puntos[y].items(), key=lambda item: item[1], reverse=True)]
        
        def ev(eq, rank):
            if any(t in str(eq) for t in titanes): return 3
            if len(rank) < 15: return 2
            pos = rank.index(eq) + 1
            return 3 if pos <= 2 else (1 if pos >= len(rank)-4 else 2)

        nivel_l.append(ev(loc, ranking))
        nivel_v.append(ev(vis, ranking))
        
        gl, gv = row['goles_local'], row['goles_visitante']
        if gl > gv: puntos[y][loc] += 3
        elif gl == gv: puntos[y][loc] += 1; puntos[y][vis] += 1
        elif gv > gl: puntos[y][vis] += 3
            
    df['nivel_local'], df['nivel_visita'] = nivel_l, nivel_v

    def calc_irr(res, cond, nivel, gl, gv):
        pts = 0.0
        if res == 'G': 
            pts = params['res_g'] + (params['mod_visita_g'] if cond == 'Visita' else 0)
            pts += (nivel-1) * 0.15
        elif res == 'E': 
            pts = params['res_e'] + (params['mod_visita_e'] if cond == 'Visita' else params['mod_local_e'])
            pts += (nivel-2) * 0.15
        elif res == 'P': 
            pts = params['res_p'] + (params['mod_local_p'] if cond == 'Local' else 0)
            pts += (nivel-3) * 0.15
        
        if params['gol_activo']:
            dif = gl-gv if cond == 'Local' else gv-gl
            if dif >= params['gol_umbral']: pts += params['gol_bono']
            elif dif <= -params['gol_umbral']: pts -= params['gol_bono']
        return pts

    df['irr_local'] = df.apply(lambda r: calc_irr(r['res_local'], 'Local', r['nivel_visita'], r['goles_local'], r['goles_visitante']), axis=1)
    df['irr_visita'] = df.apply(lambda r: calc_irr(r['res_visita'], 'Visita', r['nivel_local'], r['goles_local'], r['goles_visitante']), axis=1)

    # Historial y Ponderación
    df_h = pd.concat([
        df[['fecha_real', 'local', 'irr_local']].rename(columns={'local':'eq', 'irr_local':'irr'}),
        df[['fecha_real', 'visitante', 'irr_visita']].rename(columns={'visitante':'eq', 'irr_visita':'irr'})
    ]).sort_values(by=['eq', 'fecha_real']).reset_index(drop=True)

    for i in range(1, 6): df_h[f'H{i}'] = df_h.groupby('eq')['irr'].shift(i)
    df_h.fillna(0, inplace=True)
    
    # Unir variables H para Local
    df = pd.merge(df, df_h[['fecha_real', 'eq', 'H1', 'H2', 'H3', 'H4', 'H5']], left_on=['fecha_real', 'local'], right_on=['fecha_real', 'eq'], how='left').drop('eq', axis=1)
    df.rename(columns={f'H{i}': f'local_H{i}' for i in range(1, 6)}, inplace=True)

    # Unir variables H para Visita
    df = pd.merge(df, df_h[['fecha_real', 'eq', 'H1', 'H2', 'H3', 'H4', 'H5']], left_on=['fecha_real', 'visitante'], right_on=['fecha_real', 'eq'], how='left').drop('eq', axis=1)
    df.rename(columns={f'H{i}': f'visita_H{i}' for i in range(1, 6)}, inplace=True)

    # Cálculo Final del IPM
    df['ipm_local_5'] = (df['local_H1']*params['h1']) + (df['local_H2']*params['h2']) + (df['local_H3']*params['h3']) + (df['local_H4']*params['h4']) + (df['local_H5']*params['h5'])
    df['ipm_visita_5'] = (df['visita_H1']*params['h1']) + (df['visita_H2']*params['h2']) + (df['visita_H3']*params['h3']) + (df['visita_H4']*params['h4']) + (df['visita_H5']*params['h5'])
    
    if params['novedad_activo']:
        debuts = df[df['local'] == 'FBC Melgar'].drop_duplicates(subset=['año'], keep='first').index
        for idx in debuts: df.loc[idx, 'ipm_local_5'] = min(df.loc[idx, 'ipm_local_5'] + params['novedad_bono'], params['novedad_limite'])

    return df

# =========================================================
# 4. RENDERIZADO INTERACTIVO (PLOTLY)
# =========================================================
st.title("📈 Dashboard Interactivo de Demanda")

archivo_por_defecto = 'Dataset_Tesis_8_Variables2.xlsx'

# Lógica de Carga Dual (Manual o Automática)
df_raw = None

if archivo_cargado is not None:
    # 1. Prioridad al archivo que suba el usuario manualmente
    df_raw = pd.read_excel(archivo_cargado)
    st.sidebar.success("✅ Archivo personalizado cargado.")
elif os.path.exists(archivo_por_defecto):
    # 2. Si no suben nada, lee el archivo precargado en el servidor
    df_raw = pd.read_excel(archivo_por_defecto)
    st.sidebar.info("ℹ️ Usando base de datos oficial por defecto.")
else:
    # 3. Mensaje de error si falta el archivo
    st.warning("⚠️ No se encontró la base de datos. Por favor, carga el archivo Excel en el panel lateral.")
    st.stop() # Detiene la ejecución para no mostrar errores feos

# Si hay datos (ya sea manuales o automáticos), arranca el motor
if df_raw is not None:
    df_proc = procesar_datos(df_raw, dict(st.session_state))
    
    # Filtro de Melgar Local con Asistencia
    df_g = df_proc[(df_proc['local'] == 'FBC Melgar') & (df_proc['Asistencia'].notna())].copy()
    df_g['año'] = df_g['año'].astype(str)
    df_g['Yield_Total'] = (df_g['Ingresos'] / df_g['Asistencia']).round(2)
    
    titanes = ['Universitario', 'Alianza Lima', 'Sporting Cristal', 'Cienciano']
    
    # Multiselect para Cross-Highlighting
    equipos_all = sorted(df_g['visitante'].unique())
    seleccionados = st.multiselect("🎯 Selecciona equipo(s) para resaltar sobre el fondo gris:", equipos_all)

    tab1, tab2, tab3, tab4 = st.tabs(["📉 Momentum", "📅 Calendario", "☀️ Confort Térmico", "🌧️ Shocks"])

    with tab1:
        c1, c2 = st.columns(2)
        paleta = {'2023': '#D32F2F', '2024': '#1976D2', '2025': '#388E3C', '2026': '#FF8F00'}
        
        def plot_master(df_subset, titulo):
            df_plot = df_subset.copy()
            
            # --- LIMPIEZA QUIRÚRGICA ---
            # Forzamos a que sean números, eliminamos errores y rellenamos vacíos con 0
            df_plot['Asistencia'] = pd.to_numeric(df_plot['Asistencia'], errors='coerce').fillna(0)
            df_plot['Ingresos'] = pd.to_numeric(df_plot['Ingresos'], errors='coerce').fillna(0)
            df_plot['Yield_Total'] = pd.to_numeric(df_plot['Yield_Total'], errors='coerce').fillna(0)

            # --- PREPARACIÓN DE TEXTO ---
            # Si el número es 0, aparecerá "S/ 0.00" en lugar de desaparecer
            df_plot['Texto_Yield'] = df_plot['Yield_Total'].apply(lambda x: f"{x:,.2f}")
            df_plot['Texto_Ingresos'] = df_plot['Ingresos'].apply(lambda x: f"{x:,.2f}")

            if seleccionados:
                df_plot['Es_Resaltado'] = df_plot['visitante'].isin(seleccionados)
                df_plot['Color_Final'] = np.where(df_plot['Es_Resaltado'], df_plot['año'], 'Otros')
                df_plot['Texto_Final'] = np.where(df_plot['Es_Resaltado'], df_plot['visitante'], '')
                cmap = {**paleta, 'Otros': '#E0E0E0'}
            else:
                df_plot['Color_Final'] = df_plot['año']
                df_plot['Texto_Final'] = df_plot['visitante']
                cmap = paleta

            fig = px.scatter(
                df_plot, x='ipm_local_5', y='Asistencia', 
                color='Color_Final', text='Texto_Final',
                color_discrete_map=cmap,
                title=titulo,
                custom_data=['Texto_Yield', 'factor_sol', 'Texto_Ingresos']
            )
            
            # === Lógica OLS (Igual que antes) ===
            df_trend = df_plot[['ipm_local_5', 'Asistencia']].dropna()
            if len(df_trend) > 2: 
                x_val = df_trend['ipm_local_5'].values
                y_val = df_trend['Asistencia'].values
                X_sm = sm.add_constant(x_val)
                modelo = sm.OLS(y_val, X_sm).fit()
                x_lin = np.linspace(x_val.min(), x_val.max(), 100)
                X_pred = sm.add_constant(x_lin)
                predicciones = modelo.get_prediction(X_pred)
                df_pred = predicciones.summary_frame(alpha=0.05)
                
                fig.add_trace(go.Scatter(
                    x=np.concatenate([x_lin, x_lin[::-1]]),
                    y=np.concatenate([df_pred['mean_ci_upper'], df_pred['mean_ci_lower'][::-1]]),
                    fill='toself', fillcolor='rgba(200, 200, 200, 0.4)', 
                    line=dict(color='rgba(255,255,255,0)'), hoverinfo="skip", showlegend=False
                ))
                fig.add_trace(go.Scatter(
                    x=x_lin, y=df_pred['mean'], mode='lines',
                    line=dict(color='black', width=2, dash='dash'),
                    hoverinfo="skip", showlegend=False
                ))
                fig.data = fig.data[-2:] + fig.data[:-2]

            # --- HOVER FINAL ---
            fig.update_traces(
                marker=dict(size=14, line=dict(width=1, color='black')),
                textposition='top right',
                hovertemplate="<b>%{text}</b><br>IPM: %{x:.2f}<br>Asist: %{y:,.0f}<br>Yield: S/ %{customdata[0]}<br>Sol: %{customdata[1]}<br>Ingresos: S/ %{customdata[2]}<extra></extra>"
            )
            
            fig.update_layout(height=600)
            return fig

        with c1: st.plotly_chart(plot_master(df_g[~df_g['visitante'].isin(titanes)], "Demanda Bajos"), use_container_width=True)
        with c2: st.plotly_chart(plot_master(df_g[df_g['visitante'].isin(titanes)], "Demanda Altos"), use_container_width=True)

        # Exportación conservando todas las columnas (A-AY+)
        st.markdown("### 💾 Exportar Dataset Maestro")
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        prefijo = st.text_input("Nombre del archivo (Presiona Enter)", "Dataset_Melgar_RM")
        
        # Eliminar solo columnas de cálculo interno para no ensuciar
        df_exp = df_proc.drop(columns=['goles_local', 'goles_visitante', 'res_local', 'res_visita', 'irr_local', 'irr_visita', 'nivel_local', 'nivel_visita'], errors='ignore')
        
        buf = io.BytesIO()
        df_exp.to_excel(buf, index=False, engine='openpyxl')
        st.download_button("Descargar Excel Calibrado", data=buf.getvalue(), file_name=f"{prefijo}_{fecha}.xlsx")

    with tab2:
        st.markdown("### Análisis de Calendario y Feriados")
        
        # FILTRO DINÁMICO POR EQUIPOS
        alta_demanda = ['Universitario', 'Alianza Lima', 'Sporting Cristal', 'Cienciano']
        equipos_disp_t2 = sorted(df_g['visitante'].unique())
        equipos_def_t2 = [e for e in equipos_disp_t2 if e not in alta_demanda]
        
        equipos_calendario = st.multiselect(
            "Filtro de Rivales (Calendario): Selecciona qué equipos analizar", 
            options=equipos_disp_t2, 
            default=equipos_def_t2,
            key="multiselect_tab2"
        )
        
        df_cal = df_g[df_g['visitante'].isin(equipos_calendario)].copy()
        
        if not df_cal.empty:
            df_cal['dia_semana'] = df_cal['dia_semana'].str.strip().str.lower()
            orden_dias = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
            df_cal['Tipo_Dia'] = np.where(df_cal['dia_semana'].isin(['sábado', 'domingo']), 'Fin de Semana', 'Día de Semana')
            
            c1, c2 = st.columns(2)
            
            with c1:
                fig_dias = px.box(
                    df_cal, x='dia_semana', y='Asistencia',
                    color='dia_semana',
                    category_orders={'dia_semana': orden_dias},
                    title="1. Distribución de Asistencia por Día",
                    points='all',
                    color_discrete_sequence=px.colors.qualitative.Safe
                )
                fig_dias.update_layout(showlegend=False, plot_bgcolor='white', xaxis_title=None, yaxis_title="Asistencia")
                fig_dias.update_xaxes(showgrid=True, gridcolor='lightgray')
                fig_dias.update_yaxes(showgrid=True, gridcolor='lightgray')
                st.plotly_chart(fig_dias, use_container_width=True)
                st.markdown("**Resumen:** Los miércoles y jueves representan el valle crítico de asistencia orgánica, mientras que el domingo consolida el pico natural de demanda con la mayor mediana.")
                
            with c2:
                fig_macro = px.box(
                    df_cal, x='Tipo_Dia', y='Asistencia',
                    color='Tipo_Dia',
                    title="2. Impacto Agregado: Fin de Semana vs Día Laborable",
                    points='all',
                    color_discrete_sequence=['#4CAF50', '#FF5722']
                )
                fig_macro.update_layout(showlegend=False, plot_bgcolor='white', xaxis_title=None, yaxis_title="Asistencia")
                fig_macro.update_xaxes(showgrid=True, gridcolor='lightgray')
                fig_macro.update_yaxes(showgrid=True, gridcolor='lightgray')
                st.plotly_chart(fig_macro, use_container_width=True)
                st.markdown("**Resumen:** Jugar en fin de semana eleva drásticamente la base de asistencia garantizada, evidenciando un alto costo de oportunidad al programar partidos en días laborables.")
            
            st.markdown("---")
            
            # ANÁLISIS DE FERIADOS LARGOS Aislando Fines de Semana
            if 'feriado_largo' in df_cal.columns:
                df_cal['Es_Feriado'] = np.where(df_cal['feriado_largo'] == 1, 'Feriado Largo', 'Fin de Semana Normal')
                df_finde = df_cal[df_cal['Tipo_Dia'] == 'Fin de Semana'].copy()
                
                if not df_finde.empty:
                    fig_feriado = px.box(
                        df_finde, x='Es_Feriado', y='Asistencia',
                        color='Es_Feriado',
                        title="3. Costo de Oportunidad: Feriado Largo vs Fin de Semana Normal",
                        points='all',
                        color_discrete_sequence=['#9C27B0', '#00BCD4']
                    )
                    fig_feriado.update_layout(showlegend=False, plot_bgcolor='white', xaxis_title=None, yaxis_title="Asistencia Orgánica")
                    fig_feriado.update_xaxes(showgrid=True, gridcolor='lightgray')
                    fig_feriado.update_yaxes(showgrid=True, gridcolor='lightgray')
                    
                    _, col_centro, _ = st.columns([1, 2, 1])
                    with col_centro:
                        st.plotly_chart(fig_feriado, use_container_width=True)
                        st.markdown("**Resumen:** Coincidir con un feriado largo reduce la mediana de asistencia frente a un fin de semana regular, confirmando la fuga de demanda local por viajes o turismo emisivo.")
        else:
            st.warning("Por favor, selecciona al menos un equipo en el filtro superior.")
        
    with tab3:
        st.markdown("### Análisis de Confort Térmico y Migración")
        
        # FILTRO DINÁMICO POR EQUIPOS
        equipos_disp = sorted(df_g['visitante'].unique())
        # Por defecto seleccionamos a todos los equipos orgánicos (excluyendo Titanes)
        equipos_def = [e for e in equipos_disp if e not in titanes]
        
        equipos_clima = st.multiselect(
            "Filtro de Rivales: Selecciona qué equipos analizar en este entorno térmico", 
            options=equipos_disp, 
            default=equipos_def
        )
        
        df_clima = df_g[df_g['visitante'].isin(equipos_clima)].copy()
        
        if not df_clima.empty and 'factor_sol' in df_clima.columns:
            df_clima['factor_sol'] = df_clima['factor_sol'].fillna('Desconocido')
            df_clima = df_clima[df_clima['factor_sol'] != 'Desconocido']
            orden_clima = ['Sol Intenso', 'Transición Sombra', 'Noche']
            
            c1, c2 = st.columns(2)
            
            with c1:
                fig_total = px.box(
                    df_clima, x='factor_sol', y='Asistencia', 
                    color='factor_sol', category_orders={'factor_sol': orden_clima},
                    title="1. Impacto en Asistencia Total",
                    color_discrete_sequence=['#FFC107', '#FF9800', '#3F51B5']
                )
                fig_total.update_layout(showlegend=False, plot_bgcolor='white', xaxis_title=None, yaxis_title="Asistencia")
                st.plotly_chart(fig_total, use_container_width=True)
                
            with c2:
                # Normalización manual para porcentajes
                tribunas = ['asistentes_sur', 'asistentes_oriente', 'asistentes_occidente']
                df_prom = df_clima.groupby('factor_sol')[tribunas].mean()
                df_norm = df_prom.div(df_prom.sum(axis=1), axis=0) * 100
                df_norm = df_norm.reset_index()
                
                df_melt = df_norm.melt(id_vars='factor_sol', value_vars=tribunas, var_name='Tribuna', value_name='Porcentaje')
                df_melt['Tribuna'] = df_melt['Tribuna'].str.replace('asistentes_', '').str.capitalize()
                
                # Crear columna de texto formateado para que aparezca dentro de la barra
                df_melt['Texto_Etiqueta'] = df_melt['Porcentaje'].apply(lambda x: f"{x:.1f}%")
                
                fig_share = px.bar(
                    df_melt, x='factor_sol', y='Porcentaje', color='Tribuna',
                    category_orders={'factor_sol': orden_clima},
                    title="2. Distribución y Migración (%)",
                    barmode='stack',
                    text='Texto_Etiqueta',
                    color_discrete_map={'Sur': '#F44336', 'Oriente': '#4CAF50', 'Occidente': '#2196F3'}
                )
                fig_share.update_layout(plot_bgcolor='white', yaxis=dict(range=[0, 100]), xaxis_title=None)
                fig_share.update_traces(textposition='inside', textfont_size=12)
                st.plotly_chart(fig_share, use_container_width=True)
                
            st.markdown("""
            ### 💡 Conclusión del Análisis
            El análisis general muestra la clara migración de la tribuna Oriente hacia otras zonas y la menor asistencia total cuando los partidos se juegan expuestos al sol.
            """)
        else:
            st.warning("No hay datos suficientes para los filtros seleccionados.")

    with tab4: 
        st.info("Espacio reservado para medir el impacto de la Temporada de Lluvias y la fuga de demanda en Feriados Largos.")

else:
    st.warning("👈 Por favor, carga tu archivo Excel en el panel lateral para iniciar el simulador.")
