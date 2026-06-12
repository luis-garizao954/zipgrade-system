import re
from pypdf import PdfReader
import io

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    resultados = []
    
    for i, page in enumerate(reader.pages):
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
        
        # Extraer todas las lineas del texto como resumen
        lineas = [l.strip() for l in texto.split('\n') if l.strip()]
        resumen = " | ".join(lineas[:8])
        nombre = f"PAG{i+1}: {resumen[:200]}"
        
        if puntos is not None and posibles is not None:
            nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0
            resultados.append({
                "nombre": nombre,
                "puntos": puntos,
                "posibles": posibles,
                "porcentaje": porcentaje or 0,
                "nota": nota,
                "pagina": i+1
            })
    
    return resultados