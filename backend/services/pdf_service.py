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
        
        puntos = None
        posibles = None
        porcentaje = None
        
        # Buscar datos numéricos
        m = re.search(r'Puntos obtenidos[:\s]+([\d.]+)', texto)
        if m:
            puntos = float(m.group(1))
        
        m = re.search(r'Puntos posibles[:\s]+([\d.]+)', texto)
        if m:
            posibles = float(m.group(1))
        
        m = re.search(r'%\s*C correctas[:\s]+([\d.]+)', texto)
        if m:
            porcentaje = float(m.group(1))
        
        # Buscar nombre — aparece al inicio del texto antes de "Estudiante"
        nombre = "Desconocido"
        lineas = [l.strip() for l in texto.split('\n') if l.strip()]
        
        palabras_excluir = ['estudiante', 'quiz', 'puntos', 'informe', 'llave', 
                           'zipgrade', '#', '%', 'poss', 'stu', 'pts']
        
        for linea in lineas:
            linea_lower = linea.lower()
            if any(p in linea_lower for p in palabras_excluir):
                continue
            if re.match(r'^\d', linea):
                continue
            if len(linea) < 3 or len(linea) > 60:
                continue
            # Verificar que tiene al menos una letra
            if re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑ]', linea):
                nombre = linea
                break
        
        if puntos is not None and posibles is not None:
            nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0
            resultados.append({
                "nombre": nombre,
                "puntos": puntos,
                "posibles": posibles,
                "porcentaje": porcentaje or 0,
                "nota": nota
            })
    
    return resultados