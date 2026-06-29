 # PDF Regulator

 **PDF Regulator** is a professional, high-performance tool designed for advanced PDF manipulation and text recognition. It allows users to upload PDF or image files,interactively manage pages (reorder, rotate, delete), and extract them into optimized documents with optional OCR (Optical Character Recognition) capabilities.

 🚀 **Live Demo:**
      [https://emre-goktas-pdf-regulator.hf.space](https://emre-goktas-pdf-regulator.hf.space)


## ✨ Key Features

**📁 Multi-Format Support:** Upload PDF, TIFF, JPEG, or PNG files. Images are automatically converted to PDF.

**🖼️ Interactive Viewer:** High-quality PNG previews for every page with a responsive grid layout.

**🖱️ Advanced Manipulation:**
- **Drag & Drop:** Reorder pages effortlessly using SortableJS.
- **Multi-Select:** Use `Shift` or `Ctrl/Cmd` to select multiple pages at once.
- **Rotation:** Rotate individual pages 90° clockwise or counter-clockwise.
- **Delete/Restore:** Remove unwanted pages or restore them before extraction.

**🔍 Intelligent OCR (Powered by Tesseract & OCRmyPDF):**
- **Smart Detection:** Automatically skips OCR if the document already contains sufficient text, saving system resources.
- **Language Support:** optimized for Turkish (`tur`), English (`eng`), or both.
- **Sidecar OCR:** Runs as a background task, allowing you to continue working while the document is being repaired and recognized.
  
**⚡ Modern Tech Stack:** Built with a "Low JavaScript" philosophy using HTMX for seamless, partial page updates.

**🌑 Sleek Dark UI:** A professional dark-themed interface built with Tailwind CSS.

## ⚡ Optimization & Speed

The core of this project is built for speed and resource efficiency, especially when handling heavy OCR tasks in limited environments like HuggingFace Spaces.

### Two-Phase OCR Strategy

- Fast Scanning (Phase 1): Before triggering the heavy OCR engine, the app uses PyMuPDF to scan for existing text. If a document already has text (e.g., a digital PDF), it skips the OCR process entirely, completing in ~0.01s.
- Selective OCR (Phase 2): If OCR is needed, it uses ocrmypdf with the --skip-text flag, meaning it only processes the specific pages that are images, preserving existing text layers on other pages.

### Performance Tuning (The "Why" behind the code)

In backend/services/pdf_service.py, several features are intentionally disabled or tuned to prioritize extraction speed:
- Disabled --deskew: Straightening tilted scans is highly CPU-intensive. It was removed to ensure a snappy user experience.
- Disabled --clean: While noise removal improves quality, it significantly increases processing time.
- Parallelism & Control: The --jobs 1 constraint was removed to allow the engine to utilize available CPU cores, while a global Semaphore(2) was added to the backend to prevent system crashes from too many simultaneous heavy tasks.
- Optimization Level 0: Set to --optimize 0 for maximum speed during the PDF generation phase, ensuring the fastest possible delivery to the user.

## 🛠️ Tech Stack
### Backend
- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11)
- **PDF Engine:** [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/)
- **OCR Engine:** [OCRmyPDF](https://ocrmypdf.readthedocs.io/), [Tesseract-OCR](https://github.com/tesseract-ocr/tesseract), [Ghostscript](https://www.ghostscript.com/)
- **Database:** SQLite (for tracking background OCR tasks)

### Frontend
- **Styles:** [Tailwind CSS](https://tailwindcss.com/)
- **Interactivity:** [HTMX](https://htmx.org/) &  [SortableJS](https://sortablejs.github.io/Sortable/)
- **Templating:** [Jinja2](https://palletsprojects.com/p/jinja/)


## 🐳 Docker Setup (Recommended)

The easiest way to run PDF Regulator locally is using Docker, as it bundles all system dependencies like Tesseract and Ghostscript.

**Clone the repository:**

`git clone https://github.com/emre-goktas/pdf_regulator.git`

`cd pdf_regulator`

**Build and run the container:**

`docker build -t pdf-regulator .`

`docker run -p 7860:7860 pdf-regulator`


**Access the app:** Open `http://localhost:7860` in your browser.


## 💻 Local Development (Manual Setup)

If you prefer to run it without Docker, ensure you have the system dependencies installed:
  
### 1. Install System Dependencies
**Linux (Ubuntu/Debian):**
`sudo apt-get update && sudo apt-get install -y ocrmypdf tesseract-ocr tesseract-ocr-tur tesseract-ocr-eng ghostscript`

**macOS:**

`brew install ocrmypdf tesseract tesseract-lang`
 
### 2. Set Up Python Environment

`python -m venv .venv`

`source .venv/bin/activate  # On Windows: .venv\Scripts\activate`

`pip install -r requirements.txt`


### 3. Run the Application

`uvicorn backend.main:app --host 0.0.0.0 --port 7860 --reload`


## 📂 Project Structure

pdf_regulator/

  ├── backend/  
  │   ├── main.py                # FastAPI entry point & app configuration  
  │   ├── database.py            # SQLite task management   
  │   ├── routers/               # API endpoints (upload, extract, download, etc.)   
  │   ├── services/              # Core logic (PDF processing, OCR service)   
  │   └── storage/               # Temporary file storage (auto-cleaned)   
  ├── frontend/     
  │   ├── static/                # CSS & JavaScript assets     
  │   └── templates/             # Jinja2 HTML templates & HTMX partials   
  ├── Dockerfile                 # Multi-stage production build  
  └── requirements.txt           # Python dependencies  

## 🛡️ Privacy & Cleanup
To ensure privacy and optimize disk space, the application automatically deletes all uploaded and generated files older than **1 hour** using a background cleanup task.



## 📜 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

---

Copyright (c) 2026 Emre Göktaş
