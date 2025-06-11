FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY store.py .
# ensure the log file exists
RUN touch log.txt
EXPOSE 9000
CMD ["python", "store.py"]
