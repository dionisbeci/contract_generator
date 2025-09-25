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
def require_api_key():
  
    if request.endpoint and 'static' in request.endpoint:
        return

    api_key = request.headers.get('X-API-KEY')

    VALID_API_KEY = os.environ.get('API_KEY')

    if not VALID_API_KEY:
        app.logger.critical("FATAL: API_KEY environment variable is not set. Server cannot authenticate requests.")
        return jsonify({"error": "Server configuration error"}), 500

    if not api_key or api_key != VALID_API_KEY:
        app.logger.warning(f"Unauthorized access attempt from IP: {request.remote_addr}")
        return jsonify({"error": "Unauthorized"}), 401



@app.route('/generate-merged-pdf', methods=['POST'])
def generate_merged_pdf():

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
            context['customer_full_address'] = f'"{context["customer_address"]}", {context["customer_city"]}'

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

   
        nipt = context.get('nipt', 'UNKNOWN_NIPT')
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        file_name = f"{nipt}_{timestamp}.pdf"
        
        blob_path = f"contracts/{file_name}"
        blob = bucket.blob(blob_path)
        
        blob.upload_from_file(final_buffer, content_type='application/pdf')
        app.logger.info(f"Successfully uploaded '{file_name}' to GCS.")

      
        final_buffer.seek(0)
        return send_file(final_buffer, mimetype='application/pdf', as_attachment=True,
                         download_name='merged_document.pdf')

    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred."}), 500



if __name__ == '__main__':
   
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)