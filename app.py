import streamlit as st
import cv2
import numpy as np
from PIL import Image
import os
import re
import gspread
from streamlit_js_eval import get_geolocation
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openpyxl import Workbook
import pandas as pd
from datetime import datetime

# Setup folders
IMAGE_DIR = "tree_images"
EXPORT_DIR = "exports"
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# Google Sheets and Drive Setup
SHEET_NAME = "TreeQRDatabase"
GOOGLE_DRIVE_FOLDER_ID = "1iddkNU3O1U6bsoHge1m5a-DDZA_NjSVz"

creds_dict = st.secrets["CREDS_JSON"]
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Modern auth for Google API client
modern_creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scope)
drive_service = build("drive", "v3", credentials=modern_creds)

def get_worksheet():
    return client.open(SHEET_NAME).sheet1

def load_entries_from_gsheet():
    sheet = get_worksheet()
    rows = sheet.get_all_values()[1:]
    entries = []
    for row in rows:
        if len(row) >= 7:
            entries.append({
                "Tree Name": row[0], "Name": row[1],
                "Overall Height": row[2], "DBH": row[3], "Canopy": row[4],
                "Latitude": row[5], "Longitude": row[6]
            })
    return entries

def save_to_gsheet(entry):
    sheet = get_worksheet()
    sheet.append_row([
        entry["Tree Name"], entry["Name"],
        entry["Overall Height"], entry["DBH"], entry["Canopy"],
        entry.get("Latitude", ""), entry.get("Longitude", "")
    ])

