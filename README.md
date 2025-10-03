# POS Contract Generation API

## Overview

This project is a Python-based microservice designed to automate the generation and management of PDF contracts. Built with Flask, it provides a secure, robust API that integrates with Google Cloud Storage (GCS) for templating and document storage.

The service is designed to be deployed to modern, serverless environments and includes instructions for two primary Google Cloud targets:
*   **Google Cloud Run:** A serverless platform for running containerized applications.
*   **Google Cloud Functions:** A serverless, event-driven compute platform for running individual functions.

---

## Features

*   **Dynamic PDF Generation:** Creates stamped and merged PDFs from predefined templates (`.pdf` files) and dynamic data (`JSON` payload).
*   **Secure Cloud Storage:** All generated contracts are securely stored and versioned in a dedicated Google Cloud Storage bucket.
*   **Modern Authentication:** Endpoints are secured using Google's native IAM authentication (ID Tokens), not static API keys.
*   **Multiple Retrieval Options:**
    *   Fetch the single most recent contract for a given client NIPT.
    *   Fetch all historical contracts for a given client NIPT, conveniently packaged into a single `.zip` file.
*   **Interactive API Documentation:** Includes a live, auto-generated API documentation page (Swagger UI via Flasgger) available at the `/apidocs/` endpoint.

---

## API Documentation

The live, interactive API documentation for the deployed services can be accessed at their respective URLs:

*   **Cloud Run URL:** `https://pdf-generator-service-274189806325.europe-west8.run.app/apidocs/`
*   **Cloud Function URL:** `https://europe-west8-pdf-contract-generator.cloudfunctions.net/contract-generator-function/apidocs/`

These pages provide detailed information on all available endpoints and allow for direct testing within the browser.

---

## Architecture & Security

*   **Framework:** Flask (Python)
*   **WSGI Server (Cloud Run):** Gunicorn
*   **Hosting:** Google Cloud Run (Serverless Containers) & Google Cloud Functions (FaaS)
*   **Storage:** Google Cloud Storage

**Security Model:** The API uses short-lived, Google-signed ID Tokens for authentication. A client (e.g., another Google service or an authorized user) must first authenticate with Google to receive a temporary token. The service then cryptographically verifies that the token is valid, unexpired, and intended for its specific URL (the "audience"). This is the recommended best practice for service-to-service communication on Google Cloud.

---

## Running the Application Locally

These instructions are for running the service on a local machine for development and testing.

### Prerequisites

*   Python 3.11+
*   Google Cloud SDK (`gcloud` CLI) installed and authenticated.
*   A local copy of the source code.
*   A Google Cloud service account key file (`.json`) for authentication.

### 1. Setup

**a. Create a Virtual Environment:**
```powershell
# Navigate to the project directory
cd path\to\contract_generator

# Create and activate the virtual environment
python -m venv venv
.\venv\Scripts\Activate
```

**b. Install Dependencies:**
```powershell
pip install -r requirements.txt
```

### 2. Configuration (Environment Variables)

The application requires several environment variables to run. Set them in your PowerShell terminal.

```powershell
# 1. Set the path to your Google Cloud credentials JSON file
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your\google-key.json"

# 2. Set the name of the Google Cloud Storage bucket
$env:GCS_BUCKET_NAME="pos-contract"

# 3. Set the public URL of the DEPLOYED service.
#    This is required for token validation. Use the URL for the service you intend to test.
#    Example for Cloud Run:
$env:SERVICE_URL="https://pdf-generator-service-274189806325.europe-west8.run.app"
```

### 3. Run the Application
To run the local Flask server, ensure your `main.py` file still contains the `if __name__ == '__main__':` block.
```powershell
python main.py
```
The application will start and be accessible at `http://127.0.0.1:8080`.

## Testing the Deployed API

Because the API is secured, you must generate a valid ID token and include it in the request header.

### Testing the Cloud Run API

**1. Generate an ID Token:**
```powershell
# The audience is the public URL of the deployed Cloud Run service
$audience = "https://pdf-generator-service-274189806325.europe-west8.run.app"
$sa_email = "pdf-generator-service@pdf-contract-generator.iam.gserviceaccount.com"

# This command generates the token and stores it in a variable
$token = gcloud auth print-identity-token --audiences="$audience" --impersonate-service-account="$sa_email"
```

