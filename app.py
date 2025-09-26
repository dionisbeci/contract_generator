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
from flasgger import Swagger
import zipfile

from google.auth.transport import requests
from google.oauth2 import id_token


app = Flask(__name__)


app.config['SWAGGER'] = {
    'title': 'POS PDF Generation API',
    'uiversion': 3,
    "specs_route": "/apidocs/",
    'securityDefinitions': {
        'BearerAuth': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': 'Enter your Google-signed ID token in the format **Bearer &lt;token&gt;**'
        }
    }
}
swagger = Swagger(app)


BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

storage_client = None
bucket = None
COORDINATES = {}
PDF_TEMPLATE_CACHE = {}

try:
    if not BUCKET_NAME:
        logging.critical("FATAL: GCS_BUCKET_NAME environment variable not set.")
    else:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        app.logger.info(f"Successfully connected to GCS bucket: '{BUCKET_NAME}'")

        blob_coords = bucket.blob('coordinates.json')
        COORDINATES = json.loads(blob_coords.download_as_string())
        app.logger.info("Successfully loaded coordinates.json from GCS.")

        blobs_templates = storage_client.list_blobs(BUCKET_NAME, prefix='templates/')
        for blob in blobs_templates:
            if blob.name.endswith('.pdf'):
                template_name = os.path.splitext(os.path.basename(blob.name))[0]
                PDF_TEMPLATE_CACHE[template_name] = io.BytesIO(blob.download_as_bytes())
                app.logger.info(f"Cached template from GCS: '{blob.name}'")

except Exception as e:
    logging.critical(f"FATAL STARTUP ERROR: Could not initialize Google Cloud services. Error: {e}", exc_info=True)

@app.before_request
def verify_google_id_token():
    if request.endpoint and ('static' in request.endpoint or 'flasgger' in request.endpoint):
        return

    auth_header = request.headers.get('Authorization')
    if not auth_header or 'Bearer ' not in auth_header:
        app.logger.warning(f"Unauthorized: Missing or invalid Authorization header. IP: {request.remote_addr}")
        return jsonify({"error": "Unauthorized: Missing Authorization Bearer token."}), 401

    try:
        token = auth_header.split('Bearer ')[1]
        AUDIENCE = os.environ.get('SERVICE_URL')
        if not AUDIENCE:
             app.logger.critical("FATAL: SERVICE_URL environment variable is not set. This must be the full URL of the deployed Cloud Run service.")
             return jsonify({"error": "Server configuration error: Audience not configured."}), 500

        claims = id_token.verify_oauth2_token(
            token, requests.Request(), audience=AUDIENCE
        )
        app.logger.info(f"Authenticated call from: {claims.get('email', 'unknown service account')}")

    except ValueError as e:
        app.logger.warning(f"Unauthorized: Token verification failed. Error: {e}. IP: {request.remote_addr}")
        return jsonify({"error": f"Unauthorized: {e}"}), 401
    except Exception as e:
        app.logger.error(f"An unexpected authentication error occurred: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred during authentication."}), 500


