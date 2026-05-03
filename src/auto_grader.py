import os
import tempfile
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Import grading logic from the existing script
from submission_check import score_submission, write_csv, format_row_report, format_summary

# --- CONFIGURATION ---
import os
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = os.getenv('CLIENT_SECRET_FILE', 'client_secret.json')
ROOT_FOLDER_ID = os.getenv('ROOT_FOLDER_ID', '1YS4fhaAhKIZRtq_Tla0uNv1bDa2Qby7u') 
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '30'))          # Check for new files every 30 seconds
ERROR_COOLDOWN = int(os.getenv('ERROR_COOLDOWN', '300'))       # If a file fails, wait 300 seconds (5 mins) before trying again

def get_drive_service():
    """Authenticates using OAuth and returns Drive API service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    drive_service = build('drive', 'v3', credentials=creds)
    return drive_service

def upload_file(drive_service, local_path, file_name, folder_id, mimetype='text/csv'):
    """Uploads a file to a specific Google Drive folder."""
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaFileUpload(local_path, mimetype=mimetype)
    drive_service.files().create(
        body=file_metadata, media_body=media, fields='id').execute()

def process_files(drive_service, failed_files):
    """Scans folders, grades ungraded files, and uploads results."""
    folder_query = f"'{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = drive_service.files().list(q=folder_query, fields='files(id, name)').execute().get('files', [])

    if not folders:
        print(f"[ℹ️ Info] No group folders found. Check Folder ID and permissions.")

    for folder in folders:
        folder_id = folder['id']
        folder_name = folder['name']
        
        # 2. Find all submission files (.csv or .xlsx) in this team's folder
        file_query = f"'{folder_id}' in parents and trashed=false and (name contains '.csv' or name contains '.xlsx')"
        all_files = drive_service.files().list(q=file_query, fields='files(id, name)').execute().get('files', [])

        # FILTER: Ignore files that are grading results or error logs
        sub_files = []
        for f in all_files:
            if f['name'].endswith('_rows.csv') or f['name'].endswith('_grade.csv') or f['name'].endswith('_error.txt'):
                continue
            sub_files.append(f)

        for sub_file in sub_files:
            file_name = sub_file['name']
            file_id = sub_file['id']
            stem = Path(file_name).stem
            
            # --- COOLDOWN CHECK ---
            # If this file failed before, check if it's still on cooldown
            if file_id in failed_files:
                time_since_fail = time.time() - failed_files[file_id]
                if time_since_fail < ERROR_COOLDOWN:
                    continue # Still on cooldown, skip quietly
                else:
                    # Cooldown over, remove from dict so we can try again
                    del failed_files[file_id] 

            # 3. Check if this file has already been graded successfully
            grade_name = f"{stem}_grade.csv"
            check_query = f"'{folder_id}' in parents and name='{grade_name}' and trashed=false"
            existing = drive_service.files().list(q=check_query, fields='files(id)').execute().get('files', [])
            
            if existing:
                continue # Already graded, skip
            
            print(f"[🚀 New Submission] Found {file_name} in {folder_name}. Grading...")
            
            # 4. Download to a temporary directory
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = os.path.join(tmpdir, file_name)
                request = drive_service.files().get_media(fileId=file_id)
                with open(local_path, 'wb') as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                
                # 5. Run the grading logic
                try:
                    row_results, summary = score_submission(Path(local_path))
                    
                    # Save locally in temp dir
                    rows_path = os.path.join(tmpdir, f"{stem}_rows.csv")
                    grade_path = os.path.join(tmpdir, grade_name)
                    
                    write_csv(Path(rows_path), format_row_report(row_results))
                    write_csv(Path(grade_path), [format_summary(summary)])
                    
                    # 6. Upload results back to the team's folder
                    upload_file(drive_service, rows_path, f"{stem}_rows.csv", folder_id)
                    upload_file(drive_service, grade_path, grade_name, folder_id)
                    print(f"[✅ Success] Graded and uploaded results for {file_name}")

                except Exception as e:
                    # --- HANDLE FAILURE ---
                    # Add to cooldown dictionary
                    failed_files[file_id] = time.time()
                    print(f"[❌ Error] Failed to grade {file_name}. Placed on {ERROR_COOLDOWN}s cooldown. Error: {e}")
                    
                    # Upload an error file so the team knows something went wrong
                    error_msg = f"Grading failed for {file_name}.\n\nError details:\n{str(e)}\n\nPlease fix your file and re-upload."
                    error_path = os.path.join(tmpdir, f"{stem}_error.txt")
                    with open(error_path, 'w') as f:
                        f.write(error_msg)
                    
                    try:
                        upload_file(drive_service, error_path, f"{stem}_error.txt", folder_id, mimetype='text/plain')
                    except Exception as upload_err:
                        print(f"[❌ Error] Couldn't even upload the error file: {upload_err}")

def main():
    if ROOT_FOLDER_ID == 'PASTE_YOUR_HACKATHON_ANSWERS_FOLDER_ID_HERE':
        print("❌ ERROR: You forgot to paste your Hackathon_Answers Folder ID into the script!")
        return

    try:
        drive_service = get_drive_service()
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Google Drive. Details: {e}")
        return

    # Dictionary to track failed files: {file_id: timestamp_of_failure}
    failed_files = {}

    print("Starting Hackathon Auto-Grader... Press Ctrl+C to stop.")
    while True:
        try:
            process_files(drive_service, failed_files)
        except Exception as e:
            print(f"An error occurred during the polling cycle: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()