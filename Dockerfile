# Use an official Python image as a base
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements file to the container
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

WORKDIR /app/bot

# Specify the command to run the application
CMD ["python3", "main.py"]
