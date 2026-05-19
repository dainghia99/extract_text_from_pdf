import os
import re
import io
import fitz  
import pytesseract
from PIL import Image, ImageFilter, ImageEnhance
from flask import Flask, request, jsonify, render_template_string
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp'}

# PSM 6 = uniform block of text, OEM 3 = best available engine
TESS_CONFIG = '--oem 3 --psm 6'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def preprocess_image(img):
    """Improve image quality before OCR for better accuracy."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # Upscale small images — Tesseract works best at ~300 DPI equivalent
    w, h = img.size
    if w < 1500 or h < 1500:
        scale = max(1500 / w, 1500 / h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    # Grayscale → sharpen → boost contrast
    img = img.convert("L")
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img

def clean_text(text):
    """Remove excessive blank lines — keep only single newlines between lines."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse 2+ consecutive blank lines into exactly one newline
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()

def extract_text_from_pdf(file_bytes):
    """Extract text from PDF. Falls back to OCR for image-based pages."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    results = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text().strip()

        if text:
            results.append({
                "page": page_num + 1,
                "method": "text",
                "content": clean_text(text)
            })
        else:
            # No embedded text → render at high DPI and OCR
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img = preprocess_image(img)
            ocr_text = pytesseract.image_to_string(img, lang="vie+eng", config=TESS_CONFIG)
            results.append({
                "page": page_num + 1,
                "method": "ocr",
                "content": clean_text(ocr_text)
            })

    doc.close()
    return results, total_pages

def extract_text_from_image(file_bytes, filename):
    """Extract text from image using Tesseract OCR."""
    img = Image.open(io.BytesIO(file_bytes))
    img = preprocess_image(img)
    text = pytesseract.image_to_string(img, lang="vie+eng", config=TESS_CONFIG)
    return clean_text(text)

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trích Xuất Văn Bản</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --ink: #1a1a1a;
    --paper: #f5f0e8;
    --accent: #c0392b;
    --muted: #7a7060;
    --border: #d4cdc0;
    --card: #fdfaf5;
    --success: #2e7d32;
    --mono: 'IBM Plex Mono', monospace;
    --sans: 'IBM Plex Sans', sans-serif;
    --serif: 'Playfair Display', serif;
  }

  body {
    background: var(--paper);
    color: var(--ink);
    font-family: var(--sans);
    min-height: 100vh;
    background-image:
      repeating-linear-gradient(0deg, transparent, transparent 27px, rgba(0,0,0,.04) 28px);
  }

  header {
    border-bottom: 3px double var(--ink);
    padding: 2rem 3rem 1.5rem;
    background: var(--paper);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(4px);
  }

  header h1 {
    font-family: var(--serif);
    font-size: clamp(1.6rem, 3vw, 2.4rem);
    letter-spacing: -0.02em;
    line-height: 1.1;
  }
  header h1 span { color: var(--accent); }

  header p {
    font-family: var(--mono);
    font-size: .75rem;
    color: var(--muted);
    margin-top: .4rem;
    letter-spacing: .04em;
  }

  main {
    max-width: 900px;
    margin: 0 auto;
    padding: 3rem 2rem 6rem;
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }

  .dropzone {
    border: 2px dashed var(--border);
    border-radius: 4px;
    padding: 3.5rem 2rem;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    background: var(--card);
  }
  .dropzone:hover, .dropzone.dragover {
    border-color: var(--accent);
    background: #fff8f7;
  }
  .dropzone input { display: none; }
  .dropzone-icon { font-size: 3rem; display: block; margin-bottom: 1rem; opacity: .6; }
  .dropzone h2 { font-family: var(--serif); font-size: 1.4rem; margin-bottom: .5rem; }
  .dropzone p { font-size: .85rem; color: var(--muted); font-family: var(--mono); }
  .dropzone .formats {
    display: inline-flex; gap: .4rem; flex-wrap: wrap;
    justify-content: center; margin-top: 1rem;
  }
  .formats span {
    background: var(--ink); color: var(--paper);
    font-family: var(--mono); font-size: .68rem;
    padding: .2rem .5rem; letter-spacing: .06em;
  }

  #fileInfo {
    display: none; align-items: center; gap: 1rem;
    background: var(--card); border: 1px solid var(--border);
    padding: 1rem 1.5rem; border-radius: 4px;
  }
  #fileInfo .file-icon { font-size: 1.8rem; }
  #fileInfo .file-details { flex: 1; }
  #fileInfo .file-name { font-weight: 500; font-size: .95rem; word-break: break-all; }
  #fileInfo .file-size { font-family: var(--mono); font-size: .75rem; color: var(--muted); }

  #extractBtn {
    display: none; width: 100%; padding: 1rem;
    background: var(--ink); color: var(--paper);
    border: none; font-family: var(--mono); font-size: .9rem;
    letter-spacing: .1em; cursor: pointer;
    text-transform: uppercase; transition: background .2s; border-radius: 2px;
  }
  #extractBtn:hover { background: var(--accent); }
  #extractBtn:disabled { background: var(--muted); cursor: not-allowed; }

  #progress {
    display: none; text-align: center; padding: 2rem;
    font-family: var(--mono); font-size: .85rem; color: var(--muted);
  }
  .spinner {
    display: inline-block; width: 24px; height: 24px;
    border: 3px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin .8s linear infinite;
    vertical-align: middle; margin-right: .7rem;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  #results { display: none; }
  .result-header {
    display: flex; align-items: baseline; justify-content: space-between;
    border-bottom: 2px solid var(--ink); padding-bottom: .8rem;
    margin-bottom: 1.5rem; flex-wrap: wrap; gap: .5rem;
  }
  .result-header h3 { font-family: var(--serif); font-size: 1.3rem; }
  .result-meta { font-family: var(--mono); font-size: .72rem; color: var(--muted); }

  .copy-all-btn {
    background: transparent; border: 1.5px solid var(--ink);
    font-family: var(--mono); font-size: .72rem;
    padding: .35rem .8rem; cursor: pointer;
    letter-spacing: .06em; transition: all .15s;
  }
  .copy-all-btn:hover { background: var(--ink); color: var(--paper); }

  .page-block { margin-bottom: 1.8rem; }
  .page-label {
    font-family: var(--mono); font-size: .72rem; color: var(--muted);
    letter-spacing: .08em; text-transform: uppercase;
    margin-bottom: .5rem; display: flex; align-items: center; gap: .6rem;
  }
  .method-badge {
    background: var(--muted); color: var(--paper);
    font-size: .6rem; padding: .1rem .4rem; border-radius: 2px;
  }
  .method-badge.ocr { background: #7b5e2a; }
  .method-badge.text { background: var(--success); }

  .text-output {
    background: var(--card); border: 1px solid var(--border);
    border-left: 4px solid var(--ink);
    padding: 1.2rem 1.4rem; font-family: var(--mono);
    font-size: .82rem; line-height: 1.7;
    white-space: pre-wrap; word-break: break-word;
    max-height: 320px; overflow-y: auto;
    color: var(--ink); border-radius: 0 4px 4px 0;
  }
  .text-output:empty::before {
    content: "(Không tìm thấy văn bản)";
    color: var(--muted); font-style: italic;
  }

  #error {
    display: none; background: #fff0f0;
    border: 1px solid #f5c6c6; border-left: 4px solid var(--accent);
    padding: 1rem 1.4rem; font-family: var(--mono);
    font-size: .82rem; color: var(--accent); border-radius: 0 4px 4px 0;
  }

  .text-output::-webkit-scrollbar { width: 6px; }
  .text-output::-webkit-scrollbar-track { background: var(--border); }
  .text-output::-webkit-scrollbar-thumb { background: var(--muted); }

  #toast {
    position: fixed; bottom: 2rem; right: 2rem;
    background: var(--ink); color: var(--paper);
    font-family: var(--mono); font-size: .78rem;
    padding: .7rem 1.2rem; transform: translateY(4rem);
    opacity: 0; transition: all .25s;
    letter-spacing: .04em; pointer-events: none;
  }
  #toast.show { transform: translateY(0); opacity: 1; }
</style>
</head>
<body>

<header>
  <h1>Trích Xuất <span>Văn Bản</span></h1>
  <p>PDF · JPG · PNG · BMP · TIFF · WEBP — Tiếng Việt &amp; Tiếng Anh</p>
</header>

<main>
  <div class="dropzone" id="dropzone" onclick="document.getElementById('fileInput').click()">
    <input type="file" id="fileInput" accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp">
    <span class="dropzone-icon">📄</span>
    <h2>Kéo thả hoặc chọn file</h2>
    <p>Nhấn vào đây để chọn file từ máy tính</p>
    <div class="formats">
      <span>PDF</span><span>JPG</span><span>PNG</span><span>BMP</span><span>TIFF</span><span>WEBP</span>
    </div>
  </div>

  <div id="fileInfo">
    <span class="file-icon" id="fileIcon">📄</span>
    <div class="file-details">
      <div class="file-name" id="fileName"></div>
      <div class="file-size" id="fileSize"></div>
    </div>
  </div>

  <button id="extractBtn" onclick="extractText()">▶ Trích Xuất Văn Bản</button>

  <div id="progress">
    <span class="spinner"></span>
    <span id="progressMsg">Đang xử lý...</span>
  </div>

  <div id="error"></div>

  <div id="results">
    <div class="result-header">
      <h3 id="resultTitle">Kết Quả</h3>
      <div style="display:flex;gap:.7rem;align-items:center;flex-wrap:wrap;">
        <span class="result-meta" id="resultMeta"></span>
        <button class="copy-all-btn" onclick="copyAll()">Sao chép tất cả</button>
      </div>
    </div>
    <div id="resultContent"></div>
  </div>
</main>

<div id="toast">✓ Đã sao chép!</div>

<script>
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  let selectedFile = null;

  dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
  });

  function handleFile(file) {
    selectedFile = file;
    const ext = file.name.split('.').pop().toLowerCase();
    const icons = { pdf: '📕', jpg: '🖼️', jpeg: '🖼️', png: '🖼️', bmp: '🖼️', tiff: '🖼️', tif: '🖼️', webp: '🖼️' };
    document.getElementById('fileIcon').textContent = icons[ext] || '📄';
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatSize(file.size);
    document.getElementById('fileInfo').style.display = 'flex';
    document.getElementById('extractBtn').style.display = 'block';
    document.getElementById('results').style.display = 'none';
    document.getElementById('error').style.display = 'none';
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  }

  async function extractText() {
    if (!selectedFile) return;
    const btn = document.getElementById('extractBtn');
    btn.disabled = true;
    document.getElementById('progress').style.display = 'block';
    document.getElementById('results').style.display = 'none';
    document.getElementById('error').style.display = 'none';

    const ext = selectedFile.name.split('.').pop().toLowerCase();
    document.getElementById('progressMsg').textContent =
      ext === 'pdf' ? 'Đang trích xuất PDF...' : 'Đang nhận dạng chữ (OCR)...';

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await fetch('/extract', { method: 'POST', body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Lỗi không xác định');
      showResults(data);
    } catch (err) {
      document.getElementById('error').style.display = 'block';
      document.getElementById('error').textContent = '⚠ ' + err.message;
    } finally {
      document.getElementById('progress').style.display = 'none';
      btn.disabled = false;
    }
  }

  function showResults(data) {
    const container = document.getElementById('resultContent');
    container.innerHTML = '';

    if (data.type === 'image') {
      document.getElementById('resultTitle').textContent = 'Văn Bản Trích Xuất';
      document.getElementById('resultMeta').textContent = '1 ảnh · OCR';
      const block = document.createElement('div');
      block.className = 'page-block';
      block.innerHTML = `
        <div class="page-label">
          <span>Kết quả</span>
          <span class="method-badge ocr">OCR</span>
        </div>
        <div class="text-output">${escHtml(data.text)}</div>`;
      container.appendChild(block);
    } else {
      document.getElementById('resultTitle').textContent = 'Văn Bản Trích Xuất';
      const ocrCount = data.pages.filter(p => p.method === 'ocr').length;
      document.getElementById('resultMeta').textContent =
        `${data.total_pages} trang · ${ocrCount > 0 ? ocrCount + ' trang dùng OCR' : 'trích xuất trực tiếp'}`;

      data.pages.forEach(p => {
        const block = document.createElement('div');
        block.className = 'page-block';
        block.innerHTML = `
          <div class="page-label">
            <span>Trang ${p.page}</span>
            <span class="method-badge ${p.method}">${p.method === 'ocr' ? 'OCR' : 'Text'}</span>
          </div>
          <div class="text-output">${escHtml(p.content)}</div>`;
        container.appendChild(block);
      });
    }
    document.getElementById('results').style.display = 'block';
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function copyAll() {
    const outputs = document.querySelectorAll('.text-output');
    const texts = [...outputs].map(el => el.textContent).join('\\n---\\n');
    navigator.clipboard.writeText(texts).then(() => {
      const toast = document.getElementById('toast');
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2000);
    });
  }
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/extract', methods=['POST'])
def extract():
    if 'file' not in request.files:
        return jsonify({'error': 'Không có file được gửi lên.'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Tên file không hợp lệ.'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': f'Định dạng không hỗ trợ. Cho phép: {", ".join(ALLOWED_EXTENSIONS).upper()}'}), 400

    file_bytes = file.read()
    ext = file.filename.rsplit('.', 1)[1].lower()

    try:
        if ext == 'pdf':
            pages, total = extract_text_from_pdf(file_bytes)
            return jsonify({'type': 'pdf', 'total_pages': total, 'pages': pages})
        else:
            text = extract_text_from_image(file_bytes, file.filename)
            return jsonify({'type': 'image', 'text': text})
    except Exception as e:
        return jsonify({'error': f'Lỗi khi xử lý file: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)