@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    """
    Gjeneron Faturë ose Kontratë në PDF / Generate PDF Invoice or Contract
    This endpoint creates a PDF document by stamping data onto one or more templates.
    The final document is uploaded to Google Cloud Storage and returned to the user.
    ---
    tags:
      - "Gjenerimi i PDF (PDF Generation)"
    security:
      - BearerAuth: []
    consumes:
      - application/json
    produces:
      - application/pdf
    parameters:
      - in: body
        name: body
        required: true
        description: "Të dhënat JSON që përmbajnë template dhe informacionin për t'u plotësuar."
        schema:
          id: PdfGenerationRequest
          required:
            - template_names
            - context
          properties:
            template_names:
              type: array
              example: ["kontrate_template", "oferte_template"]
            context:
              type: object
              example:
                doc_date: "25-09-2025"
                customer_name: "Alb-Tech Servis Sh.p.k."
                customer_nipt: "L12345678P"
                customer_address: "Rruga Sami Frashëri, Nr. 15"
                customer_city: "Tiranë"
                customer_name_sign: "Administratori"
                items:
                  - name: "Printer Fiskal A-Class"
                    qty: 1
                    price: "45000.00"
                    total: "45000.00"
                  - name: "Kontratë Mirëmbajtje Vjetore"
                    qty: 1
                    price: "12000.00"
                    total: "12000.00"
                total: "57000.00"
    responses:
      200:
        description: "Suksess. PDF-ja u gjenerua dhe kthehet si përgjigje."
      401:
        description: "I Paautorizuar. Tokeni i autorizimit mungon, është i pavlefshëm, ose ka skaduar."
      404:
        description: "Nuk u Gjet. Një emër i template ose koordinatat e tij nuk u gjetën në server."
    """

    if not bucket:
        return jsonify({"error": "Server is not configured correctly. Cannot connect to storage."}), 500

    try:
        data = request.get_json()
        template_names = data.get('template_names')
        context = data.get('context')

        if not template_names or not isinstance(template_names, list) or not context:
            return jsonify({"error": "Request must include 'template_names' (as a list) and 'context'."}), 400

        if 'doc_date' in context:
            try:
                datetime.strptime(str(context['doc_date']), '%d-%m-%Y')
            except (ValueError, TypeError):
                app.logger.warning(f"Could not validate doc_date format: '{context.get('doc_date')}'. Using original value.")
                pass

        if 'customer_address' in context and 'customer_city' in context:
            context['customer_full_address'] = f'{context["customer_address"]}, {context["customer_city"]}'

        stamped_pdf_parts = []

        for template_name in template_names:
            template_coords = COORDINATES.get(template_name)
            if not template_coords:
                return jsonify({"error": f"Coordinates for template '{template_name}' not found."}), 404

            if template_name not in PDF_TEMPLATE_CACHE:
                return jsonify({"error": f"Template PDF '{template_name}.pdf' not found in cache."}), 404

            template_buffer = PDF_TEMPLATE_CACHE[template_name]
            template_buffer.seek(0)

            fields_by_page = {}
            for field_name, coords in template_coords.get('static_fields', {}).items():
                page_num = coords.get('page', 1) - 1
                if page_num not in fields_by_page: fields_by_page[page_num] = []
                if field_name in context:
                    fields_by_page[page_num].append({
                        "text": context[field_name], "x": coords['x'], "y": coords['y'],
                        "align": coords.get('align', 'left')
                    })

            items_section_config = template_coords.get('items_section')
            if items_section_config and context.get('items'):
                page_num = items_section_config.get('page', 1) - 1
                if page_num not in fields_by_page: fields_by_page[page_num] = []
                fields_by_page[page_num].extend([
                    {"type": "items_list", "config": items_section_config, "data": context.get('items', [])},
                    {"type": "final_total", "config": items_section_config, "value": context.get('total')}
                ])

            reader = PdfReader(template_buffer)
            writer = PdfWriter()

            for i, page in enumerate(reader.pages):
                if i in fields_by_page:
                    packet = io.BytesIO()
                    can = canvas.Canvas(packet, pagesize=letter)
                    last_item_y = 0
                    for field in fields_by_page[i]:
                        if field.get("type") == "items_list":
                            config, current_y = field['config'], field['config']['start_y']
                            for item in field['data']:
                                can.drawString(config['columns']['name_x'], current_y, str(item.get('name', '')))
                                can.drawString(config['columns']['qty_x'], current_y, str(item.get('qty', '')))
                                can.drawString(config['columns']['price_x'], current_y, str(item.get('price', '')))
                                can.drawString(config['columns']['total_x'], current_y, str(item.get('total', '')))
                                last_item_y = current_y
                                current_y -= config['line_height']
                        elif field.get("type") == "final_total":
                            if field.get('value') and last_item_y > 0:
                                config = field['config']
                                total_y = last_item_y - (2 * config['line_height'])
                                total_x = config['columns']['name_x']
                                can.drawString(total_x, total_y, f"Total: {field['value']}")
                        else:
                            text = str(field['text'])
                            if field.get("align") == "center":
                                text_width = can.stringWidth(text)
                                x_pos = field['x'] - (text_width / 2)
                                can.drawString(x_pos, field['y'], text)
                            else:
                                can.drawString(field['x'], field['y'], text)
                    can.save()
                    packet.seek(0)
                    stamp_pdf = PdfReader(packet)
                    if stamp_pdf.pages:
                        page.merge_page(stamp_pdf.pages[0])
                writer.add_page(page)

            part_buffer = io.BytesIO()
            writer.write(part_buffer)
            stamped_pdf_parts.append(part_buffer)

        final_writer = PdfWriter()
        for part_buffer in stamped_pdf_parts:
            part_buffer.seek(0)
            reader = PdfReader(part_buffer)
            for page in reader.pages:
                final_writer.add_page(page)

        final_buffer = io.BytesIO()
        final_writer.write(final_buffer)
        final_buffer.seek(0)

        nipt = context.get('customer_nipt', 'unknown')
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        file_name = f"{nipt}_{timestamp}.pdf"

        blob_path = f"contracts/{file_name}"
        blob = bucket.blob(blob_path)

        blob.upload_from_file(final_buffer, content_type='application/pdf')
        app.logger.info(f"Successfully uploaded '{file_name}' to GCS.")

        final_buffer.seek(0)
        return send_file(final_buffer, mimetype='application/pdf', as_attachment=True,
                         download_name=file_name)

    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred."}), 500


