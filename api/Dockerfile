# Use a slim Python image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install Flask
RUN pip install --no-cache-dir flask

# Copy API code
COPY app.py .

# Expose new port
EXPOSE 8000

# Start the Flask app on port 8000
CMD ["python", "app.py"]
