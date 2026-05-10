import os
import io
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
from dotenv import load_dotenv
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = os.getenv('CLIENT_SECRET_FILE', 'client_secret.json')
ROOT_FOLDER_ID = os.getenv('ROOT_FOLDER_ID', '1YS4fhaAhKIZRtq_Tla0uNv1bDa2Qby7u') 
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '30'))  # Check for new files every X seconds

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
    """Uploads a new file to a specific Google Drive folder."""
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaFileUpload(local_path, mimetype=mimetype)
    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def update_file(drive_service, local_path, file_id, mimetype='text/plain'):
    """Updates an existing file on Google Drive (doesn't create duplicates)."""
    media = MediaFileUpload(local_path, mimetype=mimetype)
    drive_service.files().update(fileId=file_id, media_body=media).execute()

def download_text(drive_service, file_id):
    """Downloads a text file from Drive and returns its content as a string."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return fh.getvalue().decode('utf-8')

def process_files(drive_service):
    """Scans folders, grades ungraded files, and uploads results."""
    folder_query = f"'{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = drive_service.files().list(q=folder_query, fields='files(id, name)').execute().get('files', [])

    if not folders:
        print(f"[ℹ️ Info] No group folders found. Check Folder ID and permissions.")

    for folder in folders:
        folder_id = folder['id']
        folder_name = folder['name']
        
        # 1. Find all submission files. Request md5Checksum to track if the file changed.
        file_query = f"'{folder_id}' in parents and trashed=false and (name contains '.csv' or name contains '.xlsx')"
        all_files = drive_service.files().list(q=file_query, fields='files(id, name, md5Checksum)').execute().get('files', [])

        # FILTER: Ignore files that are grading results or error logs
        sub_files = []
        for f in all_files:
            if f['name'].endswith('_rows.csv') or f['name'].endswith('_grade.csv') or f['name'].endswith('_error.txt'):
                continue
            sub_files.append(f)

        for sub_file in sub_files:
            file_name = sub_file['name']
            file_id = sub_file['id']
            file_md5 = sub_file.get('md5Checksum', 'unknown') 
            stem = Path(file_name).stem
            
            # 2. Check if already successfully graded
            grade_name = f"{stem}_grade.csv"
            grade_query = f"'{folder_id}' in parents and name='{grade_name}' and trashed=false"
            if drive_service.files().list(q=grade_query, fields='files(id)').execute().get('files', []):
                continue # Graded successfully, skip forever
            
            # 3. Check if previously errored
            error_name = f"{stem}_error.txt"
            error_query = f"'{folder_id}' in parents and name='{error_name}' and trashed=false"
            error_files = drive_service.files().list(q=error_query, fields='files(id)').execute().get('files', [])
            
            error_file_id = None
            if error_files:
                error_file_id = error_files[0]['id']
                
                # Read the existing error file to see the stored MD5 fingerprint
                old_error_text = download_text(drive_service, error_file_id)
                saved_md5 = None
                for line in old_error_text.splitlines():
                    if line.startswith("FILE_MD5: "):
                        saved_md5 = line.replace("FILE_MD5: ", "").strip()
                        break
                
                # SMART LOGIC: If the MD5 matches, the user hasn't fixed the file. DO NOTHING.
                if saved_md5 and saved_md5 == file_md5:
                    continue 
            
            # --- If we reach here, the file is either new, or the user uploaded a new version of the broken file ---
            
            print(f"[🚀 New Submission] Found {file_name} in {folder_name}. Grading...")
            
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = os.path.join(tmpdir, file_name)
                request = drive_service.files().get_media(fileId=file_id)
                with open(local_path, 'wb') as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                
                try:
                    row_results, summary = score_submission(Path(local_path))
                    
                    rows_path = os.path.join(tmpdir, f"{stem}_rows.csv")
                    grade_path = os.path.join(tmpdir, grade_name)
                    
                    write_csv(Path(rows_path), format_row_report(row_results))
                    write_csv(Path(grade_path), [format_summary(summary)])
                    
                    # If an error file existed from a previous attempt, DELETE IT (they fixed it!)
                    if error_file_id:
                        drive_service.files().delete(fileId=error_file_id).execute()
                        
                    upload_file(drive_service, rows_path, f"{stem}_rows.csv", folder_id)
                    upload_file(drive_service, grade_path, grade_name, folder_id)
                    print(f"[✅ Success] Graded and uploaded results for {file_name}")

                except Exception as e:
                    # Build the new error message with the current MD5 fingerprint
                    new_error_msg = (
                        f"FILE_MD5: {file_md5}\n\n"
                        f"Grading failed for {file_name}.\n\n"
                        f"Error details:\n{str(e)}\n\n"
                        f"IMPORTANT: If you fix and re-upload this file, it will be automatically re-graded."
                    )
                    error_path = os.path.join(tmpdir, error_name)
                    with open(error_path, 'w') as f:
                        f.write(new_error_msg)
                    
                    if error_file_id:
                        # UPDATE the existing error file on Drive (no duplicates!)
                        update_file(drive_service, error_path, error_file_id, mimetype='text/plain')
                        print(f"[⚠️ Updated] Error details updated for {file_name}")
                    else:
                        # CREATE the first error file
                        upload_file(drive_service, error_path, error_name, folder_id, mimetype='text/plain')
                        print(f"[❌ Error] Failed to grade {file_name}. Error file created.")

def main():
    if not ROOT_FOLDER_ID or ROOT_FOLDER_ID == 'PASTE_YOUR_HACKATHON_ANSWERS_FOLDER_ID_HERE':
        print("❌ ERROR: You forgot to set your Hackathon_Answers Folder ID!")
        return

    try:
        drive_service = get_drive_service()
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Google Drive. Details: {e}")
        return

    print("Starting Hackathon Auto-Grader... Press Ctrl+C to stop.")
    while True:
        try:
            process_files(drive_service)
        except Exception as e:
            print(f"An error occurred during the polling cycle: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()