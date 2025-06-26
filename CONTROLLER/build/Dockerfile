FROM python:3.10-slim

# Instalar dependencias necesarias
RUN pip install --no-cache-dir kopf avisdk pyyaml

# Crear carpeta y copiar código
WORKDIR /app
COPY handler.py .
COPY requirements.txt .

# Ejecutar el controlador
ENTRYPOINT ["kopf", "run", "--standalone", "handler.py"]
