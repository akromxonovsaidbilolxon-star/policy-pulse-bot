FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr so logs appear immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy dependency definition and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

# Run the bot
CMD ["python", "main.py"]
