import os
import streamlit as st
import fitz  # PyMuPDF
import re
import io
import pandas as pd
from datetime import datetime
import pytesseract
from PIL import Image

# Configuración condicional para Tesseract (evita errores si se despliega en Linux/Cloud)
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
    """Parsea inteligentemente formatos mixtos de COP"""
    clean_text = re.sub(r'[^\d.,]', '', text)
    if not clean_text: 
        return 0.0
    
    if '.' in clean_text and ',' in clean_text:
        if clean_text.rfind('.') > clean_text.rfind(','):
            clean_text = clean_text.replace(',', '')
        else:
            clean_text = clean_text.replace('.', '').replace(',', '.')
    else:
        sep = '.' if '.' in clean_text else (',' if ',' in clean_text else None)
        if sep:
            parts = clean_text.split(sep)
            if len(parts[-1]) == 3:
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
        tasa = st.number_input("Tasa de Cambio (COP = 1 USD)", min_value=1.0, value=4000.0, step=50.0, format="%.2f")
        
        st.divider()
        st.subheader("🎨 Diseño del Nuevo Precio")
        f_color = st.color_picker("Color Letra", "#FFFFFF") 
            
        rgb_text = tuple(int(f_color.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4))
        
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

    # --- LÓGICA CORE ---
    if st.session_state.raw_pdf:
        # BOTÓN 1: El escaneo nativo ultra rápido con detección automática de tamaño de fuente
        if st.button("🔍 Escanear Precios (Modo Rápido)", type="primary", use_container_width=True):
            with st.spinner("Analizando documento de forma nativa..."):
                try:
                    with fitz.open(stream=st.session_state.raw_pdf, filetype="pdf") as doc:
                        candidates = []
                        pattern = re.compile(r'\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)')

                        for pnum, page in enumerate(doc):
                            # Extraer información detallada de los spans para mapear tamaños de letra
                            try:
                                page_dict = page.get_text("dict")
                                spans = []
                                for block in page_dict.get("blocks", []):
                                    for line in block.get("lines", []):
                                        for span in line.get("spans", []):
                                            spans.append(span)
                            except Exception:
                                spans = []

                            words = page.get_text("words") 
                            for w in words:
                                text_str = w[4]
                                match = pattern.search(text_str)
                                if match:
                                    val_cop = parse_cop_price(match.group(0))
                                    if val_cop > 0:
                                        # Detectar el tamaño original del span que contiene la palabra por su centro geométrico
                                        cx = (w[0] + w[2]) / 2
                                        cy = (w[1] + w[3]) / 2
                                        font_size = 12.0  # Tamaño base por defecto
                                        for span in spans:
                                            s_box = span["bbox"]
                                            if s_box[0] <= cx <= s_box[2] and s_box[1] <= cy <= s_box[3]:
                                                font_size = span["size"]
                                                break

                                        candidates.append({
                                            "Página": pnum + 1,
                                            "Original": text_str,
                                            "COP": val_cop,
                                            "USD": round(val_cop / tasa, 2),
                                            "Tamaño": round(font_size, 1),
                                            "Rect": (w[0], w[1], w[2], w[3]),
                                            "Convertir": True
                                        })
                        
                        if candidates:
                            st.session_state.df_precios = pd.DataFrame(candidates)
                            st.session_state.ocr_ofrecido = False
                        else:
                            st.session_state.df_precios = None
                            st.session_state.ocr_ofrecido = True
                except Exception as e:
                    st.error(f"Error procesando el PDF: {e}")

        # INTERFAZ CONDICIONAL: Solo aparece si el método rápido falló
        if st.session_state.ocr_ofrecido and st.session_state.df_precios is None:
            st.info("💡 **Aviso de Rendimiento:** No se detectó texto interactivo en el archivo. Esto ocurre si el catálogo está hecho de imágenes escaneadas o fotos.")
            
            if st.button("👁️ Activar Búsqueda por OCR (Consumo de Recursos Alto)", type="secondary", use_container_width=True):
                with st.spinner("Ejecutando reconocimiento óptico de caracteres con detección de propiedades de texto..."):
                    try:
                        with fitz.open(stream=st.session_state.raw_pdf, filetype="pdf") as doc:
                            candidates_ocr = []
                            pattern_ocr = re.compile(r'\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?')
                            
                            for pnum, page in enumerate(doc):
                                zoom = 2  
                                mat = fitz.Matrix(zoom, zoom)
                                pix = page.get_pixmap(matrix=mat)
                                
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                hocr = pytesseract.image_to_pdf_or_hocr(img, extension='hocr', lang='spa').decode('utf-8')
                                
                                # Captura las coordenadas de las líneas y sus atributos adicionales como x_size
                                lines = re.findall(r"<span class='ocr_line'.*?title=\"bbox (\d+) (\d+) (\d+) (\d+)(.*?)\".*?>(.*?)</span>", hocr, re.DOTALL)
                                
                                for line in lines:
                                    x0_img, y0_img, x1_img, y1_img, extra_attrs, text_html = line
                                    text_str = re.sub(r'<.*?>', '', text_html).strip()
                                    text_str = text_str.replace('O', '0')
                                    text_str = text_str.replace('o', '0')
                                    text_str = text_str.replace('I', '1')
                                    text_str = text_str.replace('l', '1')
                                    text_str = text_str.replace('S', '5')
                                    text_str = text_str.replace('s', '5')
                                    text_str = text_str.replace('B', '8')

                                    matches = pattern_ocr.findall(text_str)

                                    if matches:

                                        precios = []

                                        for precio_txt in matches:

                                            precio = parse_cop_price(precio_txt)

                                            if 2000 <= precio <= 500000:
                                                precios.append(precio)

                                        # Evitar duplicados
                                        precios = list(set(precios))

                                        if precios:

                                            # Regla para catálogos:
                                            # si aparecen varios precios en la misma caja,
                                            # nos quedamos con el menor (normalmente el promocional)
                                            val_cop = min(precios)

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
                                                "Original": text_str,
                                                "COP": val_cop,
                                                "USD": round(val_cop / tasa, 2),
                                                "Tamaño": round(font_size, 1),
                                                "Rect": (left, top, left + width, top + height),
                                                "Convertir": True
                                            })
                            # Eliminar detecciones duplicadas
                            seen = set()
                            filtered = []

                            for item in candidates_ocr:

                                key = (
                                    item["Página"],
                                    round(item["Rect"][0]),
                                    round(item["Rect"][1]),
                                    item["COP"]
                                )

                                if key not in seen:
                                    seen.add(key)
                                    filtered.append(item)

                            candidates_ocr = filtered
                            st.session_state.df_precios = pd.DataFrame(candidates_ocr)
                    except Exception as e:
                        st.error(f"Error en el motor OCR: {e}")

        # --- REVISIÓN Y EDICIÓN ---
        if st.session_state.df_precios is not None and not st.session_state.df_precios.empty:
            st.subheader(f"📋 Encontramos {len(st.session_state.df_precios)} posibles precios")
            
            st.session_state.df_precios["USD"] = (st.session_state.df_precios["COP"] / tasa).round(2)

            edited_df = st.data_editor(
                st.session_state.df_precios,
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
            if st.button("🪄 Generar PDF Modificado", type="primary", use_container_width=True):
                with st.spinner("Mapeando colores y aplicando camuflaje con tamaños dinámicos..."):
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
                                
                                sample_x = max(0, int((r.x0 - 1) * (150/72))) 
                                sample_y = max(0, int(((r.y0 + r.y1) / 2) * (150/72)))
                                
                                try:
                                    pixel_color = pix.pixel(sample_x, sample_y)
                                    rgb_bg = (pixel_color[0]/255, pixel_color[1]/255, pixel_color[2]/255)
                                except:
                                    rgb_bg = (1, 1, 1)

                                # --- EVALUACIÓN DE CONTRASTE ---
                                final_rgb_text = rgb_text
                                if auto_contraste:
                                    l_bg = calcular_luminancia(*rgb_bg)
                                    l_text = calcular_luminancia(*rgb_text)
                                    
                                    if abs(l_bg - l_text) < 0.35:
                                        if l_bg < 0.5:
                                            final_rgb_text = (1.0, 1.0, 1.0)
                                        else:
                                            final_rgb_text = (0.0, 0.0, 0.0)

                                # --- APLICACIÓN ---
                                page.draw_rect(r, color=rgb_bg, fill=rgb_bg, overlay=True)
                                
                                new_text = f"${row.USD:.2f}"
                                page.insert_text(
                                    (r.x0, r.y1 - 1), 
                                    new_text,
                                    fontsize=row.Tamaño,  # Aplicación del tamaño exacto del span detectado
                                    color=final_rgb_text,
                                    fontname="hebo", 
                                    overlay=True
                                )
                            
                        output = io.BytesIO()
                        doc.save(output, garbage=4, deflate=True)
                        st.session_state.pdf_final = output.getvalue()
                        
                    st.success("¡Operación exitosa! Revisa el documento final.")

        elif st.session_state.df_precios is not None and st.session_state.df_precios.empty:
            st.warning("No se encontraron precios válidos en el PDF usando ninguno de los métodos.")

        # --- DESCARGA ---
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