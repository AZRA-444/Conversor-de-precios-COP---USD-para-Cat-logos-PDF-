import os
import streamlit as st
import fitz  # PyMuPDF
import re
import io
import pandas as pd
from datetime import datetime
import pytesseract
from PIL import Image

# Configuración condicional para Tesseract (soporte multiplataforma Windows/Linux)
ruta_windows = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
if os.path.exists(ruta_windows):
    pytesseract.pytesseract.tesseract_cmd = ruta_windows

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Conversor de Catálogos | COP a USD", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- ESTADO DE SESIÓN ---
if 'raw_pdf' not in st.session_state: st.session_state.raw_pdf = None
if 'df_precios' not in st.session_state: st.session_state.df_precios = None
if 'pdf_final' not in st.session_state: st.session_state.pdf_final = None
if 'ocr_ofrecido' not in st.session_state: st.session_state.ocr_ofrecido = False

def parse_cop_price(text):
    """Parsea inteligentemente formatos mixtos de COP, eliminando ruidos y puntuaciones finales"""
    # Limpieza inicial: solo números, puntos y comas
    clean_text = re.sub(r'[^\d.,]', '', text)
    # Corrección de Bug 5: Eliminar puntos o comas flotantes al inicio o final (ej: "25.000.")
    clean_text = clean_text.strip('.,')
    
    if not clean_text: 
        return 0.0
    
    # Tratamiento de formatos mixtos con ambos separadores
    if '.' in clean_text and ',' in clean_text:
        if clean_text.rfind('.') > clean_text.rfind(','):
            clean_text = clean_text.replace(',', '')
        else:
            clean_text = clean_text.replace('.', '').replace(',', '.')
    else:
        # Un solo tipo de separador o ninguno
        sep = '.' if '.' in clean_text else (',' if ',' in clean_text else None)
        if sep:
            parts = clean_text.split(sep)
            # Si la última parte tiene 3 dígitos, asumimos que es separador de miles (ej: 50.000)
            if len(parts[-1]) == 3 and len(parts) > 1:
                clean_text = clean_text.replace(sep, '')
            else:
                clean_text = clean_text.replace(sep, '.')
                
    try:
        return float(clean_text)
    except ValueError:
        return 0.0

def calcular_luminancia(r, g, b):
    """Calcula el brillo percibido de un color (0.0 = Negro, 1.0 = Blanco)"""
    return 0.299 * r + 0.587 * g + 0.114 * b

