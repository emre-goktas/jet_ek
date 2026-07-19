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
 * Uses pdf-lib and fflate (both loaded as CDN globals in index.html).
 * fflate (pure MIT, zero deps) is used instead of JSZip (dual MIT/GPLv3) —
 * this app handles official/legal documents, so the dependency license
 * surface is kept unambiguous on purpose. All four institution templates
 * (see templates.json) are real .docx files now, filled in by editing their
 * raw OOXML in place — no from-scratch document builder is needed anymore.
 */

// ─── Usage analytics (Faz 3 — see backend/services/db_service.py) ─────────

/** Fire-and-forget usage event log. Never awaited by callers for its result
 * and never throws — a broken analytics call must not interrupt the actual
 * feature the user is using. No-ops cleanly (backend 401s) when auth isn't
 * configured, same as every other authenticated endpoint. */
function logEvent(eventType, metadata) {
  fetch('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_type: eventType, metadata: metadata || {} }),
  }).catch((e) => console.warn('logEvent failed (non-fatal):', eventType, e));
}

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
function gatherOutputFilesData(fileIdFilter) {
  let btns = Array.from(document.querySelectorAll('#output-list .download-btn'));
  if (fileIdFilter && fileIdFilter.length > 0) {
    const filterSet = new Set(fileIdFilter);
    btns = btns.filter((btn) => filterSet.has(btn.dataset.fileId));
  }

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

/** Maps one file's data through a data_columns column-type definition to a
 * {text, align} cell value — the same "ek_no/mahiyet/sayfa_sayisi/empty/
 * constant" vocabulary templates.json has always used. */
function cellValueFor(colDef, f) {
  const ctype = colDef.type;
  let text = '';
  if (ctype === 'ek_no') text = f.ek_no;
  else if (ctype === 'sayfa_sayisi') text = f.page_count;
  else if (ctype === 'mahiyet') text = f.mahiyet;
  else if (ctype === 'constant') text = colDef.value || '';
  // 'empty' (or anything unrecognized) stays blank.
  const align = (ctype === 'ek_no' || ctype === 'sayfa_sayisi' || ctype === 'constant') ? 'center' : 'left';
  return { text, align };
}

/** Fills templates.json's {token} placeholders in a template string with
 * computed values; unknown tokens are left as-is rather than dropped. */
function fillTemplateString(str, vars) {
  return str.replace(/\{(\w+)\}/g, (match, key) => (key in vars ? String(vars[key]) : match));
}

/**
 * "toplam_row" table_mode: header row(s) + a handful of placeholder rows +
 * a TOPLAM row last. Strips the placeholder rows, inserts one row per file
 * before TOPLAM, and — if the template names a toplam_cell_column_type —
 * fills in the TOPLAM row's page-count cell positionally (used when that
 * cell starts out empty, e.g. sgk_müfettis; templates where it already
 * carries placeholder text, e.g. saglık_bk_teftis's "000", use
 * text_placeholders for that instead — see below).
 */
function fillToplamRowTable(xmlDoc, table, template, filesData, totalPages) {
  const rows = directChildren(table, 'tr');
  if (rows.length === 0) throw new Error('Template table has no rows; expected at least a TOPLAM row.');

  const toplamRow = rows[rows.length - 1];

  if (template.toplam_cell_column_type) {
    const colIdx = template.data_columns.findIndex((c) => c.type === template.toplam_cell_column_type);
    const toplamCells = directChildren(toplamRow, 'tc');
    if (colIdx !== -1 && toplamCells[colIdx]) {
      setCellText(xmlDoc, toplamCells[colIdx], String(totalPages), 'center', false);
    }
  }

  // Remove placeholder rows between the header row(s) and the TOPLAM row.
  // header_row_count defaults to 1 (a single label row, e.g. sgk_müfettis);
  // saglık_bk_teftis has 2 (a merged "Evrakın" row plus the Ek No/Tarihi/
  // Sayısı/Sayfa Adedi sub-header row) and must keep both.
  const headerRowCount = template.header_row_count || 1;
  for (let i = rows.length - 2; i >= headerRowCount; i--) {
    table.removeChild(rows[i]);
  }

  const tblGrid = directChildren(table, 'tblGrid')[0];
  const gridColWidths = tblGrid
    ? directChildren(tblGrid, 'gridCol').map((gc) => gc.getAttribute('w:w'))
    : [];

  for (const f of filesData) {
    const cells = template.data_columns.map((colDef) => cellValueFor(colDef, f));
    const tr = buildDataRow(xmlDoc, gridColWidths, cells);
    table.insertBefore(tr, toplamRow);
  }
}

/**
 * "prenumbered_rows" table_mode: header row + N pre-printed blank rows (no
 * TOPLAM row at all — sgk_denetmen's 12 numbered rows). Overwrites existing
 * rows in place regardless of whatever placeholder content they start with
 * (row position determines which file lands where, not the printed number),
 * removes unused rows if there are fewer files than pre-built rows, and
 * clones+appends new ones if there are more.
 */
function fillPrenumberedRowsTable(xmlDoc, table, template, filesData) {
  const rows = directChildren(table, 'tr');
  if (rows.length === 0) throw new Error('Template table has no header row.');
  const dataRows = rows.slice(1);

  const tblGrid = directChildren(table, 'tblGrid')[0];
  const gridColWidths = tblGrid
    ? directChildren(tblGrid, 'gridCol').map((gc) => gc.getAttribute('w:w'))
    : [];

  const n = filesData.length;
  for (let i = 0; i < Math.min(n, dataRows.length); i++) {
    const cells = directChildren(dataRows[i], 'tc');
    template.data_columns.forEach((colDef, ci) => {
      if (!cells[ci]) return;
      const { text, align } = cellValueFor(colDef, filesData[i]);
      setCellText(xmlDoc, cells[ci], String(text ?? ''), align, false);
    });
  }
  for (let i = dataRows.length - 1; i >= n; i--) {
    table.removeChild(dataRows[i]);
  }
  for (let i = dataRows.length; i < n; i++) {
    const cells = template.data_columns.map((colDef) => cellValueFor(colDef, filesData[i]));
    table.appendChild(buildDataRow(xmlDoc, gridColWidths, cells));
  }
}

/** Sets (or adds) a paragraph's <w:jc> alignment — the real, text-length-
 * independent kind, as opposed to the leading-space padding trick some of
 * these templates use for "alignment" (see whole_paragraph below). */
function setParagraphAlignment(xmlDoc, p, align) {
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

/**
 * Applies every configured {search, replace} pair anywhere in the document —
 * body paragraphs and table cells alike (e.g. saglık_bk_teftis's TOPLAM-row
 * "000", sgk_denetmen's "() Sosyal Güvenlik İl Müdürlüğü" header). Works
 * per-paragraph rather than per-node: most placeholders live in a single
 * <w:t> and get a plain in-place substring replace (preserves every sibling
 * run/tab/formatting untouched), but a few templates split one placeholder
 * across runs (saglık_bk_teftis's "……………….." signature line is "……………" in
 * one run and ".." in the next) — for exactly those paragraphs, and only
 * those, all of the paragraph's text is merged into its first node before
 * the substring replace, so the match can't fall through the gap between
 * runs. Paragraphs no placeholder touches are never merged, so their
 * original run/formatting structure survives untouched.
 *
 * A placeholder can also set `whole_paragraph: true` (optionally with
 * `center: true`): instead of substituting just the matched substring, the
 * paragraph's *entire* text is replaced with the filled value. Needed where
 * the template "aligns" text by padding it with a fixed run of leading
 * spaces rather than real paragraph alignment (saglık_bk_teftis's signature
 * name/title lines) — substituting only the placeholder portion would leave
 * that padding in place, and since the name and title are different lengths
 * than what the padding was originally sized for, they'd land at different
 * horizontal offsets instead of sharing a center line. Wiping the padding
 * and applying true `<w:jc w:val="center"/>` keeps both lines centered
 * relative to each other regardless of how long the name/title text is.
 */
function applyTextPlaceholders(xmlDoc, placeholders, vars) {
  if (!placeholders || placeholders.length === 0) return;

  const paragraphs = Array.from(xmlDoc.getElementsByTagNameNS(DOCX_W_NS, 'p'));
  for (const p of paragraphs) {
    const tNodes = Array.from(p.getElementsByTagNameNS(DOCX_W_NS, 't'));
    if (tNodes.length === 0) continue;
    const fullText = tNodes.map((t) => t.textContent).join('');

    const matching = placeholders.filter((ph) => fullText.includes(ph.search));
    if (matching.length === 0) continue;

    const wholeParagraphPh = matching.find((ph) => ph.whole_paragraph);
    if (wholeParagraphPh) {
      const replacement = fillTemplateString(wholeParagraphPh.replace, vars);
      // Rebuilt as one fresh, explicitly-formatted run (Times New Roman, not
      // bold) rather than reusing whichever original run survives — the
      // leading-space "padding" run these templates use for pseudo-alignment
      // sometimes carries its own stray formatting (e.g. saglık_bk_teftis's
      // title line padding was bold even though the visible label wasn't).
      directChildren(p, 'r').forEach((r) => p.removeChild(r));
      const r = wEl(xmlDoc, 'r');
      const rPr = wEl(xmlDoc, 'rPr');
      const rFonts = wEl(xmlDoc, 'rFonts');
      rFonts.setAttribute('w:ascii', 'Times New Roman');
      rFonts.setAttribute('w:hAnsi', 'Times New Roman');
      rPr.appendChild(rFonts);
      const sz = wEl(xmlDoc, 'sz');
      sz.setAttribute('w:val', '24');
      rPr.appendChild(sz);
      r.appendChild(rPr);
      const t = wEl(xmlDoc, 't');
      t.setAttribute('xml:space', 'preserve');
      t.textContent = replacement;
      r.appendChild(t);
      p.appendChild(r);
      if (wholeParagraphPh.center) setParagraphAlignment(xmlDoc, p, 'center');
      continue;
    }

    const needsMerge = matching.some((ph) => !tNodes.some((t) => t.textContent.includes(ph.search)));
    if (needsMerge) {
      tNodes[0].textContent = fullText;
      for (let i = 1; i < tNodes.length; i++) tNodes[i].textContent = '';
    }

    for (const ph of matching) {
      const replacement = fillTemplateString(ph.replace, vars);
      for (const t of tNodes) {
        if (t.textContent.includes(ph.search)) {
          t.textContent = t.textContent.split(ph.search).join(replacement);
        }
      }
    }
  }
}

/** Fills a template's separate 2x2 "imza" (signature) table — sgk_müfettis
 * and sgk_denetmen both have one after the main data table, empty by
 * default: row/col [0,1] gets the signer's name, [1,1] gets their title. */
function fillSignatureTable(xmlDoc, tables, config, vars) {
  const tbl = tables[config.table_index];
  if (!tbl) return;
  const rows = directChildren(tbl, 'tr');

  const fillCell = (rowCol, text) => {
    if (!rowCol) return;
    const [r, c] = rowCol;
    const row = rows[r];
    if (!row) return;
    const cell = directChildren(row, 'tc')[c];
    if (!cell) return;
    setCellText(xmlDoc, cell, text, 'center', false);
  };

  fillCell(config.name_cell, vars.isim_soyisim);
  fillCell(config.title_cell, vars.unvan);
}

/**
 * Loads an existing .docx template (all four institutions' templates are
 * real files now — see templates.json), fills in its first table according
 * to table_mode/data_columns, and substitutes every text_placeholders entry
 * anywhere in the document (body paragraphs and table cells alike — e.g.
 * saglık_bk_teftis's TOPLAM-row "000", sgk_denetmen's "Ankara" header and
 * its "...... (...) ek," summary line). Direct port of the old backend's
 * docx_service._generate_from_docx_template, generalized to be config-driven
 * instead of hardcoded to one template's shape, operating on the raw OOXML
 * since no browser library edits an existing .docx's tables in place.
 */
async function buildDocxFromExistingTemplate(templateBytes, filesData, template, extraVars) {
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
  const ekSayisi = filesData.length;

  const tables = xmlDoc.getElementsByTagNameNS(DOCX_W_NS, 'tbl');
  if (tables.length === 0) throw new Error('Template has no table.');
  const table = tables[0];

  if (template.table_mode === 'prenumbered_rows') {
    fillPrenumberedRowsTable(xmlDoc, table, template, filesData);
  } else {
    fillToplamRowTable(xmlDoc, table, template, filesData, totalPages);
  }

  const today = new Date();
  const gununTarihi = `${String(today.getDate()).padStart(2, '0')}.${String(today.getMonth() + 1).padStart(2, '0')}.${today.getFullYear()}`;

  const vars = {
    baslangic_no: startNum,
    bitis_no: endNum,
    toplam_sayfa: totalPages,
    toplam_sayfa_yazi: numberToTurkishWords(totalPages),
    ek_sayisi: ekSayisi,
    ek_sayisi_yazi: numberToTurkishWords(ekSayisi),
    il: (extraVars && extraVars.il) || '',
    gunun_tarihi: gununTarihi,
    isim_soyisim: (extraVars && extraVars.isimSoyisim) || '',
    unvan: (extraVars && extraVars.unvan) || '',
  };

  applyTextPlaceholders(xmlDoc, template.text_placeholders, vars);

  if (template.signature_table) {
    fillSignatureTable(xmlDoc, tables, template.signature_table, vars);
  }

  const serializer = new XMLSerializer();
  const newXml = serializer.serializeToString(xmlDoc);
  zipEntries['word/document.xml'] = fflate.strToU8(newXml);

  return fflate.zipSync(zipEntries, { level: 6 });
}

/** Resolves which template + extra fill-in values (il/name/title) to use for
 * the current user: their saved profile if they have one, else the first
 * available template as a defensive fallback (the backend normally redirects
 * to /onboarding before a profile-less user can reach the app at all, so
 * this fallback should rarely if ever actually fire). */
async function resolveUserTemplateChoice() {
  const meRes = await fetch('/api/me');
  if (meRes.ok) {
    const me = await meRes.json();
    if (me.profile && me.profile.template_id) {
      return {
        templateId: me.profile.template_id,
        il: me.profile.il,
        isimSoyisim: me.profile.name || '',
        unvan: me.profile.title || '',
      };
    }
  }
  const listRes = await fetch('/api/templates');
  if (!listRes.ok) throw new Error('Failed to load template list.');
  const list = await listRes.json();
  if (!list.length) throw new Error('No templates available.');
  return { templateId: list[0].id, il: null, isimSoyisim: '', unvan: '' };
}

// ─── Minimal from-scratch .xlsx builder (templates with "format": "xlsx") ──
// No source file to fill in — templates.json just names the same
// ek_no/mahiyet/sayfa_sayisi column vocabulary the docx "toplam_row" builder
// uses, and this hand-writes the handful of OOXML parts a spreadsheet needs
// (no separate library: fflate, already loaded for the PDF zip, is all a
// package this small requires). Text goes in as inline strings, so there's
// no xl/sharedStrings.xml part to manage.

function escapeXml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** One <c> cell at column letter `col`, row `rowNum`. Numbers are written as
 * real numeric cells (so Excel's SUM etc. treat them as numbers); anything
 * else becomes an inline string. `bold` maps to cellXfs index 1 (see
 * XLSX_STYLES_XML) — index 0 is the unstyled default. */
function xlsxCell(col, rowNum, value, bold) {
  const ref = `${col}${rowNum}`;
  const s = bold ? ' s="1"' : '';
  if (typeof value === 'number') {
    return `<c r="${ref}"${s}><v>${value}</v></c>`;
  }
  if (value === '' || value == null) {
    return `<c r="${ref}"${s}/>`;
  }
  return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
}

function xlsxRow(rowNum, cols, values, bold) {
  return `<row r="${rowNum}">${cols.map((col, i) => xlsxCell(col, rowNum, values[i], bold)).join('')}</row>`;
}

const XLSX_CONTENT_TYPES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`;

const XLSX_RELS_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;

const XLSX_WORKBOOK_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Ek Belgeler Listesi" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>`;

const XLSX_WORKBOOK_RELS_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;

// cellXfs index 0 = default, index 1 = bold (used for the title/header/TOPLAM rows).
const XLSX_STYLES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
</styleSheet>`;

/** Builds the same three-column (Ek No / Evrakın Mahiyeti / Sayfa Adedi) +
 * TOPLAM layout as the "duz_tablo" Word template, as a standalone .xlsx. */
function buildExcelIndex(filesData, template) {
  const cols = template.data_columns;
  const letters = ['A', 'B', 'C'];
  const headers = ['Ek No:', 'Evrakın Mahiyeti', 'Sayfa Adedi'];

  let rowNum = 1;
  let rows = xlsxRow(rowNum, letters, ['EK BELGELER LİSTESİ', '', ''], true);
  rowNum++;
  rows += xlsxRow(rowNum, letters, headers, true);
  rowNum++;

  let totalPages = 0;
  for (const f of filesData) {
    const values = cols.map((colDef) => cellValueFor(colDef, f).text);
    totalPages += Number(f.page_count) || 0;
    rows += xlsxRow(rowNum, letters, values, false);
    rowNum++;
  }

  const toplamIdx = cols.findIndex((c) => c.type === (template.toplam_cell_column_type || 'sayfa_sayisi'));
  const toplamValues = ['', 'TOPLAM', ''];
  if (toplamIdx !== -1) toplamValues[toplamIdx] = totalPages;
  rows += xlsxRow(rowNum, letters, toplamValues, true);

  const sheetXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>
    <col min="1" max="1" width="10" customWidth="1"/>
    <col min="2" max="2" width="55" customWidth="1"/>
    <col min="3" max="3" width="14" customWidth="1"/>
  </cols>
  <sheetData>${rows}</sheetData>
  <mergeCells count="1"><mergeCell ref="A1:C1"/></mergeCells>
</worksheet>`;

  const zipEntries = {
    '[Content_Types].xml': fflate.strToU8(XLSX_CONTENT_TYPES_XML),
    '_rels/.rels': fflate.strToU8(XLSX_RELS_XML),
    'xl/workbook.xml': fflate.strToU8(XLSX_WORKBOOK_XML),
    'xl/_rels/workbook.xml.rels': fflate.strToU8(XLSX_WORKBOOK_RELS_XML),
    'xl/styles.xml': fflate.strToU8(XLSX_STYLES_XML),
    'xl/worksheets/sheet1.xml': fflate.strToU8(sheetXml),
  };
  return fflate.zipSync(zipEntries, { level: 6 });
}

/** Fetches the current user's chosen template's config and builds the index
 * document — a from-scratch .xlsx for "format": "xlsx" templates, otherwise
 * the existing fill-in-the-.docx path. Returns { bytes, extension }. */
async function buildDocxIndex(filesData) {
  const { templateId, il, isimSoyisim, unvan } = await resolveUserTemplateChoice();

  const configRes = await fetch(`/api/templates/${encodeURIComponent(templateId)}`);
  if (!configRes.ok) throw new Error('Failed to load template config.');
  const template = await configRes.json();

  if (template.format === 'xlsx') {
    return { bytes: buildExcelIndex(filesData, template), extension: 'xlsx' };
  }

  const fileRes = await fetch(`/api/templates/${encodeURIComponent(template.id)}/file`);
  if (!fileRes.ok) throw new Error('Failed to load template file.');
  const templateBytes = await fileRes.arrayBuffer();
  const bytes = await buildDocxFromExistingTemplate(templateBytes, filesData, template, { il, isimSoyisim, unvan });
  return { bytes, extension: 'docx' };
}

// ─── ZIP assembly + download ────────────────────────────────────────────

// Shared by the single-file download button (index.html) and the ZIP
// packaging below — both prefix a delivered file's name with its two-digit
// Ek No the same way.
function ekPrefixedFilename(ekNo, filename) {
  return `${String(ekNo).padStart(2, '0')}_${filename}`;
}

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

// A transient network-layer hiccup (dropped QUIC stream through a proxy/tunnel,
// e.g. Cloudflare — seen in practice as net::ERR_QUIC_PROTOCOL_ERROR.QUIC_TOO_MANY_RTOS)
// makes fetch() reject outright rather than resolve with a bad status — retry
// a couple of times with backoff before giving up, same idea as
// viewer-render.js's renderPageCanvas retry, so one bad connection blip doesn't
// fail an entire multi-file ZIP. options is passed straight through to fetch()
// (method/headers/body) so POSTs — not just the plain GETs this started
// out covering — can be retried too; defaults to {} so existing GET callers
// are unaffected.
async function fetchWithRetry(url, options = {}, attempts = 3) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await fetch(url, options);
    } catch (e) {
      if (attempt === attempts - 1) throw e;
      await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
    }
  }
}

