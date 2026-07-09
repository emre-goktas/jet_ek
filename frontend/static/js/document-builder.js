/**
 * document-builder.js
 *
 * Client-side replacements for what used to be three backend jobs:
 *   1. Converting an uploaded JPEG/PNG image to a PDF before it's sent to
 *      /upload (TIFF still goes to the backend — no browser TIFF decoder).
 *   2. Stamping "EK: n/i" numbers onto every page of the "numbered" ZIP.
 *   3. Building the ZIP (PDFs + a generated Word index list) that used to be
 *      produced by GET /download-zip and /download-zip-numbered.
 *
 * The backend still owns storage and serves raw bytes (/pdf-source/{id},
 * /api/templates/*) — only the CPU-bound generation moved to the browser.
 * Uses pdf-lib, fflate and docx (all loaded as CDN globals in index.html).
 * fflate (pure MIT, zero deps) is used instead of JSZip (dual MIT/GPLv3) —
 * this app handles official/legal documents, so the dependency license
 * surface is kept unambiguous on purpose.
 */

// ─── Magic-byte detection (mirrors backend/services/preprocessor.py) ───────

function detectFileType(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length < 4) return null;
  if (b[0] === 0x25 && b[1] === 0x50 && b[2] === 0x44 && b[3] === 0x46 && b[4] === 0x2d) return 'pdf'; // %PDF-
  if (b[0] === 0xff && b[1] === 0xd8) return 'jpeg';
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return 'png'; // \x89PNG
  if ((b[0] === 0x49 && b[1] === 0x49 && b[2] === 0x2a && b[3] === 0x00) ||
      (b[0] === 0x4d && b[1] === 0x4d && b[2] === 0x00 && b[3] === 0x2a)) return 'tiff'; // II*\0 / MM\0*
  return null;
}

/**
 * Converts a JPEG/PNG File to a single-page PDF File in the browser (page
 * size = image pixel dimensions, matching how fitz.convert_to_pdf() used to
 * size the page on the backend). PDF and TIFF files pass through untouched
 * — TIFF still gets converted server-side (see preprocess_to_pdf).
 * Throws an Error with a user-facing message for unsupported/corrupt files.
 */
async function maybeConvertToPdfBeforeUpload(file) {
  const buf = await file.arrayBuffer();
  const type = detectFileType(buf);

  if (type === 'pdf' || type === 'tiff') {
    return file;
  }
  if (type !== 'jpeg' && type !== 'png') {
    throw new Error('Desteklenmeyen veya bozuk dosya formatı. Lütfen .pdf, .tiff, .jpeg veya .png yükleyin.');
  }

  const pdfDoc = await PDFLib.PDFDocument.create();
  const bytes = new Uint8Array(buf);
  const image = type === 'png' ? await pdfDoc.embedPng(bytes) : await pdfDoc.embedJpg(bytes);
  const page = pdfDoc.addPage([image.width, image.height]);
  page.drawImage(image, { x: 0, y: 0, width: image.width, height: image.height });
  const pdfBytes = await pdfDoc.save();

  const baseName = file.name.replace(/\.[^./\\]+$/, '');
  return new File([pdfBytes], `${baseName}.pdf`, { type: 'application/pdf' });
}

// ─── Turkish number-to-words (mirrors docx_service.number_to_turkish_words) ─

function numberToTurkishWords(n) {
  if (n === 0) return 'sıfır';

  const ones = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz'];
  const tens = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan'];
  const scales = ['', 'bin', 'milyon', 'milyar', 'trilyon'];

  if (n >= Math.pow(10, 3 * scales.length)) {
    throw new Error(`Number too large to convert to Turkish words: ${n}`);
  }

  function readThreeDigits(num) {
    const words = [];
    const h = Math.floor(num / 100);
    const t = Math.floor((num % 100) / 10);
    const o = num % 10;
    if (h > 1) words.push(ones[h]);
    if (h > 0) words.push('yüz');
    if (t > 0) words.push(tens[t]);
    if (o > 0) words.push(ones[o]);
    return words.join('');
  }

  const result = [];
  let scaleIdx = 0;
  while (n > 0) {
    const chunk = n % 1000;
    if (chunk > 0) {
      const chunkWords = readThreeDigits(chunk);
      if (scaleIdx === 1 && chunk === 1) {
        result.push('bin');
      } else {
        result.push(chunkWords + scales[scaleIdx]);
      }
    }
    n = Math.floor(n / 1000);
    scaleIdx++;
  }
  return result.reverse().join('');
}

