# POS Contract Generation API

## Overview

This project is a Python-based microservice designed to automate the generation and management of PDF contracts. Built with Flask, it provides a secure, robust API that integrates with Google Cloud Storage (GCS) for templating and document storage.

The service is containerized using Docker and deployed on Google Cloud Run, ensuring scalability, security, and ease of maintenance.

---

## Features

*   **Dynamic PDF Generation:** Creates stamped and merged PDFs from predefined templates (`.pdf` files) and dynamic data (`JSON` payload).
*   **Secure Cloud Storage:** All generated contracts are securely stored and versioned in a dedicated Google Cloud Storage bucket.
*   **Modern Authentication:** Endpoints are secured using Google's native IAM authentication (ID Tokens), not static API keys, which is a significant security enhancement.
*   **Multiple Retrieval Options:**
    *   Fetch the single most recent contract for a given client NIPT.
    *   Fetch all historical contracts for a given client NIPT, conveniently packaged into a single `.zip` file.
*   **Interactive API Documentation:** Includes a live, auto-generated API documentation page (Swagger UI via Flasgger) available at the `/apidocs/` endpoint.

---

## API Documentation

The live, interactive API documentation for the deployed service can be accessed at:

**[https://pdf-generator-service-274189806325.europe-west8.run.app/apidocs/](https://pdf-generator-service-274189806325.europe-west8.run.app/apidocs/)**

This page provides detailed information on all available endpoints and allows for direct testing within the browser.

---

## Architecture & Security

*   **Framework:** Flask (Python)
*   **WSGI Server:** Gunicorn (Production-grade)
*   **Hosting:** Google Cloud Run (Serverless Container Platform)
*   **Storage:** Google Cloud Storage

**Security Model:** The API has been designed with a modern, secure authentication model. Instead of using a static, long-lived API key (which can be leaked or compromised), this service uses short-lived, Google-signed ID Tokens.

*   **How it works:** A client (e.g., another Google service or an authorized user) must first authenticate with Google to receive a temporary token. This token is sent with the API request. The service then cryptographically verifies with Google that the token is valid, unexpired, and was issued to a client with the correct permissions.
*   **Benefits:** This is the recommended best practice for service-to-service communication on Google Cloud, as it eliminates the need to manage and protect secret keys. Access is controlled via Google's standard IAM roles.

---

## Running the Application Locally

These instructions are for running the service on a local machine for development and testing.

### Prerequisites

*   Python 3.11+
*   Google Cloud SDK (`gcloud` CLI) installed and authenticated.
*   A local copy of the source code.
*   A Google Cloud service account key file (`.json`).

### 1. Setup

**a. Create a Virtual Environment:**
```powershell
# Navigate to the project directory
cd path\to\contract_generator
```

# Create and activate the virtual environment
python -m venv venv
.\venv\Scripts\Activate

**b. Create a Virtual Environment:**
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

# 3. Set the public URL of the DEPLOYED service. This is required for token validation.
$env:SERVICE_URL="https://pdf-generator-service-274189806325.europe-west8.run.app"```
```

### 3. Run the Application 

```powershell
python app.py
```


 The application will start and be accessible at http://127.0.0.1:8080.

## Testing the API

 Because the API is secured, you cannot test it by simply visiting the URLs in a browser. You must generate a valid ID token and include it in the request header.

### 1. Generate an ID Token

 Open a new PowerShell terminal. Run the command below, replacing the placeholder with the email of the service account that has the "Service Account Token Creator" role for this service.

 The service account email is likely 'pdf-generator-service@pdf-contract-generator.iam.gserviceaccount.com'
```powershell
$sa_email = "SERVICE_ACCOUNT_EMAIL_HERE"
```
```powershell
# The audience is the public URL of the deployed service
$audience = "https://pdf-generator-service-274189806325.europe-west8.run.app"
```
```powershell
# This command generates the token and stores it in a variable
$token = gcloud auth print-identity-token --audiences="$audience" --impersonate-service-account="$sa_email"
```

### 2. Make API Calls

 Now you can use the $token variable to make authenticated calls.

**a. Get the latest contract for a NIPT:**
```powershell
$nipt = "L12345678A" # Replace with a real NIPT
Invoke-WebRequest -Uri "http://127.0.0.1:8080/get-contract/$nipt" -Headers @{ "Authorization" = "Bearer $token" } -OutFile "latest_contract.pdf"
```

**b. Get all contracts for a NIPT (as a ZIP):**
```powershell
$nipt = "L12345678A" # Replace with a real NIPT
Invoke-WebRequest -Uri "http://127.0.0.1:8080/get-contracts/$nipt" -Headers @{ "Authorization" = "Bearer $token" } -OutFile "all_contracts.zip"
```

## Deployment to Google Cloud Run

The application is deployed as a container on Google Cloud Run. The deployment process is managed by the `gcloud` CLI, which automatically handles container builds and service updates.

### Deployment Files

*   `Dockerfile`: Contains the instructions to build the application's container image, including installing dependencies and setting the run command.
*   `requirements.txt`: A list of all Python libraries required by the application.
*   `.gcloudignore`: Specifies files and directories (like the `venv` folder) to exclude from the upload to speed up deployment.

### Deployment Command

To deploy any changes to the application, navigate to the project root directory and run the following command in a terminal:

```powershell
# The region must match the region where the service is hosted
gcloud run deploy pdf-generator-service --source . --region europe-west8
```

This single command automatically performs several steps:
1.  Uploads your source code (respecting `.gcloudignore`).
2.  Uses Google Cloud Build to execute the `Dockerfile` and create a container image.
3.  Pushes the newly built image to Googles Artifact Registry for storage.
4.  Creates a new, immutable revision of your Cloud Run service using the new container image.
5.  Routes 100% of live traffic to this new revision.

### Verifying and Setting Environment Variables

The application code depends on environment variables to function correctly. **This is a critical step.** If these variables are not set, the service will not start correctly. After a deployment, you should always verify they are configured properly.

You can manage these variables through the Google Cloud Console.

1.  **Navigate to the Cloud Run Console:**
    *   Open the [Google Cloud Run page](https://console.cloud.google.com/run).

2.  **Select the Service:**
    *   Click on the `pdf-generator-service` in the list to open its details page.

3.  **Edit the Configuration:**
    *   Click the **"EDIT & DEPLOY NEW REVISION"** button at the top of the page.

4.  **Open the Variables Tab:**
    *   In the configuration screen, navigate to the **"VARIABLES & SECRETS"** tab.

5.  **Verify the Variables:**
    *   Ensure the following two variables are present and have the correct values. If a variable is missing or incorrect, you can add or edit it here.

    *   **Variable 1:**
        *   **Name:** `GCS_BUCKET_NAME`
        *   **Value:** `pos-contract`

    *   **Variable 2:**
        *   **Name:** `SERVICE_URL`
        *   **Value:** The full public URL of the service itself (e.g., `https://pdf-generator-service-274189806325.europe-west8.run.app`).

6.  **Deploy the Changes:**
    *   **If you made any changes** to the variables, scroll to the bottom and click the **"DEPLOY"** button. This will start the deployment of a new revision.
    *   **If the variables were already correct**, you can simply click **"CANCEL"** or navigate away from the page, as no changes are needed.

    The deployment process will take a minute or two. Once it completes with green checkmarks, the new revision is live and serving 100% of traffic. The application is now fully deployed and running with the correct configuration.