/**
 * Cuts every still-pending output row (POST /extract/finalize — see
 * backend/routers/extract.py), then unzips each response so every item's
 * bytes flow into the exact same stamping/zipping pipeline as an
 * already-materialized file. Chunked at MAX_SPLIT_GROUPS (split-mode.js)
 * since /extract/finalize rejects a request bigger than that — this app's
 * normal scale is hundreds of pending rows at once, so a single download
 * click needs to survive going over that in one pass. Returns
 * { entriesByIndex, filenamesByIndex }, both keyed by `pending`'s array
 * index — an index missing from either means that item's source vanished
 * server-side, or its whole chunk failed (same best-effort semantics as
 * batch-split: one bad item/chunk never blocks the rest).
 */
async function finalizePendingItems(pending, onProgress) {
  const entriesByIndex = {};
  const filenamesByIndex = {};

  for (let start = 0; start < pending.length; start += MAX_SPLIT_GROUPS) {
    const chunk = pending.slice(start, start + MAX_SPLIT_GROUPS);
    const payload = {
      items: chunk.map((f) => ({
        pages: pendingOutputs[f.file_id].pages,
        custom_name: pendingOutputs[f.file_id].customName || null,
      })),
    };

    // /extract/finalize does no disk writes (build_finalize_zip is purely
    // computational — see pdf_service.py), so unlike /extract it's safe to
    // blindly retry on a transport failure: no risk of a duplicate file, the
    // retry just recomputes and returns the same bytes.
    let res;
    try {
      res = await fetchWithRetry('/extract/finalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      if (typeof showStatus === 'function') showStatus('✗ Bekleyen belgeler paketlenemedi.', 'text-red-400');
      if (onProgress) onProgress(start + chunk.length);
      continue;
    }
    if (!res.ok) {
      if (typeof showStatus === 'function') showStatus('✗ Bekleyen belgeler paketlenemedi.', 'text-red-400');
      if (onProgress) onProgress(start + chunk.length);
      continue;
    }

    const innerEntries = fflate.unzipSync(new Uint8Array(await res.arrayBuffer()));
    for (const key of Object.keys(innerEntries)) {
      const localIndex = parseInt(key.split('_')[0], 10);
      const globalIndex = start + localIndex;
      entriesByIndex[globalIndex] = innerEntries[key];
      filenamesByIndex[globalIndex] = key.slice(String(localIndex).length + 1); // server-sanitized — authoritative over the row's provisional display name
    }
    if (onProgress) onProgress(start + chunk.length);
  }

  return { entriesByIndex, filenamesByIndex };
}

/**
 * Replaces GET /download-zip and /download-zip-numbered: fetches each
 * already-materialized output's PDF bytes from /pdf-source/{id}, cuts every
 * still-pending row in one /extract/finalize pass, optionally stamps EK
 * numbers, builds the Word index, and packages everything into one ZIP
 * client-side.
 */
async function buildAndDownloadZip(numbered, fileIdFilter) {
  const filesData = gatherOutputFilesData(fileIdFilter);
  if (filesData.length === 0) return;

  const materialized = filesData.filter((f) => !isPendingFileId(f.file_id));
  const pending = filesData.filter((f) => isPendingFileId(f.file_id));
  const totalUnits = materialized.length + pending.length;
  let doneUnits = 0;
  const progressLabel = numbered ? 'Numaralandırılıp paketleniyor...' : 'Paketleniyor...';
  if (typeof showProgressBar === 'function') showProgressBar(0, totalUnits, progressLabel);

  try {
    const zipEntries = {};

    for (const f of materialized) {
      const res = await fetchWithRetry(`/pdf-source/${encodeURIComponent(f.file_id)}`);
      if (res.ok) {
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
        const zipFilename = ekPrefixedFilename(f.ek_no, f.filename);
        zipEntries[zipFilename] = pdfBytes;
      } // else: skip files that fail to resolve, matches backend behavior
      doneUnits++;
      if (typeof showProgressBar === 'function') showProgressBar(doneUnits, totalUnits, progressLabel);
    }

    const finalizedPendingIds = [];
    if (pending.length > 0) {
      const { entriesByIndex, filenamesByIndex } = await finalizePendingItems(pending, (count) => {
        if (typeof showProgressBar === 'function') showProgressBar(doneUnits + count, totalUnits, progressLabel);
      });
      doneUnits += pending.length;
      for (let i = 0; i < pending.length; i++) {
        let pdfBytes = entriesByIndex[i];
        if (!pdfBytes) continue; // that item's source vanished server-side; leave its pending row untouched, don't mark it delivered
        if (numbered) {
          try {
            pdfBytes = await stampEkNumbers(pdfBytes, pending[i].ek_no);
          } catch (e) {
            console.error(`Failed to stamp PDF ${filenamesByIndex[i]}:`, e);
          }
        }
        finalizedPendingIds.push(pending[i].file_id);
        zipEntries[ekPrefixedFilename(pending[i].ek_no, filenamesByIndex[i])] = pdfBytes;
      }
      if (finalizedPendingIds.length < pending.length && typeof showStatus === 'function') {
        showStatus(`⚠ ${pending.length - finalizedPendingIds.length} belge paketlenemedi — kaynak bulunamadı.`, 'text-yellow-400');
      }
    }

    try {
      const { bytes, extension } = await buildDocxIndex(filesData);
      zipEntries[`Ek Belgeler Listesi.${extension}`] = new Uint8Array(bytes);
    } catch (e) {
      // Matches the backend: a broken index document shouldn't block the PDF ZIP.
      console.error('Failed to generate index document:', e);
    }

    const zipped = fflate.zipSync(zipEntries, { level: 6 });
    const blob = new Blob([zipped], { type: 'application/zip' });
    triggerBlobDownload(blob, 'jetek_files.zip');
    if (typeof completeProgressBar === 'function') completeProgressBar('✓ İndirme hazır');
    logEvent('download_zip', { file_count: filesData.length, numbered, total_pages: filesData.reduce((s, f) => s + (f.page_count || 0), 0) });
    await cleanupDeliveredFiles(materialized.map((f) => f.file_id).concat(finalizedPendingIds));
  } catch (e) {
    console.error('ZIP packaging failed:', e);
    if (typeof hideProgressBar === 'function') hideProgressBar();
    if (typeof showStatus === 'function') showStatus('✗ Paketleme sırasında hata oluştu.', 'text-red-400');
  }
}