// ─── File metadata resolution (mirrors download.py's _gather_files_data) ───

/**
 * Reads the left panel's output list in DOM order and resolves each item's
 * ek_no/mahiyet exactly like the old backend _gather_files_data did: a
 * renamed file's custom name is used as-is; otherwise a "NN_name.pdf"-shaped
 * filename donates its own number; anything left gets the next free integer.
 */
function gatherOutputFilesData() {
  const btns = Array.from(document.querySelectorAll('#output-list .download-btn'));

  const raw = btns.map((btn) => {
    const li = btn.closest('li');
    const filename = li?.querySelector('p.truncate')?.textContent?.trim() || `${btn.dataset.fileId}.pdf`;
    const renameBtn = li?.querySelector('.rename-btn');
    const pageCount = renameBtn ? (parseInt(renameBtn.dataset.pageCount, 10) || 1) : 1;
    const customName = btn.dataset.customName || '';
    return { file_id: btn.dataset.fileId, filename, page_count: pageCount, custom_name: customName };
  });

  const filesData = raw.map((f) => {
    let ekNo = null;
    let mahiyet;
    if (f.custom_name) {
      mahiyet = f.custom_name.trim();
    } else {
      const m = f.filename.match(/^(\d+)_(.+)\.pdf$/i);
      if (m) {
        ekNo = parseInt(m[1], 10);
        mahiyet = m[2];
      } else {
        mahiyet = f.filename.replace(/\.pdf$/i, '');
      }
    }
    return { ...f, ek_no: ekNo, mahiyet };
  });

  let assignedNum = 1;
  for (const f of filesData) {
    if (f.ek_no === null) f.ek_no = assignedNum;
    assignedNum = Math.max(assignedNum, f.ek_no + 1);
  }
  filesData.sort((a, b) => a.ek_no - b.ek_no);
  return filesData;
}

// ─── PDF page stamping (mirrors download.py's EK-number loop) ──────────────

/** Stamps "EK: {ekNo}/{pageIndex}" in red bold text near the top-right of
 * every page. Position uses each page's native (unrotated) size, same as
 * the original pymupdf-based implementation. */
async function stampEkNumbers(pdfBytes, ekNo) {
  const pdfDoc = await PDFLib.PDFDocument.load(pdfBytes);
  const font = await pdfDoc.embedFont(PDFLib.StandardFonts.HelveticaBold);
  const pages = pdfDoc.getPages();
  pages.forEach((page, i) => {
    const { width, height } = page.getSize();
    const text = `EK: ${ekNo}/${i + 1}`;
    const fontSize = 12;
    const x = Math.max(10, width - 90);
    const y = height - 30;
    page.drawText(text, { x, y, size: fontSize, font, color: PDFLib.rgb(1, 0, 0) });
  });
  return pdfDoc.save();
}

// ─── DOCX generation ─────────────────────────────────────────────────────

const DOCX_W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';

function wEl(xmlDoc, name) {
  return xmlDoc.createElementNS(DOCX_W_NS, `w:${name}`);
}

function directChildren(node, localName) {
  return Array.from(node.childNodes).filter((n) => n.nodeType === 1 && n.localName === localName);
}

/** Builds one <w:tr> with plain (no borders) cells matching what python-docx's
 * bare Table.add_row() used to produce: tcW from the table's own tblGrid,
 * Times New Roman 12pt runs, and a jc only when the column isn't left-aligned. */
function buildDataRow(xmlDoc, gridColWidths, cells) {
  const tr = wEl(xmlDoc, 'tr');
  cells.forEach((cell, i) => {
    const tc = wEl(xmlDoc, 'tc');
    const tcPr = wEl(xmlDoc, 'tcPr');
    const tcW = wEl(xmlDoc, 'tcW');
    tcW.setAttribute('w:type', 'dxa');
    tcW.setAttribute('w:w', gridColWidths[i] || '0');
    tcPr.appendChild(tcW);
    tc.appendChild(tcPr);

    const p = wEl(xmlDoc, 'p');
    if (cell.align === 'center' || cell.align === 'right') {
      const pPr = wEl(xmlDoc, 'pPr');
      const jc = wEl(xmlDoc, 'jc');
      jc.setAttribute('w:val', cell.align);
      pPr.appendChild(jc);
      p.appendChild(pPr);
    }

    const r = wEl(xmlDoc, 'r');
    const rPr = wEl(xmlDoc, 'rPr');
    const rFonts = wEl(xmlDoc, 'rFonts');
    rFonts.setAttribute('w:ascii', 'Times New Roman');
    rFonts.setAttribute('w:hAnsi', 'Times New Roman');
    rPr.appendChild(rFonts);
    const sz = wEl(xmlDoc, 'sz');
    sz.setAttribute('w:val', '24');
    rPr.appendChild(sz);
    if (cell.bold) rPr.appendChild(wEl(xmlDoc, 'b'));
    r.appendChild(rPr);

    const t = wEl(xmlDoc, 't');
    t.setAttribute('xml:space', 'preserve');
    t.textContent = cell.text != null ? String(cell.text) : '';
    r.appendChild(t);
    p.appendChild(r);
    tc.appendChild(p);
    tr.appendChild(tc);
  });
  return tr;
}