@app.route('/get-contracts/<string:nipt>', methods=['GET'])
def get_contracts_by_nipt(nipt):
    """
    Merr të gjitha kontratat për një NIPT si skedar ZIP / Get all contracts for a NIPT as a ZIP file
    This endpoint finds all generated PDFs for a given customer NIPT, packages them
    into a single ZIP archive, and returns the archive.
    ---
    tags:
      - "Marrja e Kontratave (Contract Retrieval)"
    security:
      - BearerAuth: []
    produces:
      - application/zip
      - application/json
    parameters:
      - name: nipt
        in: path
        type: string
        required: true
        description: "NIPT-i i klientit për të kërkuar kontratat."
    responses:
      200:
        description: "Suksess. Një skedar ZIP me të gjitha PDF-të e gjetura kthehet si përgjigje."
        content:
            application/zip:
                schema:
                    type: string
                    format: binary
      401:
        description: "I Paautorizuar. Tokeni i autorizimit mungon ose është i pavlefshëm."
      404:
        description: "Nuk u Gjet. Asnjë PDF nuk u gjet për NIPT-in e dhënë."
    """
    if not bucket:
        return jsonify({"error": "Server is not configured correctly. Cannot connect to storage."}), 500

    try:
        prefix = f"contracts/{nipt}_"
        blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=prefix))

        if not blobs:
            app.logger.info(f"No contracts found for NIPT: {nipt}")
            return jsonify({"error": f"No contract PDFs found for NIPT '{nipt}'"}), 404

        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            app.logger.info(f"Found {len(blobs)} contracts for NIPT {nipt}. Creating ZIP archive.")
            for blob in blobs:
                pdf_content = blob.download_as_bytes()
                file_name = os.path.basename(blob.name)
                zf.writestr(file_name, pdf_content)

        zip_buffer.seek(0)
        
        zip_download_name = f"{nipt}_contracts.zip"

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_download_name
        )

    except Exception as e:
        app.logger.error(f"An unexpected error occurred while fetching contracts for NIPT {nipt}: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred."}), 500



@app.route('/get-contract/<string:nipt>', methods=['GET'])
def get_latest_contract_by_nipt(nipt):
    """
    Merr kontratën më të fundit për një NIPT / Get the latest contract for a NIPT
    This endpoint finds the most recently generated PDF for a given customer NIPT
    and returns that single file.
    ---
    tags:
      - "Marrja e Kontratave (Contract Retrieval)"
    security:
      - BearerAuth: []
    produces:
      - application/pdf
      - application/json
    parameters:
      - name: nipt
        in: path
        type: string
        required: true
        description: "NIPT-i i klientit për të kërkuar kontratën më të fundit."
    responses:
      200:
        description: "Suksess. PDF-ja më e fundit u gjet dhe kthehet si përgjigje."
        content:
            application/pdf:
                schema:
                    type: string
                    format: binary
      401:
        description: "I Paautorizuar. Tokeni i autorizimit mungon ose është i pavlefshëm."
      404:
        description: "Nuk u Gjet. Asnjë PDF nuk u gjet për NIPT-in e dhënë."
    """
    if not bucket:
        return jsonify({"error": "Server is not configured correctly. Cannot connect to storage."}), 500

    try:
        prefix = f"contracts/{nipt}_"
        blobs = list(storage_client.list_blobs(BUCKET_NAME, prefix=prefix))

        if not blobs:
            app.logger.info(f"No contract found for NIPT: {nipt}")
            return jsonify({"error": f"No contract PDF found for NIPT '{nipt}'"}), 404


        latest_blob = blobs[-1]
        app.logger.info(f"Found latest contract for NIPT {nipt}: {latest_blob.name}")

        pdf_buffer = io.BytesIO(latest_blob.download_as_bytes())
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=os.path.basename(latest_blob.name)
        )

    except Exception as e:
        app.logger.error(f"An unexpected error occurred while fetching PDF for NIPT {nipt}: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred."}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)