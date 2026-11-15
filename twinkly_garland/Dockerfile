FROM python:3.12-alpine

WORKDIR /opt/twinkly
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /opt/twinkly/app/

ENV PYTHONUNBUFFERED=1
EXPOSE 8099
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