/** Rewrites an existing <w:tc>'s first paragraph's text in place (used for the
 * TOPLAM row's page-count cell), mirroring _set_cell_text: drop existing runs,
 * add one new Times New Roman 12pt run, set alignment if not left. */
function setCellText(xmlDoc, tcNode, text, align, bold) {
  const p = directChildren(tcNode, 'p')[0];
  if (!p) return;

  directChildren(p, 'r').forEach((r) => p.removeChild(r));

  if (align === 'center' || align === 'right') {
    let pPr = directChildren(p, 'pPr')[0];
    if (!pPr) {
      pPr = wEl(xmlDoc, 'pPr');
      p.insertBefore(pPr, p.firstChild);
    }
    let jc = directChildren(pPr, 'jc')[0];
    if (!jc) {
      jc = wEl(xmlDoc, 'jc');
      pPr.appendChild(jc);
    }
    jc.setAttribute('w:val', align);
  }

  const r = wEl(xmlDoc, 'r');
  const rPr = wEl(xmlDoc, 'rPr');
  const rFonts = wEl(xmlDoc, 'rFonts');
  rFonts.setAttribute('w:ascii', 'Times New Roman');
  rFonts.setAttribute('w:hAnsi', 'Times New Roman');
  rPr.appendChild(rFonts);
  const sz = wEl(xmlDoc, 'sz');
  sz.setAttribute('w:val', '24');
  rPr.appendChild(sz);
  if (bold) rPr.appendChild(wEl(xmlDoc, 'b'));
  r.appendChild(rPr);

  const t = wEl(xmlDoc, 't');
  t.setAttribute('xml:space', 'preserve');
  t.textContent = text;
  r.appendChild(t);
  p.appendChild(r);
}

/**
 * "file_path" template mode: loads an existing .docx (e.g. sgk_template.docx),
 * finds its first table, replaces the placeholder data rows with one row per
 * file, fills in the TOPLAM page count, and substitutes the "( ) numaraları
 * altında ... ( ) sayfadan" paragraph placeholders. This is a direct port of
 * docx_service._generate_from_docx_template, operating on the raw OOXML
 * instead of python-docx, since no browser library edits existing .docx
 * tables in place.
 */
