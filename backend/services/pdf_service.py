import re
from pypdf import PdfReader
import io

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    resultados = []
    
    for page in reader.pages:
        texto = page.extract_text()
        if not texto:
            continue
        
        nombre = None
        puntos = None
        posibles = None
        porcentaje = None
        
        lineas = texto.split('\n')
        for linea in lineas:
            if 'Puntos obtenidos:' in linea:
                m = re.search(r'Puntos obtenidos:\s*([\d.]+)', linea)
                if m:
                    puntos = float(m.group(1))
            elif 'Puntos posibles' in linea:
                m = re.search(r'Puntos posibles\s*([\d.]+)', linea)
                if m:
                    posibles = float(m.group(1))
            elif '% C correctas:' in linea:
                m = re.search(r'%\s*C correctas:\s*([\d.]+)', linea)
                if m:
                    porcentaje = float(m.group(1))
        
        palabras_clave = ['Estudiante:', 'Quiz:', 'Puntos', '%', '#', 'Informe', 'Llave']
        for linea in lineas:
            linea = linea.strip()
            if not linea or len(linea) < 3 or len(linea) > 60:
                continue
            if any(p in linea for p in palabras_clave):
                continue
            if re.match(r'^\d', linea):
                continue
            nombre = linea
            break
        
        if puntos is not None:
            nota = round((puntos / posibles) * 5.0, 1) if posibles else 0
            resultados.append({
                "nombre": nombre or "Desconocido",
                "puntos": puntos,
                "posibles": posibles,
                "porcentaje": porcentaje,
                "nota": nota
            })
    
    return resultados