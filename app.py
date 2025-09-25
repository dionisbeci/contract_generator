from flask import Flask, request, jsonify, send_file
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import logging
import io
import json
from datetime import datetime
from google.cloud import storage
import os

app = Flask(__name__)

# --- Configuration ---
# It's better to load these from environment variables for security
# For local testing, you can set them directly. For deployment, use environment variables.
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'path/to/your/credentials.json'
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'your-gcs-bucket-name')

# Initialize Google Cloud Storage client
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load Coordinates ---
try:
    # In a cloud environment, coordinates.json should also be in the bucket
    blob = bucket.blob('coordinates.json')
    COORDINATES = json.loads(blob.download_as_string())
    app.logger.info("Successfully loaded coordinates.json from GCS.")
except Exception as e:
    app.logger.error(f"FATAL ERROR: Could not load coordinates.json from GCS. Error: {e}")
    COORDINATES = {}

# --- PDF Template Caching ---
PDF_TEMPLATE_CACHE = {}
try:
    # List all blobs in the 'templates/' prefix (folder) in GCS
    blobs = storage_client.list_blobs(BUCKET_NAME, prefix='templates/')
    for blob in blobs:
        if blob.name.endswith('.pdf'):
            template_name = os.path.splitext(os.path.basename(blob.name))[0]
            PDF_TEMPLATE_CACHE[template_name] = io.BytesIO(blob.download_as_bytes())
            app.logger.info(f"Cached template from GCS: '{blob.name}'")
except Exception as e:
    app.logger.error(f"FATAL ERROR: Could not cache PDF templates from GCS. Error: {e}")

# --- Security Middleware (Simple API Key Auth) ---
# It's a good practice to move this to a separate file in a real application
@app.before_request
def require_api_key():
    # Exclude health check endpoints if you have them
    if request.endpoint and 'static' not in request.endpoint:
        api_key = request.headers.get('X-API-KEY')
        # Store your actual API key securely, e.g., as an environment variable
        VALID_API_KEY = os.environ.get('API_KEY', 'your-secret-api-key')
        if not api_key or api_key != VALID_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

@app.route('/generate-merged-pdf', methods=['POST'])
def generate_merged_pdf():
    try:
        data = request.get_json()
        template_names = data.get('template_names')
        context = data.get('context')

        if not template_names or not isinstance(template_names, list) or not context:
            return jsonify({"error": "Request must include 'template_names' (as a list) and 'context'."}), 400

        # --- Stamping Logic (largely unchanged) ---
        # ... (Your existing PDF generation logic remains the same here)
        # ...

        # --- Save to Google Cloud Storage ---
        final_buffer.seek(0)
        
        # Naming convention: NIPT_timestampKrijimi.pdf
        nipt = context.get('nipt', 'UNKNOWN_NIPT') # Get NIPT from context or use a default
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        file_name = f"{nipt}_{timestamp}.pdf"
        
        # Define the path in the bucket where the contract will be stored
        blob_path = f"contracts/{file_name}"
        blob = bucket.blob(blob_path)
        
        # Upload the PDF buffer
        blob.upload_from_file(final_buffer, content_type='application/pdf')
        app.logger.info(f"Successfully uploaded '{file_name}' to GCS bucket '{BUCKET_NAME}'.")

        # --- Return the generated PDF ---
        final_buffer.seek(0)
        return send_file(final_buffer, mimetype='application/pdf', as_attachment=True,
                         download_name='merged_document.pdf')

    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred."}), 500

if __name__ == '__main__':
    # For local development, it's helpful to specify the host and port
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)