import re
from pypdf import PdfReader
import io

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    resultados = []
    
    for i, page in enumerate(reader.pages):
        texto = page.extract_text() or ""
        
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
        
        if puntos is None or posibles is None:
            continue
        
        nombre = f"Estudiante_{i+1}"
        
        # Buscar nombre en campo Name de la hoja
        m = re.search(r'Name\s*[:|]?\s*(.+?)(?:\n|Date|Period|$)', texto, re.IGNORECASE)
        if m:
            candidato = m.group(1).strip()
            if len(candidato) > 2 and len(candidato) < 60:
                nombre = candidato
        
        # Si no encontro, buscar linea con letras antes de "Estudiante:"
        if nombre.startswith("Estudiante_"):
            lineas = [l.strip() for l in texto.split('\n') if l.strip()]
            excluir = ['estudiante', 'quiz', 'puntos', 'informe', 'zipgrade', 
                      '#', 'llave', 'poss', 'stu', 'pts', 'name', 'date', 'period']
            for linea in lineas:
                if any(p in linea.lower() for p in excluir):
                    continue
                if re.match(r'^\d', linea):
                    continue
                if len(linea) < 3 or len(linea) > 50:
                    continue
                if re.search(r'[a-zA-ZáéíóúñÁÉÍÓÚÑ]{2,}', linea):
                    nombre = linea
                    break
        
        nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0
        resultados.append({
            "nombre": nombre,
            "puntos": puntos,
            "posibles": posibles,
            "porcentaje": porcentaje or 0,
            "nota": nota
        })
    
    return resultados