from datetime import datetime
from sqlalchemy import create_engine
import pandas as pd

# Conexión MySQL
engine = create_engine("mysql+pymysql://root:123456789@localhost/tecmd")

# Verificar si ya existe la columna
with engine.connect() as connection:
    result = connection.execute("SHOW COLUMNS FROM notas_convenio LIKE 'fecha_cargue'")
    if result.fetchone() is None:
        connection.execute("ALTER TABLE notas_convenio ADD COLUMN fecha_cargue DATETIME")

# Leer y actualizar datos
df = pd.read_sql("SELECT * FROM notas_convenio", con=engine)
df["fecha_cargue"] = datetime.now()

# Guardar cambios
df.to_sql("notas_convenio", con=engine, if_exists="replace", index=False)

print("✅ Columna 'fecha_cargue' añadida y actualizada correctamente.")