def upload_image_to_drive(image_file, filename):
    with open(filename, "wb") as f:
        f.write(image_file.read())

    file_metadata = {
        "name": os.path.basename(filename),
        "parents": [GOOGLE_DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(filename, mimetype="image/jpeg")
    file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()

    # Make public
    drive_service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    os.remove(filename)
    return f"https://drive.google.com/uc?id={file['id']}"

# Session state setup
for key in ["latitude", "longitude", "location_requested", "session_entries", "qr_image"]:
    if key not in st.session_state:
        st.session_state[key] = None if key != "session_entries" else []

st.title("🌳 Tree QR Scanner")

# 1. QR Capture
st.header("1. Capture QR Code Photo")
captured = st.camera_input("📸 Take a photo of the QR code (no scanning required)")
if captured:
    st.session_state.qr_image = captured
    st.success("✅ QR image captured.")

# 2. GPS Capture
st.header("2. Capture GPS Location")
if st.button("Get Location"):
    st.session_state.location_requested = True

if st.session_state.location_requested:
    location = get_geolocation()
    if location:
        coords = location.get("coords", {})
        st.session_state.latitude = coords.get("latitude")
        st.session_state.longitude = coords.get("longitude")
        st.success("📡 Location captured!")
    else:
        st.info("📍 Waiting for browser permission or location data...")

if st.session_state.latitude is not None and st.session_state.longitude is not None:
    st.write(f"📍 Latitude: `{st.session_state.latitude}`")
    st.write(f"📍 Longitude: `{st.session_state.longitude}`")
elif st.session_state.location_requested:
    st.info("📍 Waiting for browser permission or location data...")
else:
    st.info("⚠️ Click 'Get Location' to capture coordinates.")

# 3. Tree Data Form
st.header("3. Fill Tree Details")
with st.form("tree_form"):
    tree_name_suffix = st.text_input("Tree Name (Suffix only)")
    tree_custom_name = f"GGN/25/{tree_name_suffix}"
    st.markdown(f"🔖 **Full Tree Name:** `{tree_custom_name}`")

    tree_name = st.selectbox("Tree Name", [
        "Alstonia angustiloba", "Aquilaria malaccensis", "Azadirachta indica",
        "Baringtonia acutangula", "Buchanania arborescens", "Callophyllum inophyllum",
        "Cerbera odollam rubra", "Cinnamomum iners", "Coccoloba uvifera",
        "Cratoxylum chochinchinensis", "Cratoxylum cochichinensis", "Cratoxylum formosum",
        "Dillenia indica", "Diospyros blancoi", "Diptercarpus baudi", "Diptercarpus gracilis",
        "Dyera costulata", "Eleocarpus grandiflorus", "Ficus lyrata",
        "Filicium decipiens", "Garcinia hombroniana", "Gardenia carinata",
        "Heteropanax fragrans", "Hopea ferrea", "Hopea odorata",
        "Leptospermum brachyandrum", "Licuala grandis", "Maniltoa browneoides",
        "Mesua ferrea", "Michelia champaka", "Millingtonia hortensis",
        "Millettia pinnata", "Mimusops elengi", "Pentaspadon motleyi",
        "Podocarpus macrophyllus", "Podocarpus polystachyus", "Pometia pinnata",
        "Saraca thaipingensis", "Shorea roxburghii", "Spathodea campanulata",
        "Sterculia foetida", "Sterculia parviflora", "Syzygium polyanthum",
        "Syzygium grande", "Syzygium spicata", "Tabebuia argentea",
        "Tabebuia rosea", "Terminalia calamansanai", "Terminalia catappa",
        "Tristania obovata", "Tristaniopsis whiteana", "Unknown sp", "Mixed sp"
    ]))  
    overall_height = st.selectbox("Overall Height (m)", ["1", "2", "3", "4", "5", "6", "7"])
    dbh = st.selectbox("DBH (cm)", ["1", "2", "3", "4", "5", "6", "7", "8", "9"])
    canopy = st.text_input("Canopy Diameter (cm)")

    submitted = st.form_submit_button("Add Entry")

if submitted:
    latest_entries = load_entries_from_gsheet()
    latest_tree_names = [entry["Tree Name"].strip().upper() for entry in latest_entries]

    if tree_custom_name.strip().upper() in latest_tree_names:
        st.error("❌ This Tree Name already exists.")
    elif not all([tree_name, overall_height, dbh, canopy]):
        st.error("❌ Please complete all fields.")
    elif st.session_state.latitude is None or st.session_state.longitude is None:
        st.error("❌ GPS location is missing.")
    else:
        qr_filename = os.path.join(IMAGE_DIR, f"GGN_25_{tree_name_suffix}_QR.jpg")
        if st.session_state.qr_image:
            image_url = upload_image_to_drive(st.session_state.qr_image, qr_filename)
            st.success(f"📸 QR image uploaded successfully.")

        entry = {
            "Tree Name": tree_custom_name,
            "Name": tree_name,
            "Overall Height": overall_height,
            "DBH": dbh,
            "Canopy": canopy,
            "Latitude": st.session_state.latitude,
            "Longitude": st.session_state.longitude
        }
        st.session_state.session_entries.append(entry)
        try:
            save_to_gsheet(entry)
            st.success("✅ Entry added and image saved!")
        except Exception as e:
            st.error(f"❌ Error saving to Google Sheet: {e}")

        # Reset state
        st.session_state.latitude = None
        st.session_state.longitude = None
        st.session_state.location_requested = False
        st.session_state.qr_image = None

# 4. Show Session Data
if st.session_state.session_entries:
    st.header("4. Your Entries This Session")
    df = pd.DataFrame(st.session_state.session_entries)
    st.dataframe(df)

    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", csv_data, "tree_data.csv", "text/csv")

    if st.button("📥 Download Excel with Images"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(EXPORT_DIR, f"tree_data_{timestamp}.xlsx")
        wb = Workbook()
        ws = wb.active
        headers = ["Tree Name", "Name", "Overall Height", "DBH", "Canopy", "Latitude", "Longitude"]
        ws.append(headers)
        for entry in st.session_state.session_entries:
            ws.append([entry.get(k, "") for k in headers])
        wb.save(path)
        with open(path, "rb") as f:
            st.download_button("Download Excel File", f, f"tree_data_{timestamp}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