def main():
    st.title("Cambia los Precios de Tu Catálogo (COP -> USD)")
    st.markdown("Sube tu catálogo, escanea los precios y el sistema reemplazará los valores detectando y respetando el tamaño de letra original.")

    # --- PANEL LATERAL ---
    with st.sidebar:
        st.header("⚙️ Configuración")
        tasa = st.number_input("Tasa de Cambio (COP = 1 USD)", min_value=1.0, value=2100.0, step=50.0, format="%.2f")
        
        st.divider()
        st.subheader("🔍 Filtros de Extracción")
        # Rangos dinámicos controlados por el usuario
        precio_min = st.number_input("Precio mínimo a detectar (COP)", min_value=0.0, value=1000.0, step=100.0)
        precio_max = st.number_input("Precio máximo a detectar (COP)", min_value=0.0, value=10000000.0, step=50000.0)
        
        st.divider()
        st.subheader("🎨 Diseño del Nuevo Precio")
        f_color = st.color_picker("Color Letra", "#FFFFFF") 
        rgb_text = tuple(int(f_color.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4))
        
        # Flexibilidad estética para fondos complejos
        bg_mode = st.radio("Fondo del nuevo precio", ["Auto-detectar (Camuflaje)", "Blanco Puro", "Manual personalizado"])
        rgb_bg_manual = (1.0, 1.0, 1.0)
        if bg_mode == "Manual personalizado":
            f_bg_custom = st.color_picker("Color Fondo Personalizado", "#000000")
            rgb_bg_manual = tuple(int(f_bg_custom.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4))
        
        st.divider()
        st.subheader("🛡️ Seguridad Visual")
        auto_contraste = st.toggle("Auto-corregir contraste", value=True)
        st.caption("Si se detecta que el texto no se va a leer sobre el fondo, se cambiará automáticamente a blanco o negro.")

    # --- CARGA DE ARCHIVO ---
    uploaded_file = st.file_uploader("📥 Arrastra tu catálogo PDF aquí", type=["pdf"])

    if uploaded_file:
        if uploaded_file.getvalue() != st.session_state.raw_pdf:
            st.session_state.raw_pdf = uploaded_file.getvalue()
            st.session_state.df_precios = None 
            st.session_state.pdf_final = None
            st.session_state.ocr_ofrecido = False

    # --- EXPRESIÓN REGULAR ULTRA ESTRICTA ---
    # Obliga a que existan separadores de miles/decimales. No hace match con números planos (ej: 1239129 o 2026)
    pattern_universal = re.compile(r'(?:\$\s*)?\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?\b')

    # --- LÓGICA CORE ---
    if st.session_state.raw_pdf:
        
        # BOTÓN 1: El escaneo nativo ultra rápido con detección automática de tamaño de fuente
        if st.button("🔍 Escanear Precios (Modo Rápido)", type="primary", use_container_width=True):
            with st.spinner("Analizando estructura interna del documento de forma nativa..."):
                try:
                    with fitz.open(stream=st.session_state.raw_pdf, filetype="pdf") as doc:
                        candidates = []

                        for pnum, page in enumerate(doc):
                            try:
                                page_dict = page.get_text("dict")
                            except Exception:
                                continue

                            for block in page_dict.get("blocks", []):
                                for line in block.get("lines", []):
                                    for span in line.get("spans", []):
                                        text_str = span.get("text", "").strip()
                                        
                                        # Buscar coincidencias de precios estructurados dentro del span
                                        for match in pattern_universal.finditer(text_str):
                                            matched_txt = match.group(0)
                                            
                                            # --- FILTROS DE EXCLUSIÓN ADICIONALES POR CONTEXTO ---
                                            start_idx = match.start()
                                            end_idx = match.end()
                                            contexto_previo = text_str[max(0, start_idx - 20):start_idx]
                                            contexto_posterior = text_str[end_idx:min(len(text_str), end_idx + 20)]
                                            
                                            # Filtrar prefijos explícitos de códigos o fechas
                                            if re.search(r'(?:#|cod|ref|item|id|código|codigo|año|ano|fecha|date)\s*[:.]?\s*$', contexto_previo, re.IGNORECASE):
                                                continue
                                                
                                            # Filtrar si está directamente unido a un formato de fecha común (ej: 10.12/2026)
                                            if (contexto_previo and contexto_previo[-1] in ['/', '-']) or (contexto_posterior and contexto_posterior[0] in ['/', '-']):
                                                continue
                                            
                                            val_cop = parse_cop_price(matched_txt)
                                            
                                            # Filtrar años con separador por error si no tienen símbolo de moneda explícito
                                            if '$' not in matched_txt and '$' not in contexto_previo:
                                                if 2000 <= val_cop <= 2035:
                                                    continue
                                            # -----------------------------------------------------
                                            
                                            if precio_min <= val_cop <= precio_max:
                                                font_size = span.get("size", 12.0)
                                                
                                                rects = page.search_for(matched_txt)
                                                span_rect = fitz.Rect(span["bbox"])
                                                best_rect = span_rect  # Fallback
                                                
                                                for r in rects:
                                                    if span_rect.contains(r) or span_rect.intersects(r):
                                                        best_rect = r
                                                        break
                                                
                                                candidates.append({
                                                    "Página": pnum + 1,
                                                    "Original": matched_txt,
                                                    "COP": val_cop,
                                                    "USD": round(val_cop / tasa, 2),
                                                    "Tamaño": round(font_size, 1),
                                                    "Rect": (best_rect.x0, best_rect.y0, best_rect.x1, best_rect.y1),
                                                    "Convertir": True
                                                })
                        
                        # Filtrado de duplicados por vecindad espacial (tolerancia de 6 puntos)
                        if candidates:
                            filtered_candidates = []
                            for item in candidates:
                                duplicado = False
                                for f_item in filtered_candidates:
                                    if item["Página"] == f_item["Página"]:
                                        dist_x = abs(item["Rect"][0] - f_item["Rect"][0])
                                        dist_y = abs(item["Rect"][1] - f_item["Rect"][1])
                                        if dist_x < 6 and dist_y < 6:
                                            duplicado = True
                                            break
                                if not duplicado:
                                    filtered_candidates.append(item)
                                    
                            st.session_state.df_precios = pd.DataFrame(filtered_candidates)
                            st.session_state.ocr_ofrecido = False
                        else:
                            st.session_state.df_precios = None
                            st.session_state.ocr_ofrecido = True
                            
                except Exception as e:
                    st.error(f"Error procesando el PDF: {e}")

        # INTERFAZ CONDICIONAL: Modo OCR
        if st.session_state.ocr_ofrecido and st.session_state.df_precios is None:
            st.info("💡 **Aviso de Estructura:** No se detectó texto interactivo estructurado. Activando preparación para lectura por imágenes (OCR).")
            
            if st.button("👁️ Activar Búsqueda por OCR (Procesamiento Avanzado)", type="secondary", use_container_width=True):
                with st.spinner("Ejecutando reconocimiento óptico de caracteres..."):
                    try:
                        with fitz.open(stream=st.session_state.raw_pdf, filetype="pdf") as doc:
                            candidates_ocr = []
                            
                            for pnum, page in enumerate(doc):
                                zoom = 2
                                mat = fitz.Matrix(zoom, zoom)
                                pix = page.get_pixmap(matrix=mat)
                                
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                hocr = pytesseract.image_to_pdf_or_hocr(img, extension='hocr', lang='spa', config='--psm 11').decode('utf-8')
                                
                                lines = re.findall(r"<span class='ocr_line'.*?title=\"bbox (\d+) (\d+) (\d+) (\d+)(.*?)\".*?>(.*?)</span>", hocr, re.DOTALL)
                                
                                for line in lines:
                                    x0_img, y0_img, x1_img, y1_img, extra_attrs, text_html = line
                                    text_str = re.sub(r'<.*?>', '', text_html).strip()
                                    
                                    # Normalización OCR estándar
                                    replacements = {'O': '0', 'o': '0', 'I': '1', 'l': '1', 'S': '5', 's': '5', 'B': '8'}
                                    for src, dst in replacements.items():
                                        text_str = text_str.replace(src, dst)

                                    # Evaluación con la nueva regex estricta en el bucle OCR
                                    for match in pattern_universal.finditer(text_str):
                                        matched_txt = match.group(0)
                                        
                                        # --- FILTROS DE EXCLUSIÓN EN OCR ---
                                        start_idx = match.start()
                                        end_idx = match.end()
                                        contexto_previo = text_str[max(0, start_idx - 20):start_idx]
                                        contexto_posterior = text_str[end_idx:min(len(text_str), end_idx + 20)]
                                        
                                        if re.search(r'(?:#|cod|ref|item|id|código|codigo|año|ano|fecha|date)\s*[:.]?\s*$', contexto_previo, re.IGNORECASE):
                                            continue
                                            
                                        if (contexto_previo and contexto_previo[-1] in ['/', '-']) or (contexto_posterior and contexto_posterior[0] in ['/', '-']):
                                            continue
                                        
                                        val_cop = parse_cop_price(matched_txt)
                                        
                                        if '$' not in matched_txt and '$' not in contexto_previo:
                                            if 2000 <= val_cop <= 2035:
                                                continue
                                        # -----------------------------------

                                        if precio_min <= val_cop <= precio_max:
                                            left = float(x0_img) / zoom
                                            top = float(y0_img) / zoom
                                            width = (float(x1_img) - float(x0_img)) / zoom
                                            height = (float(y1_img) - float(y0_img)) / zoom

                                            size_match = re.search(r'x_size (\d+)', extra_attrs)
                                            if size_match:
                                                font_size = float(size_match.group(1)) / zoom
                                            else:
                                                font_size = height * 0.75

                                            candidates_ocr.append({
                                                "Página": pnum + 1,
                                                "Original": matched_txt,
                                                "COP": val_cop,
                                                "USD": round(val_cop / tasa, 2),
                                                "Tamaño": round(font_size, 1),
                                                "Rect": (left, top, left + width, top + height),
                                                "Convertir": True
                                            })
                            
                            if candidates_ocr:
                                filtered_ocr = []
                                for item in candidates_ocr:
                                    duplicado = False
                                    for f_item in filtered_ocr:
                                        if item["Página"] == f_item["Página"]:
                                            dist_x = abs(item["Rect"][0] - f_item["Rect"][0])
                                            dist_y = abs(item["Rect"][1] - f_item["Rect"][1])
                                            if dist_x < 6 and dist_y < 6:
                                                duplicado = True
                                                break
                                    if not duplicado:
                                        filtered_ocr.append(item)
                                candidates_ocr = filtered_ocr
                                
                            st.session_state.df_precios = pd.DataFrame(candidates_ocr)
                    except Exception as e:
                        st.error(f"Error en el motor OCR: {e}.")

        # --- REVISIÓN Y EDICIÓN ---
        if st.session_state.df_precios is not None and not st.session_state.df_precios.empty:
            st.subheader(f"Registros Detectados: {len(st.session_state.df_precios)} elementos")
            
            st.session_state.df_precios["USD"] = (st.session_state.df_precios["COP"] / tasa).round(2)

            edited_df = st.data_editor(
                st.session_state.df_precios,
                key="workspace_tabla_precios",
                column_config={
                    "Rect": None, 
                    "Página": st.column_config.NumberColumn(disabled=True),
                    "Original": st.column_config.TextColumn(disabled=True),
                    "COP": st.column_config.NumberColumn(format="$ %.2f", disabled=True),
                    "USD": st.column_config.NumberColumn(format="$ %.2f USD"),
                    "Tamaño": st.column_config.NumberColumn(format="%.1f pt", disabled=True),
                    "Convertir": st.column_config.CheckboxColumn("Reemplazar")
                },
                use_container_width=True,
                hide_index=True
            )

            # --- GENERACIÓN DE PDF ---
            if st.button("Generar PDF Modificado", type="primary", use_container_width=True):
                st.session_state.df_precios = edited_df
                
                with st.spinner("Procesando documento final y aplicando diseño de capas..."):
                    with fitz.open(stream=st.session_state.raw_pdf, filetype="pdf") as doc:
                        edits_by_page = {}
                        for row in edited_df.itertuples():
                            if row.Convertir:
                                edits_by_page.setdefault(row.Página, []).append(row)
                        
                        for page_num, rows in edits_by_page.items():
                            page = doc[page_num - 1]
                            pix = page.get_pixmap(dpi=150)
                            
                            for row in rows:
                                r = fitz.Rect(row.Rect)
                                
                                if bg_mode == "Blanco Puro":
                                    rgb_bg = (1.0, 1.0, 1.0)
                                elif bg_mode == "Manual personalizado":
                                    rgb_bg = rgb_bg_manual
                                else:
                                    sample_x = max(0, min(int((r.x0 - 1) * (150/72)), pix.width - 1)) 
                                    sample_y = max(0, min(int(((r.y0 + r.y1) / 2) * (150/72)), pix.height - 1))
                                    try:
                                        pixel_color = pix.pixel(sample_x, sample_y)
                                        rgb_bg = (pixel_color[0]/255, pixel_color[1]/255, pixel_color[2]/255)
                                    except Exception:
                                        rgb_bg = (1.0, 1.0, 1.0)

                                final_rgb_text = rgb_text
                                if auto_contraste:
                                    l_bg = calcular_luminancia(*rgb_bg)
                                    l_text = calcular_luminancia(*rgb_text)
                                    if abs(l_bg - l_text) < 0.35:
                                        final_rgb_text = (1.0, 1.0, 1.0) if l_bg < 0.5 else (0.0, 0.0, 0.0)

                                padding_rect = fitz.Rect(r.x0, r.y0 - 1, r.x1, r.y1 + 1)
                                page.draw_rect(padding_rect, color=rgb_bg, fill=rgb_bg, overlay=True)
                                
                                new_text = f"${row.USD:.2f}"
                                page.insert_text(
                                    (r.x0, r.y1 - 1), 
                                    new_text,
                                    fontsize=row.Tamaño, 
                                    color=final_rgb_text,
                                    fontname="hebo", 
                                    overlay=True
                                )
                            
                        output = io.BytesIO()
                        doc.save(output, garbage=4, deflate=True)
                        st.session_state.pdf_final = output.getvalue()
                        
                    st.success("¡Catálogo procesado con éxito! Listo para descarga continua.")

        elif st.session_state.df_precios is not None and st.session_state.df_precios.empty:
            st.warning("No se encontraron precios que cumplan con los rangos de filtrado establecidos o la estructura requerida.")

        # --- PANEL DE DESCARGA ---
        if st.session_state.pdf_final:
            st.download_button(
                label="📥 Descargar Catálogo en USD",
                data=st.session_state.pdf_final,
                file_name=f"catalogo_USD_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
