# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire src directory into the container
COPY src/ ./src/

# Change working directory to src, since auto_grader.py expects key.json to be in the same folder
WORKDIR /app/src

# Run auto_grader.py when the container launches
CMD ["python", "auto_grader.py"]