async function buildDocxFromExistingTemplate(templateBytes, filesData) {
  const zipEntries = fflate.unzipSync(new Uint8Array(templateBytes));
  const docXmlBytes = zipEntries['word/document.xml'];
  if (!docXmlBytes) throw new Error('Invalid .docx template: word/document.xml missing.');
  const xmlStr = fflate.strFromU8(docXmlBytes);

  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(xmlStr, 'application/xml');
  if (xmlDoc.getElementsByTagName('parsererror').length) {
    throw new Error('Failed to parse template document.xml.');
  }

  const startNum = filesData.length ? filesData[0].ek_no : 1;
  const endNum = filesData.length ? filesData[filesData.length - 1].ek_no : 1;
  const totalPages = filesData.reduce((sum, f) => sum + (f.page_count || 0), 0);

  const tables = xmlDoc.getElementsByTagNameNS(DOCX_W_NS, 'tbl');
  if (tables.length === 0) throw new Error('No templates available.');
  const table = tables[0];
  const rows = directChildren(table, 'tr');
  if (rows.length === 0) throw new Error('Template table has no rows; expected at least a TOPLAM row.');

  const toplamRow = rows[rows.length - 1];
  const toplamCells = directChildren(toplamRow, 'tc');
  if (toplamCells.length > 2) {
    setCellText(xmlDoc, toplamCells[2], String(totalPages), 'center', false);
  }

  // Remove placeholder rows between the header and the TOPLAM row.
  for (let i = 1; i < rows.length - 1; i++) {
    table.removeChild(rows[i]);
  }

  const tblGrid = directChildren(table, 'tblGrid')[0];
  const gridColWidths = tblGrid
    ? directChildren(tblGrid, 'gridCol').map((gc) => gc.getAttribute('w:w'))
    : [];

  for (const f of filesData) {
    const tr = buildDataRow(xmlDoc, gridColWidths, [
      { text: f.ek_no, align: 'center' },
      { text: f.mahiyet, align: 'left' },
      { text: f.page_count, align: 'center' },
      { text: '', align: 'center' },
      { text: 'F', align: 'center' },
    ]);
    table.insertBefore(tr, toplamRow);
  }

  // Paragraph placeholder substitution — only direct body paragraphs (never
  // ones nested in a table), matching python-docx's doc.paragraphs.
  const body = xmlDoc.getElementsByTagNameNS(DOCX_W_NS, 'body')[0];
  for (const p of directChildren(body, 'p')) {
    const tNodes = Array.from(p.getElementsByTagNameNS(DOCX_W_NS, 't'));
    const fullText = tNodes.map((t) => t.textContent).join('');
    if (!fullText.includes('( ) numaraları altında')) continue;
    for (const t of tNodes) {
      t.textContent = t.textContent
        .replace('( ) numaraları', `(${startNum}-${endNum}) numaraları`)
        .replace('( ) sayfadan', `(${totalPages}) sayfadan`);
    }
  }

  const serializer = new XMLSerializer();
  const newXml = serializer.serializeToString(xmlDoc);
  zipEntries['word/document.xml'] = fflate.strToU8(newXml);

  return fflate.zipSync(zipEntries, { level: 6 });
}

/**
 * "legacy" mode: builds a Word document from scratch using the `docx`
 * library, driven by the same declarative JSON shape docx_service._generate_legacy_docx
 * used to read from templates.json (header_text, table.header_rows/data_columns,
 * footer_rows, post_table_text, post_table_signature, logo_base64).
 */
