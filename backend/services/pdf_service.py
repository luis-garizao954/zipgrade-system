import re
import anthropic
import base64
import os
from pypdf import PdfReader, PdfWriter
import io

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    resultados = []
    ac = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    
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
        
        # Extraer imagen de la pagina para leer nombre con Vision
        nombre = f"Estudiante_{i+1}"
        try:
            import fitz
            doc = fitz.open(stream=contenido, filetype="pdf")
            pag = doc[i]
            # Recortar solo la parte superior donde esta el nombre
            rect = fitz.Rect(0, 0, pag.rect.width, pag.rect.height * 0.35)
            clip = pag.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect)
            img_b64 = base64.b64encode(clip.tobytes("png")).decode()
            doc.close()
            
            resp = ac.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": "Lee el nombre escrito a mano en esta imagen de examen. Responde SOLO el nombre, nada mas. Si no ves nombre claro responde Desconocido."}
                ]}]
            )
            nombre = resp.content[0].text.strip()
        except Exception as e:
            nombre = f"Estudiante_{i+1}"
        
        nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0
        resultados.append({
            "nombre": nombre,
            "puntos": puntos,
            "posibles": posibles,
            "porcentaje": porcentaje or 0,
            "nota": nota
        })
    
    return resultados