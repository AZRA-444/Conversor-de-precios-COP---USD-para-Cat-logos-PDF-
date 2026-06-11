# Conversor de Catálogos PDF COP → USD

Aplicación desarrollada en Streamlit para convertir automáticamente precios en catálogos PDF desde pesos colombianos (COP) a dólares estadounidenses (USD).

## Características

- Escaneo rápido mediante extracción nativa de texto PDF.
- OCR automático para catálogos escaneados o imágenes.
- Conversión automática COP → USD.
- Conservación del tamaño original de la tipografía.
- Detección de contraste automática.
- Edición manual de precios detectados.
- Exportación de PDF modificado.

---

## Tecnologías utilizadas

- Python 3.14
- Streamlit
- PyMuPDF
- Pandas
- Pillow
- Tesseract OCR

---

## Instalación local

### Clonar repositorio

```bash
git clone https://github.com/usuario/catalogo-converter.git
cd catalogo-converter
```

### Crear entorno virtual

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Linux:

```bash
source venv/bin/activate
```

### Instalar dependencias

```bash
pip install -r requirements.txt
```

### Ejecutar

```bash
streamlit run app.py
```

---



---

## Flujo de trabajo

1. Subir catálogo PDF.
2. Ejecutar escaneo rápido.
3. Si no hay texto embebido:

```text
Activar OCR
```

4. Revisar precios detectados.
5. Generar PDF.
6. Descargar catálogo convertido.

---

## Licencia

MIT