async function buildDocxFromScratch(template, filesData) {
  const {
    Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
    AlignmentType, WidthType, ImageRun, VerticalAlign,
  } = docx;

  const totalPages = filesData.reduce((sum, f) => sum + (f.page_count || 0), 0);
  const children = [];

  // Logo
  if (template.logo_base64) {
    try {
      const logoBytes = base64ToUint8Array(template.logo_base64);
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new ImageRun({ data: logoBytes, transformation: { width: 72, height: 72 }, type: 'png' })],
      }));
    } catch (e) {
      console.warn('Logo embed failed, continuing without logo:', e);
    }
  }

  // Header
  if (template.header_text) {
    const runs = [];
    for (const line of template.header_text.split('\n')) {
      if (line === '---') {
        runs.push(new TextRun({ text: '___________________________________________________________', bold: true, break: 1 }));
      } else {
        runs.push(new TextRun({ text: line, bold: true, font: 'Times New Roman', size: 24, break: runs.length ? 1 : 0 }));
      }
    }
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, children: runs }));
  }
  children.push(new Paragraph({})); // spacer

  // Table
  const tableConfig = template.table || {};
  const headerRows = tableConfig.header_rows || [];
  const dataColumns = tableConfig.data_columns || [];
  const numCols = dataColumns.length;

  const tableRows = [];

  // Header rows with colspan/rowspan
  const grid = headerRows.map(() => new Array(numCols).fill(null));
  headerRows.forEach((rowDef, rIdx) => {
    let cIdx = 0;
    for (const cellDef of rowDef) {
      while (cIdx < numCols && grid[rIdx][cIdx] !== null) cIdx++;
      if (cIdx >= numCols) break;
      const colspan = cellDef.colspan || 1;
      const rowspan = cellDef.rowspan || 1;
      grid[rIdx][cIdx] = { text: cellDef.text || '', colspan, rowspan, master: true };
      for (let ro = 0; ro < rowspan; ro++) {
        for (let co = 0; co < colspan; co++) {
          if (ro === 0 && co === 0) continue;
          grid[rIdx + ro][cIdx + co] = { covered: true, master: false, vMergeContinue: co === 0 };
        }
      }
      cIdx += colspan;
    }
  });

  headerRows.forEach((rowDef, rIdx) => {
    const cells = [];
    for (let cIdx = 0; cIdx < numCols; cIdx++) {
      const g = grid[rIdx][cIdx];
      if (!g) continue;
      if (g.covered) {
        if (g.vMergeContinue) {
          cells.push(new TableCell({ children: [new Paragraph({})], verticalMerge: 'continue' }));
        }
        continue;
      }
      cells.push(new TableCell({
        columnSpan: g.colspan > 1 ? g.colspan : undefined,
        verticalMerge: g.rowspan > 1 ? 'restart' : undefined,
        verticalAlign: VerticalAlign.CENTER,
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: g.text, bold: true, font: 'Times New Roman', size: 24 })],
        })],
      }));
    }
    tableRows.push(new TableRow({ children: cells }));
  });

  // Data rows
  for (const f of filesData) {
    const cells = dataColumns.map((colDef) => {
      let text = '';
      const ctype = colDef.type;
      if (ctype === 'ek_no') text = String(f.ek_no ?? '');
      else if (ctype === 'sayfa_sayisi') text = String(f.page_count ?? '');
      else if (ctype === 'mahiyet') text = f.mahiyet || '';
      else if (ctype === 'constant') text = colDef.value || '';
      const align = ['ek_no', 'sayfa_sayisi', 'constant'].includes(ctype) ? AlignmentType.CENTER : AlignmentType.LEFT;
      return new TableCell({
        children: [new Paragraph({ alignment: align, children: [new TextRun({ text, font: 'Times New Roman', size: 24 })] })],
      });
    });
    tableRows.push(new TableRow({ children: cells }));
  }

  // Footer rows ({toplam_sayfa}/{toplam_sayfa_yazi_ile} placeholders)
  const footerRows = template.footer_rows || [];
  const totalPagesWords = capitalize(numberToTurkishWords(totalPages));
  for (const rowDef of footerRows) {
    const cells = [];
    for (const cellDef of rowDef) {
      const colspan = cellDef.colspan || 1;
      let text = cellDef.text || '';
      text = text.replace('{toplam_sayfa}', String(totalPages)).replace('{toplam_sayfa_yazi_ile}', totalPagesWords);
      const align = cellDef.align === 'center' ? AlignmentType.CENTER
        : cellDef.align === 'right' ? AlignmentType.RIGHT : AlignmentType.LEFT;
      cells.push(new TableCell({
        columnSpan: colspan > 1 ? colspan : undefined,
        children: [new Paragraph({ alignment: align, children: [new TextRun({ text, bold: !!cellDef.bold, font: 'Times New Roman', size: 24 })] })],
      }));
    }
    tableRows.push(new TableRow({ children: cells }));
  }

  children.push(new Table({ rows: tableRows, width: { size: 100, type: WidthType.PERCENTAGE } }));

  // Post-table text
  if (template.post_table_text) {
    children.push(new Paragraph({}));
    const startNum = filesData.length ? filesData[0].ek_no : 1;
    const endNum = filesData.length ? filesData[filesData.length - 1].ek_no : 1;
    const today = new Date();
    const dateStr = `${String(today.getDate()).padStart(2, '0')}.${String(today.getMonth() + 1).padStart(2, '0')}.${today.getFullYear()}`;
    let text = template.post_table_text
      .replace('{gunun_tarihi}', dateStr)
      .replace('{baslangic_no}', String(startNum))
      .replace('{bitis_no}', String(endNum))
      .replace('{toplam_sayfa}', String(totalPages));
    children.push(new Paragraph({
      alignment: template.post_table_align === 'justify' ? AlignmentType.JUSTIFIED : AlignmentType.LEFT,
      children: [new TextRun({ text, bold: !!template.post_table_bold, font: 'Times New Roman', size: 24 })],
    }));
  }

  // Signature block
  if (template.post_table_signature) {
    children.push(new Paragraph({}), new Paragraph({}));
    const sig = template.post_table_signature;
    children.push(new Table({
      rows: [
        new TableRow({
          children: [
            new TableCell({ borders: NO_BORDERS, children: [new Paragraph({})] }),
            new TableCell({ borders: NO_BORDERS, children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: sig.name || '' })] })] }),
          ],
        }),
        new TableRow({
          children: [
            new TableCell({ borders: NO_BORDERS, children: [new Paragraph({})] }),
            new TableCell({ borders: NO_BORDERS, children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: sig.title || '' })] })] }),
          ],
        }),
      ],
      width: { size: 100, type: WidthType.PERCENTAGE },
    }));
  }

  const doc = new Document({ sections: [{ children }] });
  return Packer.toArrayBuffer(doc);
}

