from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text
import pandas as pd
import os
import shutil
from datetime import datetime
import re
from fastapi.responses import StreamingResponse
import io
from difflib import get_close_matches

# Inicialización
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Conexión MySQL
engine = create_engine("mysql+pymysql://root:123456789@localhost/tecmd")

# Carpeta para archivos
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
def formulario_carga(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

from datetime import datetime




@app.post("/subir", response_class=HTMLResponse)
async def subir_excel(request: Request, archivo: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, archivo.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(archivo.file, f)

    try:
        # Leer archivo y asignar columnas
        df = pd.read_excel(file_path, sheet_name="TODOS LOS CONVENIOS")
        df.columns = [
            "nombres", "apellidos", "documento", "email_institucional",
            "institucion", "email_personal", "convenio", "skype_id",
            "estado", "programa", "nombre_curso", "categoria_curso",
            "categoria_id_padre", "fecha_inicio", "fecha_fin", "itemname", "calificacion"
        ]

        # Normalizar columnas de texto
        columnas_texto = [
            "nombres", "apellidos", "documento", "email_institucional",
            "institucion", "email_personal", "convenio", "skype_id",
            "estado", "programa", "nombre_curso", "categoria_curso",
            "categoria_id_padre", "itemname"
        ]
        for col in columnas_texto:
            df[col] = df[col].astype(str).str.lower().str.strip()

        # 🔧 Limpiar nombre del curso (mantener "e-commerce" intacto)
        def limpiar_nombre_curso(nombre):
            if not isinstance(nombre, str):
                return nombre
            nombre = nombre.strip().lower()

            if re.search(r"\be[\s-]?commerce\b", nombre):
                return "e-commerce"

            nombre = re.sub(r"\(.*?\)", "", nombre)
            nombre = re.sub(r"\[.*?\]", "", nombre)
            nombre = nombre.split("-")[0] if "-" in nombre else nombre
            return nombre.strip()

        df["nombre_curso"] = df["nombre_curso"].apply(limpiar_nombre_curso)

        # Calificación y fechas
        df["calificacion"] = (
            df["calificacion"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df["calificacion"] = pd.to_numeric(df["calificacion"], errors="coerce")
        df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"], errors="coerce")
        df["fecha_cargue"] = datetime.now()

        registros_originales = len(df)

        # 🔎 Obtener cursos oficiales
        with engine.connect() as conn:
            cursos_oficiales = pd.read_sql(
                "SELECT DISTINCT LOWER(TRIM(curso)) AS curso FROM rutas_curriculares",
                conn
            )
            lista_cursos_oficiales = cursos_oficiales["curso"].dropna().tolist()

        # 🔁 Reemplazar por curso más parecido
        def corregir_nombre_curso(nombre):
            if nombre == "e-commerce":
                return nombre
            coincidencias = get_close_matches(nombre, lista_cursos_oficiales, n=1, cutoff=0.6)
            return coincidencias[0] if coincidencias else nombre

        df["nombre_curso"] = df["nombre_curso"].apply(corregir_nombre_curso)

        # Separar por fecha
        fecha_corte = pd.to_datetime("2025-03-23")
        df_recientes = df[df["fecha_inicio"] > fecha_corte]
        df_antiguos = df[df["fecha_inicio"] <= fecha_corte]

        df_antiguos = df_antiguos[df_antiguos["calificacion"].notna()]
        df_antiguos = df_antiguos[df_antiguos["calificacion"] >= 3.0]

        registros_descartados = registros_originales - len(df_antiguos) - len(df_recientes)

        # Filtros por nombre de curso y estado
        filtros_excluir = [
            "bienestar virtual tecmd",
            "cuso liderazgo",
            "prueba clasificacion ingles-tecmd",
            "curso pruebas saber"
        ]
        for filtro in filtros_excluir:
            df_antiguos = df_antiguos[~df_antiguos["nombre_curso"].str.contains(filtro, na=False)]

        df_antiguos = df_antiguos[~df_antiguos["estado"].str.contains("inactivo", na=False)]

        # Deduplicación por nota más alta
        antes_deduplicar = len(df_antiguos)
        df_antiguos = df_antiguos.loc[
            df_antiguos.groupby(["documento", "nombre_curso"])["calificacion"].idxmax()
        ].reset_index(drop=True)
        registros_duplicados = antes_deduplicar - len(df_antiguos)

        # Unir todo
        df_final = pd.concat([df_recientes, df_antiguos], ignore_index=True)

        # Verificar columna y guardar
        with engine.connect() as conn:
            result = conn.execute(text("SHOW COLUMNS FROM notas_convenio LIKE 'fecha_cargue'"))
            if result.fetchone() is None:
                conn.execute(text("ALTER TABLE notas_convenio ADD COLUMN fecha_cargue DATETIME"))

        df_final.to_sql("notas_convenio", con=engine, if_exists="replace", index=False)

    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": f"Error al subir archivo: {e}"
        })

    return templates.TemplateResponse("resumen.html", {
        "request": request,
        "totales": registros_originales,
        "descartados": registros_descartados,
        "duplicados": registros_duplicados,
        "finales": len(df_final)
    })


@app.get("/notas", response_class=HTMLResponse)
async def ver_notas(request: Request):
    return templates.TemplateResponse("notas.html", {"request": request})

@app.get("/api/notas")
async def api_notas():
    df = pd.read_sql("SELECT * FROM notas_convenio", con=engine)
    for col in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
        df[col] = df[col].astype(str)
    df = df.fillna("")
    return JSONResponse(content={"data": df.to_dict(orient="records")})

@app.get("/mallas", response_class=HTMLResponse)
async def formulario_mallas(request: Request):
    return templates.TemplateResponse("mallas.html", {"request": request})



@app.post("/subir-mallas-v1", response_class=HTMLResponse)
async def subir_mallas(request: Request, archivo: UploadFile = File(...)):
    import pandas as pd
    from datetime import datetime

    file_path = os.path.join(UPLOAD_DIR, archivo.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(archivo.file, f)

    try:
        # Cargar Excel con encabezado automático
        df = pd.read_excel(file_path)

        # Asegurar que las columnas existan
        columnas_requeridas = {"nombre_ruta", "periodo", "nombre_curso", "creditos"}
        if not columnas_requeridas.issubset(df.columns):
            raise Exception("El archivo no contiene las columnas requeridas.")

        # Limpiar y convertir
        df["creditos"] = pd.to_numeric(df["creditos"], errors="coerce")
        df["fecha_cargue"] = datetime.now()

        # Agregar orden por grupo (ruta + periodo)
        df["orden"] = df.groupby(["nombre_ruta", "periodo"]).cumcount() + 1

        # Subir a la base de datos
        df.to_sql("rutas_curriculares", con=engine, if_exists="append", index=False)

    except Exception as e:
        return templates.TemplateResponse("mallas.html", {
            "request": request,
            "error": f"⚠️ Error al subir archivo: {e}"
        })

    return templates.TemplateResponse("mallas.html", {
        "request": request,
        "success": f"✅ {len(df)} registros cargados exitosamente."
    })



@app.post("/subir-mallas", response_class=HTMLResponse)
async def subir_mallas(request: Request, archivo: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, archivo.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(archivo.file, f)

    try:
        df = pd.read_excel(file_path)

        # Normalizar encabezados
        df.columns = df.columns.str.strip().str.lower()

        # Verificar columnas requeridas
        columnas_requeridas = {"programa", "curso", "creditos", "periodo", "plan"}
        if not columnas_requeridas.issubset(df.columns):
            raise Exception(f"⚠️ El archivo no contiene las columnas requeridas: {columnas_requeridas}")

        # Normalizar texto en columnas clave
        for col in ["programa", "curso", "periodo", "plan"]:
            df[col] = df[col].apply(normalizar_texto)

        df["creditos"] = pd.to_numeric(df["creditos"], errors="coerce")
        df["fecha_cargue"] = datetime.now()
        df["orden"] = df.groupby(["programa", "periodo"]).cumcount() + 1

        df[["programa", "curso", "creditos", "periodo", "orden", "plan", "fecha_cargue"]].to_sql(
            "rutas_curriculares", con=engine, if_exists="append", index=False
        )

    except Exception as e:
        return templates.TemplateResponse("mallas.html", {
            "request": request,
            "error": f"⚠️ Error al subir archivo: {e}"
        })

    return templates.TemplateResponse("mallas.html", {
        "request": request,
        "success": f"✅ {len(df)} registros cargados exitosamente."
    })




@app.get("/rutas", response_class=HTMLResponse)
async def ver_rutas(request: Request):
    return templates.TemplateResponse("rutas.html", {"request": request})

@app.get("/api/rutas")
async def api_rutas():
    df = pd.read_sql("SELECT * FROM rutas_curriculares", con=engine)
    for col in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
        df[col] = df[col].astype(str)
    df = df.fillna("")
    return JSONResponse(content={"data": df.to_dict(orient="records")})


@app.get("/pendientes", response_class=HTMLResponse)
async def ver_pendientes(request: Request):
    return templates.TemplateResponse("pendientes.html", {"request": request})

@app.get("/api/pendientes")
async def api_pendientes():
    query = """
         SELECT * from materias_pendientes
    """
    df = pd.read_sql(query, con=engine)
    df = df.fillna("").astype(str)
    return JSONResponse(content={"data": df.to_dict(orient="records")})



@app.get("/exportar-pendientes")
async def exportar_pendientes():
    query = """
        SELECT * from materias_pendientes
    """
    df = pd.read_sql(query, con=engine)
    df = df.fillna("")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Pendientes")

    output.seek(0)
    headers = {
        "Content-Disposition": "attachment; filename=pendientes.xlsx"
    }
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)



@app.get("/generar-pendientes")
async def generar_materias_pendientes():
    from datetime import datetime

    # 1. Detectar plan
    plan_query = """
        SELECT COUNT(*) AS cantidad
        FROM rutas_curriculares rc
        INNER JOIN notas_convenio nc
        ON rc.curso = nc.nombre_curso
        WHERE rc.plan = 'viejo'
    """
    plan_result = pd.read_sql(plan_query, con=engine)
    usar_plan = 'viejo' if plan_result.iloc[0]["cantidad"] > 0 else 'nuevo'

    # 2. Cargar equivalencias
    equivalencias = pd.read_sql("SELECT curso, grupo_equivalente FROM cursos_equivalentes", con=engine)
    equivalencias["curso"] = equivalencias["curso"].str.strip().str.lower()

    # 3. Cargar materias aprobadas
    aprobadas = pd.read_sql("""
        SELECT documento, LOWER(TRIM(nombre_curso)) AS nombre_curso
        FROM notas_convenio
        WHERE calificacion >= 3.0 AND estado != 'inactivo'
    """, con=engine)

    # 4. Agregar grupo_equivalente a las aprobadas
    aprobadas = aprobadas.merge(equivalencias, how="left", left_on="nombre_curso", right_on="curso")
    aprobadas["grupo_equivalente"] = aprobadas["grupo_equivalente"].fillna(-1)

    # 5. Cursos pendientes por plan (sin LEFT JOIN para evaluar después)
    query = f"""
    SELECT 
        r.programa AS nombre_ruta,
        r.periodo,
        r.curso AS nombre_curso,
        r.creditos,
        r.plan,
        n.documento,
        CONCAT(n.nombres, ' ', n.apellidos) AS estudiante,
        n.convenio,
        n.institucion
    FROM rutas_curriculares r
    JOIN (
        SELECT DISTINCT documento, nombres, apellidos, programa, convenio, institucion
        FROM notas_convenio
        WHERE documento IS NOT NULL AND documento != ''
    ) n ON n.programa = r.programa
    WHERE r.plan = '{usar_plan}'
    """
    pendientes = pd.read_sql(query, con=engine)
    pendientes["nombre_curso"] = pendientes["nombre_curso"].str.strip().str.lower()

    # 6. Agregar grupo_equivalente a las pendientes
    pendientes = pendientes.merge(equivalencias, how="left", left_on="nombre_curso", right_on="curso")
    pendientes["grupo_equivalente"] = pendientes["grupo_equivalente"].fillna(-1)

    # 7. Filtrar: si el estudiante tiene aprobado algo del mismo grupo_equivalente, excluir
    def esta_aprobada(documento, grupo_eq, curso):
        if grupo_eq != -1:
            return ((aprobadas["documento"] == documento) & (aprobadas["grupo_equivalente"] == grupo_eq)).any()
        else:
            return ((aprobadas["documento"] == documento) & (aprobadas["nombre_curso"] == curso)).any()

    pendientes["excluir"] = pendientes.apply(
        lambda row: esta_aprobada(row["documento"], row["grupo_equivalente"], row["nombre_curso"]),
        axis=1
    )

    pendientes = pendientes[~pendientes["excluir"]].drop(columns=["curso", "grupo_equivalente", "excluir"])

    # 8. Guardar
    pendientes["fecha_cargue"] = datetime.now()
    pendientes = pendientes.fillna("")

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM materias_pendientes"))

    pendientes.to_sql("materias_pendientes", con=engine, if_exists="append", index=False)

    return {"message": f"{len(pendientes)} materias pendientes guardadas correctamente para plan '{usar_plan}'."}






@app.get("/historial-carga", response_class=HTMLResponse)
async def formulario_historial(request: Request):
    return templates.TemplateResponse("historial_carga.html", {"request": request})


import unicodedata

def normalizar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    return texto

@app.post("/subir-historial", response_class=HTMLResponse)
async def subir_historial(request: Request, archivo: UploadFile = File(...)):
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

        columnas_texto = [
            "nombres", "apellidos", "email_institucional", "institucion",
            "email_personal", "convenio", "skype_id", "estado",
            "programa", "nombre_curso", "categoria_curso", "itemname"
        ]
        for col in columnas_texto:
            df[col] = df[col].apply(normalizar_texto)

        

        # Normalizar calificaciones
        df["calificacion"] = (
            df["calificacion"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df["calificacion"] = pd.to_numeric(df["calificacion"], errors="coerce")

        # Convertir fechas
        df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"], errors="coerce")
        df["fecha_fin"] = pd.to_datetime(df["fecha_fin"], errors="coerce")
        df["fecha_cargue"] = datetime.now()

        # Dejar solo nota más alta por documento + curso
        df = df.sort_values("calificacion", ascending=False)
        df = df.drop_duplicates(subset=["documento", "nombre_curso"], keep="first").reset_index(drop=True)

        df.to_sql("historial_academico", con=engine, if_exists="replace", index=False)

    except Exception as e:
        
        return templates.TemplateResponse("historial_carga.html", {
            "request": request,
            "error": f"⚠️ Error al subir archivo: {e}"
        })

    return templates.TemplateResponse("historial_carga.html", {
        "request": request,
        "success": f"✅ {len(df)} registros de historial cargados correctamente."
    })
