# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app/src

# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire directory into the container
COPY . .

# Run auto_grader.py when the container launches
CMD ["python", "auto_grader.py"]