let NO_BORDERS;
function initNoBorders() {
  const none = { style: docx.BorderStyle.NONE, size: 0, color: 'FFFFFF' };
  NO_BORDERS = { top: none, bottom: none, left: none, right: none };
}

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function base64ToUint8Array(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** Fetches templates[0]'s full config (and its source .docx bytes, if any)
 * and builds the Word index list. Templates[0] is always used today — see
 * the "template selection" note in the project's memory: institution-based
 * selection is deferred until auth exists. */
async function buildDocxIndex(filesData) {
  if (typeof NO_BORDERS === 'undefined' || !NO_BORDERS) initNoBorders();

  const listRes = await fetch('/api/templates');
  if (!listRes.ok) throw new Error('Failed to load template list.');
  const list = await listRes.json();
  if (!list.length) throw new Error('No templates available.');

  const configRes = await fetch(`/api/templates/${encodeURIComponent(list[0].id)}`);
  if (!configRes.ok) throw new Error('Failed to load template config.');
  const template = await configRes.json();

  if (template.file_path) {
    const fileRes = await fetch(`/api/templates/${encodeURIComponent(template.id)}/file`);
    if (!fileRes.ok) throw new Error('Failed to load template file.');
    const templateBytes = await fileRes.arrayBuffer();
    return buildDocxFromExistingTemplate(templateBytes, filesData);
  }

  return buildDocxFromScratch(template, filesData);
}

// ─── ZIP assembly + download ────────────────────────────────────────────

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/**
 * Tells the backend it can delete these output files now that their content
 * has actually reached the browser (POST /cleanup) — the ZIP/docx are built
 * client-side now, so the backend has no other way to know a download
 * finished. Only ever passed the specific output file_ids just delivered,
 * never a source upload — a later extraction from the same upload should
 * still work. Best-effort: a failed cleanup call just means the hourly/
 * nightly sweeps (see backend/main.py) catch it later instead.
 */
async function cleanupDeliveredFiles(fileIds) {
  if (!fileIds || fileIds.length === 0) return;
  try {
    await fetch('/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_ids: fileIds }),
    });
  } catch (e) {
    console.error('Cleanup request failed (non-fatal, hourly/nightly sweep will catch it):', e);
  }
  fileIds.forEach((id) => {
    if (typeof removeOutputByFileId === 'function') removeOutputByFileId(id);
  });
}

/**
 * Replaces GET /download-zip and /download-zip-numbered: fetches each
 * output's PDF bytes from /pdf-source/{id}, optionally stamps EK numbers,
 * builds the Word index, and packages everything into one ZIP client-side.
 */
async function buildAndDownloadZip(numbered) {
  const filesData = gatherOutputFilesData();
  if (filesData.length === 0) return;

  if (typeof showStatus === 'function') {
    showStatus(numbered ? '⏳ Numaralandırılıp paketleniyor...' : '⏳ Paketleniyor...', 'text-gray-400');
  }

  try {
    const zipEntries = {};

    for (const f of filesData) {
      const res = await fetch(`/pdf-source/${encodeURIComponent(f.file_id)}`);
      if (!res.ok) continue; // matches backend's "skip files that fail to resolve"
      let pdfBytes = new Uint8Array(await res.arrayBuffer());
      if (numbered) {
        try {
          pdfBytes = await stampEkNumbers(pdfBytes, f.ek_no);
        } catch (e) {
          console.error(`Failed to stamp PDF ${f.filename}:`, e);
          // Fall back to the unstamped bytes already in pdfBytes, same as the
          // original backend's per-file stamping fallback.
        }
      }
      const zipFilename = `${String(f.ek_no).padStart(2, '0')}_${f.filename}`;
      zipEntries[zipFilename] = pdfBytes;
    }

    try {
      const docxBytes = await buildDocxIndex(filesData);
      zipEntries['Ek Belgeler Listesi.docx'] = new Uint8Array(docxBytes);
    } catch (e) {
      // Matches the backend: a broken Word index shouldn't block the PDF ZIP.
      console.error('Failed to generate Word index:', e);
    }

    const zipped = fflate.zipSync(zipEntries, { level: 6 });
    const blob = new Blob([zipped], { type: 'application/zip' });
    triggerBlobDownload(blob, 'jetek_files.zip');
    if (typeof showStatus === 'function') showStatus('✓ İndirme hazır.', 'text-green-400');
    await cleanupDeliveredFiles(filesData.map((f) => f.file_id));
  } catch (e) {
    console.error('ZIP packaging failed:', e);
    if (typeof showStatus === 'function') showStatus('✗ Paketleme sırasında hata oluştu.', 'text-red-400');
  }
}
