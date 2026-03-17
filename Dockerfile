FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install system dependencies
# We need ffmpeg for video/audio stitching and build-essential for library compilation
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Ensure the subfolder is treated as a package
RUN touch the_other_side/__init__.py

EXPOSE 8080

# Using python main.py allows your if __name__ == "__main__" block to handle the config
CMD ["python", "main.py"]
