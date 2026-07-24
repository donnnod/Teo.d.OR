FROM python:3.11-slim

WORKDIR /app

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "."

# Copy service code
COPY teo/ teo/

ENV TEO_HOST=0.0.0.0
ENV TEO_PORT=8001

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "teo.main:app", "--host", "0.0.0.0", "--port", "8001"]