**2. Make API Calls:**
```powershell
# Create a PDF
Invoke-WebRequest -Method POST -Uri "$audience/generate-pdf" -Headers @{ "Authorization" = "Bearer $token" } -InFile "request_body.json" -ContentType "application/json" -OutFile "cloud_run_contract.pdf"

# Get all contracts for a NIPT (as a ZIP)
$nipt = "L12345678A"
Invoke-WebRequest -Uri "$audience/get-contracts/$nipt" -Headers @{ "Authorization" = "Bearer $token" } -OutFile "all_contracts.zip"
```

### Testing the Cloud Functions API

**1. Generate an ID Token:**
```powershell
# IMPORTANT: The audience is the underlying service URL of the 2nd Gen Function.
$audience = "https://contract-generator-function-htmxpfbu2q-oc.a.run.app"
$sa_email = "pdf-generator-service@pdf-contract-generator.iam.gserviceaccount.com"

# This command generates the token and stores it in a variable
$token = gcloud auth print-identity-token --audiences="$audience" --impersonate-service-account="$sa_email"
```

**2. Make API Calls:**
```powershell
# The request URL is the public trigger URL of the function
$requestUrl = "https://europe-west8-pdf-contract-generator.cloudfunctions.net/contract-generator-function"

# Create a PDF
Invoke-WebRequest -Method POST -Uri "$requestUrl/generate-pdf" -Headers @{ "Authorization" = "Bearer $token" } -InFile "request_body.json" -ContentType "application/json" -OutFile "cloud_function_contract.pdf"

# Get all contracts for a NIPT (as a ZIP)
$nipt = "L12345678A"
Invoke-WebRequest -Uri "$requestUrl/get-contracts/$nipt" -Headers @{ "Authorization" = "Bearer $token" } -OutFile "all_contracts.zip"
```
## Deployment

### A) Deployment to Google Cloud Run

The application is deployed as a container on Google Cloud Run. The `gcloud` CLI automatically handles container builds and service updates.

*   **`Dockerfile`**: Contains instructions to build the application's container image.
*   **`.gcloudignore`**: Specifies files to exclude from the upload to speed up deployment.

**Deployment Command:**
```powershell
gcloud run deploy pdf-generator-service --source . --region europe-west8
```
This command uploads the code, builds the container image, pushes it to the Artifact Registry, and creates a new revision of the Cloud Run service.

**Environment Variables for Cloud Run:** After deployment, ensure the `GCS_BUCKET_NAME` and `SERVICE_URL` variables are set correctly in the Cloud Run service's "Variables & Secrets" tab in the Google Cloud Console.

### B) Deployment to Google Cloud Functions

The application can also be deployed as a 2nd Generation HTTP Function. This method does not use the `Dockerfile`.

*   **`main.py`**: Must contain a single callable function (e.g., `contract_generator`) to act as the entry point.
*   **`requirements.txt`**: Defines the Python dependencies.

**Deployment Command:**
```powershell
# NOTE: The environment variables are set directly in the deployment command.
# Use quotes around the --set-env-vars value in PowerShell to ensure it's parsed correctly.

gcloud functions deploy contract-generator-function --gen2 --runtime=python311 --region=europe-west8 --source=. --entry-point=contract_generator --trigger-http --allow-unauthenticated --set-env-vars="GCS_BUCKET_NAME=pos-contract,SERVICE_URL=https://contract-generator-function-htmxpfbu2q-oc.a.run.app"
```
This command uploads the code, builds a serving environment, and deploys it as a Cloud Function.

**Explanation of Flags:**
*   `--gen2`: Specifies the 2nd generation environment.
*   `--entry-point`: The name of the Python function in `main.py` to be invoked.
*   `--trigger-http`: Makes the function accessible via a public URL.
*   `--allow-unauthenticated`: Allows public access; security is handled by our ID token check.
*   `--set-env-vars`: Sets the necessary environment variables for the function.
