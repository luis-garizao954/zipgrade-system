import re
import anthropic
import base64
import os
from pypdf import PdfReader
import io

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    resultados = []
    ac = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    
    import fitz
    doc = fitz.open(stream=contenido, filetype="pdf")
    
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
        try:
            pag = doc[i]
            # Solo la franja superior izquierda donde esta el nombre
            ancho = pag.rect.width
            alto = pag.rect.height
            rect = fitz.Rect(0, alto * 0.05, ancho * 0.55, alto * 0.25)
            clip = pag.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect)
            img_bytes = clip.tobytes("jpeg")
            img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            
            resp = ac.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": img_b64
                    }},
                    {"type": "text", "text": "What name is handwritten in this image? Reply with ONLY the name, nothing else."}
                ]}]
            )
            nombre = resp.content[0].text.strip()
        except Exception as e:
            nombre = f"ERR:{str(e)[:40]}"
        
        nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0
        resultados.append({
            "nombre": nombre,
            "puntos": puntos,
            "posibles": posibles,
            "porcentaje": porcentaje or 0,
            "nota": nota
        })
    
    doc.close()
    return resultados