from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text
import pandas as pd
import os
import shutil
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Conexión MySQL
engine = create_engine("mysql+pymysql://root:123456789@localhost/tecmd")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
def formulario_carga(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/subir", response_class=HTMLResponse)
async def subir_excel(request: Request, archivo: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, archivo.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(archivo.file, f)

    try:
        df = pd.read_excel(file_path, sheet_name="TODOS LOS CONVENIOS")
        df.columns = [
            "nombres", "apellidos", "documento", "email_institucional",
            "institucion", "email_personal", "convenio", "skype_id",
            "estado", "programa", "nombre_curso", "categoria_curso",
            "categoria_id_padre", "fecha_inicio", "fecha_fin", "itemname", "calificacion"
        ]

        df["calificacion"] = (
            df["calificacion"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df["calificacion"] = pd.to_numeric(df["calificacion"], errors="coerce")

        df["fecha_cargue"] = datetime.now()

        with engine.connect() as conn:
            result = conn.execute(text("SHOW COLUMNS FROM notas_convenio LIKE 'fecha_cargue'"))
            if result.fetchone() is None:
                conn.execute(text("ALTER TABLE notas_convenio ADD COLUMN fecha_cargue DATETIME"))

        df.to_sql("notas_convenio", con=engine, if_exists="replace", index=False)

    except Exception as e:
        return templates.TemplateResponse("index.html", {"request": request, "error": str(e)})

    return RedirectResponse(url="/notas", status_code=302)

@app.get("/notas", response_class=HTMLResponse)
async def ver_notas(request: Request):
    return templates.TemplateResponse("notas.html", {"request": request})

@app.get("/api/notas")
async def api_notas():
    df = pd.read_sql("SELECT * FROM notas_convenio", con=engine)

    # ✅ Convertir fechas a string
    for col in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
        df[col] = df[col].astype(str)

    # ✅ Reemplazar NaN por cadena vacía (¡esto evita el error!)
    df = df.fillna("")

    return JSONResponse(content={"data": df.to_dict(orient="records")})
