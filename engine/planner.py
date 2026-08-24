import pandas as pd
import numpy as np
import math

class PlanificadorProduccion:
    def __init__(self, dias_objetivo_stock=15, dias_maximos_stock=30, horas_disponibles_semanales=120.0,
                 tiempo_cambio_formato_hrs=2.0, tiempo_cambio_referencia_hrs=0.5):
        self.dias_objetivo = dias_objetivo_stock
        self.dias_maximos = dias_maximos_stock
        self.horas_disponibles_default = horas_disponibles_semanales
        self.tiempo_cambio_formato_default = tiempo_cambio_formato_hrs
        self.tiempo_cambio_referencia_default = tiempo_cambio_referencia_hrs

    def _limpiar_numero(self, val):
        if pd.isna(val):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).replace(',', '.').strip()
        try:
            return float(val_str)
        except ValueError:
            return 0.0

    def calcular_plan(self, df_skus, semana_seleccionada=1, horas_por_linea=None, paros_manuales=None,
                      dias_laborables_por_linea=None, setup_formato_por_linea=None, setup_referencia_por_linea=None,
                      dias_objetivo=None, dias_maximos=None, ordenes_manuales=None):
        
        if dias_objetivo is not None:
            self.dias_objetivo = dias_objetivo
        if dias_maximos is not None:
            self.dias_maximos = dias_maximos
            
        df = df_skus.copy()
        
        col_formato = None
        for posible_col in ['FORMATO', 'FORMA1', 'Formato', 'formato']:
            if posible_col in df.columns:
                col_formato = posible_col
                break
        if col_formato is None:
            df['FORMATO'] = 'Único'
        else:
            df['FORMATO'] = df[col_formato].astype(str)

        columnas_num = ['Inventario_Bodega', 'Produccion_EnCurso', 'Inventario_Final', 'Inventario_Actual',
                        'Unidades_Por_Hora', 'Lote_Minimo',
                        'Demanda_Semana_1', 'Demanda_Semana_2', 'Demanda_Semana_3',
                        'Demanda_Semana_4', 'Demanda_Semana_5', 'Demanda_Mensual']
        
        for col in columnas_num:
            if col in df.columns:
                df[col] = df[col].apply(self._limpiar_numero)

        if 'Inventario_Final' in df.columns:
            df['Inventario_Bodega'] = df['Inventario_Bodega'].apply(self._limpiar_numero)
            df['Produccion_EnCurso'] = df['Produccion_EnCurso'].apply(self._limpiar_numero)
            df['Inventario_Final'] = df['Inventario_Final'].apply(self._limpiar_numero)
            df['Inventario_Actual'] = df['Inventario_Final']
        elif 'Inventario_Bodega' in df.columns:
            df['Inventario_Bodega'] = df['Inventario_Bodega'].apply(self._limpiar_numero)
            df['Produccion_EnCurso'] = df.get('Produccion_EnCurso', 0).apply(self._limpiar_numero)
            df['Inventario_Final'] = df['Inventario_Bodega'] + df['Produccion_EnCurso']
            df['Inventario_Actual'] = df['Inventario_Final']
        else:
            df['Inventario_Actual'] = df['Inventario_Actual'].apply(self._limpiar_numero)
            df['Inventario_Bodega'] = df['Inventario_Actual']
            df['Produccion_EnCurso'] = 0.0
            df['Inventario_Final'] = df['Inventario_Actual']

        w = semana_seleccionada
        w_next = (w + 1) if w < 5 else 1
        
        df['Demanda_Sem_Actual'] = df[f'Demanda_Semana_{w}'].apply(lambda x: max(0.0, x))
        df['Demanda_Sem_Siguiente'] = df[f'Demanda_Semana_{w_next}'].apply(lambda x: max(0.0, x))
        
        if 'Demanda_Mensual' in df.columns:
            df['Demanda_Mensual_Clean'] = df['Demanda_Mensual'].apply(lambda x: max(0.0, x))
        else:
            df['Demanda_Mensual_Clean'] = 999999.0

        semanas_restantes = [f'Demanda_Semana_{k}' for k in range(w, 6) if f'Demanda_Semana_{k}' in df.columns]
        df['Demanda_Restante_Mes'] = df[semanas_restantes].sum(axis=1).apply(lambda x: max(0.0, x))
        
        df['Demanda_Ventana_2Sem'] = df['Demanda_Sem_Actual'] + df['Demanda_Sem_Siguiente']
        
        lineas_unicas = df['Linea_Produccion'].unique()
        if dias_laborables_por_linea is None:
            dias_laborables_por_linea = {str(linea): 5.0 for linea in lineas_unicas}
            
        # Venta diaria específica basada en los días laborables INDEPENDIENTES de cada línea
        df['Dias_Laborables_Linea'] = df['Linea_Produccion'].apply(lambda l: float(dias_laborables_por_linea.get(str(l), 5.0)))
        df['Venta_Diaria_Sem_Actual'] = df['Demanda_Sem_Actual'] / df['Dias_Laborables_Linea']
        
        df['Dias_Mes_Linea'] = df['Dias_Laborables_Linea'] * 4.0
        df['Venta_Diaria_Mensual'] = np.where(
            df['Demanda_Mensual_Clean'] > 0,
            df['Demanda_Mensual_Clean'] / df['Dias_Mes_Linea'],
            df['Venta_Diaria_Sem_Actual']
        )
        
        df['Dias_Stock_Actual_Mensual'] = np.where(
            df['Venta_Diaria_Mensual'] > 0,
            df['Inventario_Final'] / df['Venta_Diaria_Mensual'],
            np.where(df['Inventario_Final'] > 0, 999.0, 0.0)
        )
        df['Dias_Stock_Actual'] = df['Dias_Stock_Actual_Mensual']
        
        df['Stock_Objetivo_Unid'] = self.dias_objetivo * df['Venta_Diaria_Mensual']
        df['Stock_Maximo_Unid'] = self.dias_maximos * df['Venta_Diaria_Mensual']
        
        df['Requerimiento_Total_Ventana'] = df['Demanda_Ventana_2Sem'] + df['Stock_Objetivo_Unid']

        # CLASIFICACIÓN DINÁMICA DE PRIORIDAD Y RIESGO
        prioridad_num = []
        prioridad_label = []
        
        for idx, row in df.iterrows():
            inv = row['Inventario_Final']
            d_act = row['Demanda_Sem_Actual']
            d_req_tot = row['Requerimiento_Total_Ventana']
            d_rest = row['Demanda_Restante_Mes']
            d_mensual = row['Demanda_Mensual_Clean']
            
            if d_mensual <= 0 or (w < 5 and d_rest <= 0):
                prioridad_num.append(4)
                prioridad_label.append('🟢 BAJA / NULA (Sin Demanda Futura)')
            elif inv < d_act:
                prioridad_num.append(1)
                prioridad_label.append('🔴 CRÍTICA (Déficit Semana Actual)')
            elif inv < d_req_tot:
                prioridad_num.append(2)
                prioridad_label.append('🟠 ALTA (Bajo Stock Mín. Objetivo)')
            else:
                prioridad_num.append(3)
                prioridad_label.append('🟡 MEDIA (Stock Suficiente)')
                
        df['Prioridad_Num'] = prioridad_num
        df['Prioridad_Nivel'] = prioridad_label
        
        # CÁLCULO DE NECESIDAD BRUTA Y SUGERIDO POR LOTE
        df['Deficit_Ventana'] = np.maximum(0.0, df['Requerimiento_Total_Ventana'] - df['Inventario_Final'])
        
        df['Necesidad_Bruta'] = df.apply(
            lambda r: min(r['Deficit_Ventana'], r['Demanda_Restante_Mes']) if r['Prioridad_Num'] < 4 else 0.0,
            axis=1
        )
        
        df['Sugerido_Produccion_Lote'] = df.apply(
            lambda r: math.ceil(r['Necesidad_Bruta'] / r['Lote_Minimo']) * r['Lote_Minimo']
            if r['Necesidad_Bruta'] > 0 and r['Lote_Minimo'] > 0 else 0,
            axis=1
        )

        # ÓRDENES MANUALES (PRIORIDAD 0)
        if ordenes_manuales is not None and len(ordenes_manuales) > 0:
            for ord_m in ordenes_manuales:
                sku_m = str(ord_m['SKU'])
                cant_m = float(ord_m['Cantidad'])
                linea_m = str(ord_m.get('Linea', ''))
                
                mask = df['SKU'].astype(str) == sku_m
                if mask.any():
                    df.loc[mask, 'Prioridad_Num'] = 0
                    df.loc[mask, 'Prioridad_Nivel'] = '⭐ PEDIDO ESPECIAL (Manual)'
                    df.loc[mask, 'Sugerido_Produccion_Lote'] = cant_m
                    if linea_m:
                        df.loc[mask, 'Linea_Produccion'] = linea_m

        # SECUENCIAMIENTO POR CAMPAÑAS DE FORMATO
        fmt_summary = df.groupby(['Linea_Produccion', 'FORMATO']).agg(
            Prio_Min=('Prioridad_Num', 'min'),
            Stock_Min=('Dias_Stock_Actual_Mensual', 'min')
        ).reset_index()

        fmt_summary = fmt_summary.sort_values(
            by=['Linea_Produccion', 'Prio_Min', 'Stock_Min', 'FORMATO'],
            ascending=[True, True, True, True]
        )
        
        fmt_summary['Orden_Formato_Linea'] = fmt_summary.groupby('Linea_Produccion').cumcount() + 1
        
        df = df.merge(fmt_summary[['Linea_Produccion', 'FORMATO', 'Orden_Formato_Linea']], on=['Linea_Produccion', 'FORMATO'], how='left')

        df = df.sort_values(
            by=['Linea_Produccion', 'Orden_Formato_Linea', 'Prioridad_Num', 'Dias_Stock_Actual_Mensual'],
            ascending=[True, True, True, True]
        ).reset_index(drop=True)

        # Ajuste a Techo de Días Máximos de Stock
        for idx, row in df.iterrows():
            if row['Prioridad_Num'] == 0:
                continue
                
            sug = row['Sugerido_Produccion_Lote']
            lote_min = row['Lote_Minimo']
            inv_act = row['Inventario_Final']
            dem_act = row['Demanda_Sem_Actual']
            v_diaria_m = row['Venta_Diaria_Mensual']
            
            if sug > 0 and v_diaria_m > 0 and lote_min > 0:
                inv_proyectado = inv_act - dem_act + sug
                dias_proyectados_m = inv_proyectado / v_diaria_m
                
                while dias_proyectados_m > self.dias_maximos and (sug - lote_min) >= 0:
                    sug_nuevo = sug - lote_min
                    inv_proj_nuevo = inv_act - dem_act + sug_nuevo
                    if inv_proj_nuevo < dem_act:
                        break
                    sug = sug_nuevo
                    dias_proyectados_m = inv_proj_nuevo / v_diaria_m
                
                df.at[idx, 'Sugerido_Produccion_Lote'] = sug

        # ASIGNACIÓN CRONOLÓGICA CON SETUPS INDIVIDUALES POR LÍNEA
        df['Horas_Requeridas'] = df.apply(
            lambda r: r['Sugerido_Produccion_Lote'] / r['Unidades_Por_Hora']
            if r['Unidades_Por_Hora'] > 0 else 0.0,
            axis=1
        )
        
        if horas_por_linea is None:
            horas_por_linea = {str(linea): self.horas_disponibles_default for linea in lineas_unicas}
        if paros_manuales is None:
            paros_manuales = {str(linea): 0.0 for linea in lineas_unicas}
        if setup_formato_por_linea is None:
            setup_formato_por_linea = {str(linea): self.tiempo_cambio_formato_default for linea in lineas_unicas}
        if setup_referencia_por_linea is None:
            setup_referencia_por_linea = {str(linea): self.tiempo_cambio_referencia_default for linea in lineas_unicas}
            
        df['Sugerido_Final_Ajustado'] = 0
        df['Horas_Asignadas'] = 0.0
        df['Horas_Setup_Formato'] = 0.0
        df['Horas_Setup_Referencia'] = 0.0
        df['Orden_Secuencia'] = 0
        df['Hora_Inicio_Proyectada'] = 0.0
        df['Hora_Fin_Proyectada'] = 0.0
        df['Estado_Produccion'] = 'No Programado'
        
        horas_acumuladas = {}
        secuencia_contador = {str(linea): 1 for linea in lineas_unicas}
        
        for linea in lineas_unicas:
            linea_str = str(linea)
            cap_bruta = horas_por_linea.get(linea_str, self.horas_disponibles_default)
            paros = paros_manuales.get(linea_str, 0.0)
            horas_acumuladas[linea_str] = paros
            
        ultimo_formato_linea = {str(linea): None for linea in lineas_unicas}
        ultimo_sku_linea = {str(linea): None for linea in lineas_unicas}
        
        for idx, row in df.iterrows():
            linea = str(row['Linea_Produccion'])
            formato_actual = str(row['FORMATO'])
            sku_actual = str(row['SKU'])
            prio_num = row['Prioridad_Num']
            
            capacidad_bruta = horas_por_linea.get(linea, self.horas_disponibles_default)
            hrs_prod_neta = row['Horas_Requeridas']
            sugerido_lote = int(row['Sugerido_Produccion_Lote'])
            
            t_setup_fmt_linea = setup_formato_por_linea.get(linea, self.tiempo_cambio_formato_default)
            t_setup_ref_linea = setup_referencia_por_linea.get(linea, self.tiempo_cambio_referencia_default)
            
            if prio_num == 4:
                df.at[idx, 'Estado_Produccion'] = 'Sin Demanda Futura'
                continue

            if sugerido_lote == 0:
                df.at[idx, 'Estado_Produccion'] = 'Stock Suficiente'
                continue
            
            hrs_setup_fmt = 0.0
            hrs_setup_ref = 0.0
            
            if ultimo_formato_linea[linea] is not None:
                if ultimo_formato_linea[linea] != formato_actual:
                    hrs_setup_fmt = t_setup_fmt_linea
                elif ultimo_sku_linea[linea] != sku_actual:
                    hrs_setup_ref = t_setup_ref_linea
                    
            hrs_totales_item = hrs_prod_neta + hrs_setup_fmt + hrs_setup_ref
            hrs_inicio = horas_acumuladas.get(linea, 0.0)
            
            if hrs_inicio + hrs_totales_item <= capacidad_bruta:
                hrs_fin = hrs_inicio + hrs_totales_item
                horas_acumuladas[linea] = hrs_fin
                ultimo_formato_linea[linea] = formato_actual
                ultimo_sku_linea[linea] = sku_actual
                
                df.at[idx, 'Sugerido_Final_Ajustado'] = sugerido_lote
                df.at[idx, 'Horas_Asignadas'] = hrs_prod_neta
                df.at[idx, 'Horas_Setup_Formato'] = hrs_setup_fmt
                df.at[idx, 'Horas_Setup_Referencia'] = hrs_setup_ref
                df.at[idx, 'Orden_Secuencia'] = secuencia_contador[linea]
                df.at[idx, 'Hora_Inicio_Proyectada'] = hrs_inicio
                df.at[idx, 'Hora_Fin_Proyectada'] = hrs_fin
                df.at[idx, 'Estado_Produccion'] = 'Programado OK (Pedido Especial)' if prio_num == 0 else 'Programado OK'
                
                secuencia_contador[linea] += 1
            else:
                unidades_un_lote = row['Lote_Minimo']
                hrs_un_lote = unidades_un_lote / row['Unidades_Por_Hora'] if row['Unidades_Por_Hora'] > 0 else 0
                
                tiempo_remoto = capacidad_bruta - hrs_inicio - hrs_setup_fmt - hrs_setup_ref
                lotes_posibles = int(tiempo_remoto // hrs_un_lote) if (tiempo_remoto > 0 and hrs_un_lote > 0) else 0
                
                if lotes_posibles > 0:
                    sug_parcial = int(lotes_posibles * unidades_un_lote)
                    hrs_parcial = sug_parcial / row['Unidades_Por_Hora']
                    hrs_fin = hrs_inicio + hrs_parcial + hrs_setup_fmt + hrs_setup_ref
                    
                    horas_acumuladas[linea] = hrs_fin
                    ultimo_formato_linea[linea] = formato_actual
                    ultimo_sku_linea[linea] = sku_actual
                    
                    df.at[idx, 'Sugerido_Final_Ajustado'] = sug_parcial
                    df.at[idx, 'Horas_Asignadas'] = hrs_parcial
                    df.at[idx, 'Horas_Setup_Formato'] = hrs_setup_fmt
                    df.at[idx, 'Horas_Setup_Referencia'] = hrs_setup_ref
                    df.at[idx, 'Orden_Secuencia'] = secuencia_contador[linea]
                    df.at[idx, 'Hora_Inicio_Proyectada'] = hrs_inicio
                    df.at[idx, 'Hora_Fin_Proyectada'] = hrs_fin
                    df.at[idx, 'Estado_Produccion'] = 'Ajustado por Capacidad'
                    
                    secuencia_contador[linea] += 1
                else:
                    df.at[idx, 'Estado_Produccion'] = 'Excede Capacidad'
        
        # PROYECCIÓN DE DÍAS DE STOCK SEMANA SIGUIENTE
        df['Inv_Inicial_Sem2'] = df['Inventario_Final'] - df['Demanda_Sem_Actual'] + df['Sugerido_Final_Ajustado']
        
        v_diaria_sig = df['Demanda_Sem_Siguiente'] / df['Dias_Laborables_Linea']
        df['Dias_Stock_Inicio_Sem2'] = np.where(
            v_diaria_sig > 0,
            df['Inv_Inicial_Sem2'] / v_diaria_sig,
            999.0
        )
        
        df['Inv_Final_Sem2'] = df['Inv_Inicial_Sem2'] - df['Demanda_Sem_Siguiente']
        df['Dias_Stock_Final_Sem2'] = np.where(
            v_diaria_sig > 0,
            df['Inv_Final_Sem2'] / v_diaria_sig,
            999.0
        )
        
        # DÍAS DE STOCK FINAL MENSUAL Y CUMPLIMIENTO
        df['Inv_Final_Mes'] = df['Inventario_Final'] + df['Sugerido_Final_Ajustado'] - df['Demanda_Mensual_Clean']
        df['Dias_Stock_Final_Mensual'] = np.where(
            df['Venta_Diaria_Mensual'] > 0,
            df['Inv_Final_Mes'] / df['Venta_Diaria_Mensual'],
            999.0
        )
        
        if 'Demanda_Mensual' in df.columns:
            df['Cumplimiento_Demanda_Mensual_%'] = np.where(
                df['Demanda_Mensual_Clean'] > 0,
                ((df['Inventario_Final'] + df['Sugerido_Final_Ajustado']) / df['Demanda_Mensual_Clean']) * 100.0,
                0.0
            )
            
        return df, horas_acumuladas