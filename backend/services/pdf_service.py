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
        
        m = re.search(r'Puntos obtenidos[:\s]+([\d.]+)', texto)
        if m:
            puntos = float(m.group(1))
        
        m = re.search(r'Puntos posibles[:\s]+([\d.]+)', texto)
        if m:
            posibles = float(m.group(1))
        
        m = re.search(r'%\s*C correctas[:\s]+([\d.]+)', texto)
        if m:
            porcentaje = float(m.group(1))
        
        # El nombre está ANTES de "Estudiante:" en el texto
        nombre = "Desconocido"
        
        # Buscar el patron: texto antes de "Estudiante:"
        match = re.search(r'^(.+?)\nEstudiante:', texto, re.DOTALL)
        if match:
            bloque = match.group(1)
            lineas = [l.strip() for l in bloque.split('\n') if l.strip()]
            # Tomar la ultima linea que no sea "ZipGrade" ni numeros
            for linea in reversed(lineas):
                if re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑ]', linea) and 'ZipGrade' not in linea and len(linea) > 2:
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