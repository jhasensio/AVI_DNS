FROM python:3.11-slim

# Install dependencies
RUN pip install --no-cache-dir kopf avisdk pyyaml

# Create folder and add files
WORKDIR /app
COPY avidnsoperator.py .
COPY requirements.txt .

# Command to launch operator
ENTRYPOINT ["kopf", "run", "--standalone", "avidnsoperator.py"]
