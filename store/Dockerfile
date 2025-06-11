FROM python:3.9-slim
WORKDIR /app

# Copy store code and ensure the log file exists
COPY store.py .
RUN touch log.txt

# Run the store script (you'll likely replace this with a long-running server later)
CMD ["python", "store.py"]
