import hashlib
import html
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
except Exception:
    DocumentConverter = None
    InputFormat = None
    PdfFormatOption = None
    PdfPipelineOptions = None

try:
    import pikepdf
except Exception:
    pikepdf = None


ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = ROOT / "reflow-cache"
CONFIG_PATH = CACHE_ROOT / "config.json"
PORT = int(os.environ.get("REFLOW_PORT", "27621"))
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
AUTO_TRANSLATE = os.environ.get("AUTO_TRANSLATE", "1") != "0"
AUTO_SUMMARY = os.environ.get("AUTO_SUMMARY", "1") != "0"
TRANSLATE_BATCH_CHARS = int(os.environ.get("TRANSLATE_BATCH_CHARS", "7000"))
TRANSLATE_BATCH_ITEMS = int(os.environ.get("TRANSLATE_BATCH_ITEMS", "10"))
REFLOW_WORKERS = int(os.environ.get("REFLOW_WORKERS", "3"))
DEEPSEEK_WORKERS = int(os.environ.get("DEEPSEEK_WORKERS", "4"))
SUMMARY_CONTEXT_CHARS = int(os.environ.get("SUMMARY_CONTEXT_CHARS", "36000"))
METADATA_CONTEXT_CHARS = int(os.environ.get("METADATA_CONTEXT_CHARS", "16000"))
CHAT_CONTEXT_CHARS = int(os.environ.get("CHAT_CONTEXT_CHARS", "28000"))

JOBS = {}
JOB_LOCK = threading.Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=REFLOW_WORKERS, thread_name_prefix="reflow-job")
DEEPSEEK_EXECUTOR = ThreadPoolExecutor(max_workers=DEEPSEEK_WORKERS, thread_name_prefix="deepseek")
DOCLING_CONVERTER = None
DOCLING_LOCK = threading.Lock()

FIGURE_CAPTION_RE = re.compile(r"^(?:fig(?:ure)?\.?)\s*(\d+)\b", re.I)
TABLE_LABEL_RE = re.compile(r"^TABLE\s+([IVXLCDM0-9]+)\b", re.I)

TRANSLATION_SYSTEM_PROMPT = (
    "你是严谨的学术论文中英对照翻译助手。"
    "请把用户 JSON 数组中每个 text 翻译成自然、准确的中文，返回严格 JSON 对象，键为 id，值为中文译文。"
    "保留公式、变量名、引用编号、英文专有名词和数据集名称；不要添加解释；不要翻译参考文献列表。"
)

SUMMARY_SYSTEM_PROMPT = """你是一名资深的计算机领域学术研究者，擅长拆解论文的逻辑链条、提炼核心创新并进行批判性分析。请根据论文内容自动判断子领域，用自然、连贯、可阅读的学术中文总结论文。不要寒暄，不要输出“好的”“下面是”等开场白，直接从第一个 Markdown 标题开始。全文只允许使用 Markdown 标题和自然段，严禁项目符号、编号列表、表格、条列式回答或“一、二、三”下面继续分点。每个标题下写成一到两段完整自然段，像给研究生讲论文一样把逻辑说顺。

请使用这些标题，但标题下面必须是自然段：
### 一、来源与等级
### 二、研究背景与动机
### 三、核心方法与技术创新
### 四、实验设计与结果分析
### 五、局限性与未来工作

如果 PDF 正文中没有代码开源、发表刊物、CCF、JCR 或 SCI 信息，请在第一段中自然说明“未在 PDF 正文中找到”，不要编造。涉及公式、损失函数或关键数学表达时，必须写成可由 MathJax 编译的 LaTeX：行内公式使用 \\(...\\)，较长公式使用 \\[...\\]。不要把公式写成普通 Unicode 符号串。"""


def load_dotenv():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


load_dotenv()


def now():
    return time.time()


def file_id(path):
    path = Path(path)
    stat = path.stat()
    key = f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def safe_pdf_path(raw_path):
    if not raw_path:
        raise ValueError("Missing PDF path")
    path = Path(raw_path)
    if not path.exists():
        raise ValueError("PDF file does not exist")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported")
    return path.resolve()


def doc_dir(doc_id):
    return CACHE_ROOT / doc_id


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    if not path.exists():
        return default
    last_error = None
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.03)
    raise last_error


def set_status(doc_id, **updates):
    path = doc_dir(doc_id) / "status.json"
    status = read_json(path, {}) or {}
    status.update(updates)
    status["updated"] = now()
    write_json(path, status)
    return status


def get_status(doc_id):
    return read_json(doc_dir(doc_id) / "status.json", {"status": "missing", "updated": now()})


def get_config():
    return read_json(CONFIG_PATH, {}) or {}


def save_config(updates):
    config = get_config()
    for key, value in updates.items():
        if value is None:
            continue
        value = str(value).strip()
        if value:
            config[key] = value
    write_json(CONFIG_PATH, config)
    return config


def get_secret(primary, aliases=()):
    config = get_config()
    for key in (primary, *aliases):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    for key in (primary, *aliases):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def config_status():
    return {
        "deepseekConfigured": bool(get_secret("DEEPSEEK_API_KEY")),
        "easyScholarConfigured": bool(get_secret("EASYSCHOLAR_SECRET_KEY", ("EASYSCHOLAR_SECRETKEY", "EASYSCHOLAR_KEY"))),
        "deepseekModel": get_config().get("DEEPSEEK_MODEL") or os.environ.get("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
    }


def clean_pdf_text(text):
    text = html.unescape(str(text or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("鈥檚", "'s").replace("鈥檙", "'r")
    text = text.replace("鈥檔", "'n").replace("鈥檛", "'t")
    text = text.replace("鈥擳", "—T").replace("鈥擣", "—F")
    text = text.replace("鈥欌€撯€?", "-").replace("鈥搢", "-")
    text = text.replace("锟斤拷", "").replace("�", "")
    text = re.sub(r"[*_]{1,3}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_page_noise(text):
    plain = clean_pdf_text(text)
    if not plain:
        return True
    upper = plain.upper()
    if upper.startswith("JOURNAL OF L") or upper.startswith("IEEE TRANSACTIONS"):
        return True
    if re.fullmatch(r"\d{1,3}", plain):
        return True
    if re.match(r"^-+\s*end of page\.page_?number\s*=", plain, re.I):
        return True
    if "arXiv:" in plain or plain.startswith("https://") or plain.startswith("http://"):
        return True
    if re.search(r"\b(is|are)\s+with\s+the\b", plain, re.I):
        return True
    if re.search(r"\bcorresponding author\b|\bcorrespondence\b", plain, re.I):
        return True
    return False


def normalize_heading(text):
    text = clean_pdf_text(text)
    text = re.sub(r"^[#\s]+", "", text)
    text = re.sub(r"^\(?([IVXLCDM]+|[A-Z]|\d+)[.)]\s+", r"\1. ", text)
    return text.strip()


def is_author_list(text):
    if re.search(r"\b(Abstract|Index Terms)\b", text, re.I):
        return False
    if re.search(r"\bwith the\b|\bSchool of\b|\bUniversity\b|\bInstitute\b", text):
        return True
    comma_count = text.count(",")
    words = text.split()
    if (
        comma_count >= 2
        and len(words) <= 32
        and "." not in text
        and not re.search(r"\[[0-9]+\]|\b(Federated|Learning|cloud|model|data|task)\b", text, re.I)
    ):
        return True
    return False


def table_label(text):
    match = TABLE_LABEL_RE.match(text)
    if not match:
        return None
    return f"TABLE {match.group(1).upper()}"


def figure_number(text):
    match = FIGURE_CAPTION_RE.match(text)
    return match.group(1) if match else None


def asset_src(doc_id, name):
    return f"/cache/{doc_id}/images/{urllib.parse.quote(name)}"


def call_deepseek(messages, max_tokens=1800):
    api_key = get_secret("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    config = get_config()
    payload = {
        "model": config.get("DEEPSEEK_MODEL") or os.environ.get("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def translation_key(kind, text):
    return hashlib.sha256(f"{kind}\n{text}".encode("utf-8")).hexdigest()


def translatable_items(blocks):
    items = []
    for block in blocks:
        if block["type"] in {"paragraph", "heading"}:
            text = block.get("text", "").strip()
            if text:
                items.append({"id": block["id"], "kind": block["type"], "text": text})
        if block["type"] in {"figure", "table"}:
            caption = block.get("caption", "").strip()
            if caption:
                items.append({"id": block["id"] + ":caption", "kind": block["type"] + "_caption", "text": caption})
    return items


def translation_cache_complete(doc_id, blocks):
    cache = read_json(doc_dir(doc_id) / "translations.json", {}) or {}
    for item in translatable_items(blocks):
        key = translation_key(item["kind"], item["text"])
        if key not in cache:
            return False
    return True


def blocks_have_translations(blocks):
    for block in blocks:
        if block["type"] in {"paragraph", "heading"} and block.get("text", "").strip():
            if not block.get("translation", "").strip():
                return False
        if block["type"] in {"figure", "table"} and block.get("caption", "").strip():
            if not block.get("caption_translation", "").strip():
                return False
    return True


def make_translation_batches(items):
    batches = []
    current = []
    chars = 0
    for item in items:
        item_len = len(item["text"])
        if current and (len(current) >= TRANSLATE_BATCH_ITEMS or chars + item_len > TRANSLATE_BATCH_CHARS):
            batches.append(current)
            current = []
            chars = 0
        current.append(item)
        chars += item_len
    if current:
        batches.append(current)
    return batches


def parse_translation_json(text):
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Translation response is not a JSON object")
    return {str(k): str(v).strip() for k, v in data.items()}


def translate_batch(batch):
    payload = [{"id": item["id"], "text": item["text"]} for item in batch]
    result = call_deepseek([
        {
            "role": "system",
            "content": TRANSLATION_SYSTEM_PROMPT,
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], max_tokens=5200)
    try:
        return parse_translation_json(result)
    except Exception:
        translated = {}
        for item in batch:
            translated[item["id"]] = call_deepseek([
                {
                    "role": "system",
                    "content": "把下面这段英文学术论文翻译成中文，保留公式、引用编号和关键英文术语，只输出译文。",
                },
                {"role": "user", "content": item["text"]},
            ], max_tokens=1800).strip()
        return translated


def translate_blocks(doc_id, blocks, force=False):
    target_dir = doc_dir(doc_id)
    cache_path = target_dir / "translations.json"
    cache = read_json(cache_path, {}) or {}
    items = []
    for item in translatable_items(blocks):
        key = translation_key(item["kind"], item["text"])
        item["key"] = key
        if force or key not in cache:
            items.append(item)

    batches = make_translation_batches(items)
    if batches:
        set_status(
            doc_id,
            status="translating",
            stage=f"parallel batches 0/{len(batches)}",
            progress=55,
        )
    futures = {
        DEEPSEEK_EXECUTOR.submit(translate_batch, batch): (batch_index, batch)
        for batch_index, batch in enumerate(batches, start=1)
    }
    completed = 0
    for future in as_completed(futures):
        _batch_index, batch = futures[future]
        translated = future.result()
        for item in batch:
            if item["id"] in translated and translated[item["id"]]:
                cache[item["key"]] = translated[item["id"]]
        completed += 1
        progress = 55 + int(completed / max(len(batches), 1) * 35)
        set_status(
            doc_id,
            status="translating",
            stage=f"parallel batches {completed}/{len(batches)}",
            progress=progress,
        )
        write_json(cache_path, cache)

    for block in blocks:
        if block["type"] in {"paragraph", "heading"} and block.get("text"):
            block["translation"] = cache.get(translation_key(block["type"], block["text"]), "")
        if block["type"] in {"figure", "table"} and block.get("caption"):
            key = translation_key(block["type"] + "_caption", block["caption"])
            block["caption_translation"] = cache.get(key, "")
    return blocks


def formula_to_tex(text):
    text = clean_pdf_text(text)
    replacements = {
        "∑": r"\sum",
        "∏": r"\prod",
        "√": r"\sqrt",
        "∪": r"\cup",
        "∈": r"\in",
        "∉": r"\notin",
        "→": r"\to",
        "←": r"\leftarrow",
        "≤": r"\le",
        "≥": r"\ge",
        "≈": r"\approx",
        "≃": r"\simeq",
        "≠": r"\ne",
        "∼": r"\sim",
        "∥": r"\Vert",
        "·": r"\cdot",
        "×": r"\times",
        "⋄": r"\diamond",
        "α": r"\alpha",
        "β": r"\beta",
        "γ": r"\gamma",
        "δ": r"\delta",
        "ε": r"\epsilon",
        "ϵ": r"\epsilon",
        "θ": r"\theta",
        "λ": r"\lambda",
        "µ": r"\mu",
        "μ": r"\mu",
        "σ": r"\sigma",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(
        r"(\\(?:sim|sqrt|sum|prod|cup|in|notin|to|leftarrow|le|ge|approx|simeq|ne|cdot|times|diamond|alpha|beta|gamma|delta|epsilon|theta|lambda|mu|sigma))(?=[A-Za-z])",
        r"\1 ",
        text,
    )
    return text


def block_html(block):
    typ = block["type"]
    if typ == "heading":
        level = max(1, min(3, int(block.get("level", 2))))
        text = html.escape(block.get("text", ""))
        zh = html.escape(block.get("translation", ""))
        zh_html = f'<div class="zh heading-zh">{zh}</div>' if zh else ""
        return f'<section class="block heading-block"><h{level}>{text}</h{level}>{zh_html}</section>'
    if typ == "paragraph":
        text = html.escape(block.get("text", ""))
        zh = html.escape(block.get("translation", ""))
        zh_html = f'<p class="zh">{zh}</p>' if zh else '<p class="zh pending">翻译缓存生成中...</p>'
        return f'<section class="block para"><p class="en">{text}</p>{zh_html}</section>'
    if typ == "formula":
        raw = html.escape(block.get("text", ""))
        tex = html.escape(block.get("latex", "") or formula_to_tex(block.get("text", "")))
        return (
            '<section class="block formula-block">'
            f'<div class="formula-tex">\\[{tex}\\]</div>'
            f'<div class="formula-raw">{raw}</div>'
            '</section>'
        )
    if typ in {"figure", "table"}:
        src = html.escape(block.get("src", ""))
        caption = html.escape(block.get("caption", ""))
        caption_zh = html.escape(block.get("caption_translation", ""))
        label = "图" if typ == "figure" else "表"
        index = html.escape(str(block.get("index") or block.get("number") or ""))
        caption_html = ""
        if caption:
            caption_html = f'<figcaption><span class="cap-en">{caption}</span>'
            if caption_zh:
                caption_html += f'<span class="cap-zh">{caption_zh}</span>'
            caption_html += "</figcaption>"
        return (
            f'<figure class="{typ}-block media-block" data-kind="{typ}" data-index="{index}">'
            f'<img src="{src}" alt="{label}{index}">'
            f'{caption_html}'
            f'<button class="explain" onclick="explainAsset(\'{typ}\', \'{index}\')">AI 解释</button>'
            f'</figure>'
        )
    return ""


def render_article(blocks):
    return "\n".join(block_html(block) for block in blocks)


def get_docling_converter():
    if DocumentConverter is None:
        raise RuntimeError("Docling is not installed")
    global DOCLING_CONVERTER
    with DOCLING_LOCK:
        if DOCLING_CONVERTER is None:
            options = PdfPipelineOptions()
            options.do_table_structure = True
            options.do_ocr = False
            options.generate_picture_images = True
            options.generate_table_images = True
            options.images_scale = 2.0
            DOCLING_CONVERTER = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
        return DOCLING_CONVERTER


def repair_pdf_for_docling(path, target_dir):
    if pikepdf is None:
        raise RuntimeError("pikepdf is not installed; cannot normalize malformed PDF")
    repaired = target_dir / "docling-input.pdf"
    with pikepdf.open(str(path)) as pdf:
        pdf.save(str(repaired), linearize=True)
    return repaired


def convert_with_docling(path, doc_id, target_dir):
    converter = get_docling_converter()
    try:
        return converter.convert(Path(path))
    except Exception as exc:
        set_status(doc_id, status="extracting", stage="repairing PDF", progress=12, error="")
        repaired = repair_pdf_for_docling(path, target_dir)
        try:
            return converter.convert(repaired)
        except Exception:
            raise exc


def docling_ref_text(doc, ref):
    cref = getattr(ref, "cref", "") or ""
    match = re.fullmatch(r"#/texts/(\d+)", cref)
    if not match:
        return ""
    index = int(match.group(1))
    if index < 0 or index >= len(doc.texts):
        return ""
    return clean_pdf_text(getattr(doc.texts[index], "text", ""))


def docling_caption(doc, item, items=None, start_index=0):
    captions = []
    for ref in getattr(item, "captions", []) or []:
        text = docling_ref_text(doc, ref)
        if text:
            captions.append(text)
    if captions or not items:
        return " ".join(captions).strip(), set()

    consumed = set()
    kind = type(item).__name__.lower()
    for offset in range(1, 7):
        if start_index + offset >= len(items):
            break
        candidate, _level = items[start_index + offset]
        label = str(getattr(candidate, "label", "") or "")
        text = clean_pdf_text(getattr(candidate, "text", ""))
        if label == "caption":
            if ("table" in kind and TABLE_LABEL_RE.match(text)) or ("picture" in kind and FIGURE_CAPTION_RE.match(text)):
                captions.append(text)
                consumed.add(getattr(candidate, "self_ref", ""))
                break
        if len(text) <= 4 or label in {"formula", "text"} and re.fullmatch(r"[0-9A-Za-z+\-. ]{1,6}", text):
            consumed.add(getattr(candidate, "self_ref", ""))
            continue
        if label not in {"caption", "formula"}:
            break
    return " ".join(captions).strip(), consumed


def save_docling_image(item, image_dir, name):
    image = getattr(item, "image", None)
    uri = str(getattr(image, "uri", "") or "")
    if not uri:
        return None
    out = image_dir / name
    out.parent.mkdir(parents=True, exist_ok=True)
    if uri.startswith("data:"):
        payload = uri.split(",", 1)[1]
        out.write_bytes(base64.b64decode(payload))
        return out
    source = Path(urllib.parse.unquote(uri))
    if source.exists():
        out.write_bytes(source.read_bytes())
        return out
    return None


def docling_page(item):
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None
    return getattr(prov[0], "page_no", None)


def is_docling_author_or_note(text):
    if is_author_list(text):
        return True
    if re.match(r"^\d+\s*https?://", text):
        return True
    return False


def extract_docling_reflow(path, doc_id, target_dir, image_dir):
    result = convert_with_docling(path, doc_id, target_dir)
    doc = result.document
    items = list(doc.iterate_items(traverse_pictures=False))

    blocks = []
    figures = []
    tables = []
    consumed_refs = set()
    seen_abstract = False
    title_seen = False
    stop = False

    def add_block(block):
        block["id"] = f"b{len(blocks) + 1}"
        blocks.append(block)
        return block

    for index, (item, _level) in enumerate(items):
        if stop:
            break
        self_ref = getattr(item, "self_ref", "")
        if self_ref in consumed_refs:
            continue
        label = str(getattr(item, "label", "") or "")
        layer = str(getattr(item, "content_layer", "") or "")
        text = clean_pdf_text(getattr(item, "text", ""))

        if "FURNITURE" in layer or label in {"page_header", "page_footer", "footnote", "caption"}:
            continue
        if label == "section_header" and re.fullmatch(r"REFERENCES", text, re.I):
            stop = True
            break

        item_type = type(item).__name__
        if item_type == "TableItem":
            caption, extra = docling_caption(doc, item, items, index)
            consumed_refs.update(extra)
            table_index = len(tables) + 1
            name = f"docling_table_{table_index}.png"
            saved = save_docling_image(item, image_dir, name)
            if not saved:
                continue
            block = add_block({
                "type": "table",
                "index": table_index,
                "label": table_label(caption) or f"TABLE {table_index}",
                "page": docling_page(item),
                "image": name,
                "src": asset_src(doc_id, name),
                "caption": caption,
            })
            tables.append({k: block.get(k) for k in ("index", "label", "page", "image", "src", "caption")})
            continue

        if item_type == "PictureItem":
            caption, extra = docling_caption(doc, item, items, index)
            consumed_refs.update(extra)
            number = figure_number(caption)
            picture_index = len(figures) + 1
            name = f"docling_figure_{picture_index}.png"
            saved = save_docling_image(item, image_dir, name)
            if not saved:
                continue
            if not caption and saved.stat().st_size < 24000:
                continue
            block = add_block({
                "type": "figure",
                "kind": "figure",
                "index": picture_index,
                "number": number,
                "page": docling_page(item),
                "image": name,
                "src": asset_src(doc_id, name),
                "caption": caption,
            })
            figures.append({k: block.get(k) for k in ("index", "number", "page", "image", "src", "caption")})
            continue

        if item_type == "FormulaItem":
            raw_formula = clean_pdf_text(getattr(item, "orig", "") or text)
            if raw_formula:
                add_block({
                    "type": "formula",
                    "text": raw_formula,
                    "latex": formula_to_tex(raw_formula),
                    "page": docling_page(item),
                })
            continue

        if is_page_noise(text) or is_docling_author_or_note(text):
            continue
        if not text:
            continue

        if not seen_abstract:
            if label == "section_header" and not title_seen:
                add_block({"type": "heading", "level": 1, "text": normalize_heading(text)})
                title_seen = True
                continue
            if re.search(r"\bAbstract\b", text, re.I):
                seen_abstract = True
                text = re.sub(r"^Abstract\s*[-—:]*\s*", "Abstract: ", text, flags=re.I)
                add_block({"type": "paragraph", "text": text})
            continue

        if label == "section_header":
            level = 2 if re.match(r"^[IVXLCDM]+\.", text) else 3
            add_block({"type": "heading", "level": level, "text": normalize_heading(text)})
        elif label in {"text", "list_item"}:
            text = re.sub(r"^Index Terms\s*[-—:]*\s*", "Index Terms: ", text, flags=re.I)
            if label == "list_item" and not text.startswith("- "):
                text = "- " + text
            add_block({"type": "paragraph", "text": text})

    clean_md = "\n\n".join(
        block.get("text") or block.get("caption") or ""
        for block in blocks
        if block.get("text") or block.get("caption")
    )
    (target_dir / "docling.md").write_text(clean_md, encoding="utf-8")
    return clean_md, blocks, figures, tables


def extract_reflow(path, force=False):
    doc_id = file_id(path)
    target_dir = doc_dir(doc_id)
    image_dir = target_dir / "images"
    html_path = target_dir / "article.html"
    blocks_path = target_dir / "blocks.json"
    md_path = target_dir / "reflow.md"

    if not force and html_path.exists() and blocks_path.exists() and md_path.exists():
        blocks = read_json(blocks_path, []) or []
        return doc_id, md_path.read_text(encoding="utf-8"), blocks, html_path.read_text(encoding="utf-8")

    target_dir.mkdir(parents=True, exist_ok=True)
    if force and image_dir.exists():
        for stale in image_dir.iterdir():
            if stale.is_file() and stale.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                try:
                    stale.unlink()
                except OSError:
                    pass
    image_dir.mkdir(parents=True, exist_ok=True)
    set_status(doc_id, status="extracting", stage="docling layout", progress=8)

    md, blocks, figures, tables = extract_docling_reflow(path, doc_id, target_dir, image_dir)
    md_path.write_text(md, encoding="utf-8")

    write_json(target_dir / "figures.json", figures)
    write_json(target_dir / "tables.json", tables)
    write_json(blocks_path, blocks)

    article = render_article(blocks)
    html_path.write_text(article, encoding="utf-8")
    return doc_id, md, blocks, article


def ingest_pdf(path, title=None, item_id=None, venue=None, translate=AUTO_TRANSLATE, force=False):
    path = safe_pdf_path(path)
    doc_id = file_id(path)
    target_dir = doc_dir(doc_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    write_json(target_dir / "source.json", {
        "path": str(path),
        "title": title or path.name,
        "venue": venue or "",
        "itemID": item_id,
        "mtime": path.stat().st_mtime,
        "size": path.stat().st_size,
        "updated": now(),
    })

    with JOB_LOCK:
        job = JOBS.get(doc_id)
        if job and not job.done():
            return doc_id, get_status(doc_id)

        def run():
            try:
                set_status(doc_id, status="queued", stage="queued", progress=0, error="")
                _doc_id, md, blocks, _article = extract_reflow(path, force=force)
                if translate:
                    blocks = translate_blocks(doc_id, blocks, force=force)
                    write_json(doc_dir(doc_id) / "blocks.json", blocks)
                    (doc_dir(doc_id) / "article.html").write_text(render_article(blocks), encoding="utf-8")
                set_status(doc_id, status="classifying", stage="DeepSeek metadata", progress=94)
                ensure_metadata(doc_id, force=force)
                if translate and AUTO_SUMMARY:
                    ensure_summary(doc_id, force=force)
                set_status(doc_id, status="ready", stage="done", progress=100, error="")
            except Exception as exc:
                set_status(doc_id, status="error", stage="error", progress=0, error=str(exc))
                sys.stderr.write(f"[reflow] ingest failed for {path}: {exc}\n")

        set_status(doc_id, status="queued", stage="queued", progress=0, error="")
        JOBS[doc_id] = JOB_EXECUTOR.submit(run)
    return doc_id, get_status(doc_id)


def get_cached_markdown(doc_id):
    md_path = doc_dir(doc_id) / "reflow.md"
    if not md_path.exists():
        raise ValueError("Document is not in cache yet")
    return md_path.read_text(encoding="utf-8")


def get_article(doc_id):
    path = doc_dir(doc_id) / "article.html"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_blocks(doc_id):
    return read_json(doc_dir(doc_id) / "blocks.json", []) or []


def get_assets(doc_id):
    target_dir = doc_dir(doc_id)
    return {
        "figures": read_json(target_dir / "figures.json", []) or [],
        "tables": read_json(target_dir / "tables.json", []) or [],
    }


def get_summary(doc_id):
    path = doc_dir(doc_id) / "summary.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def summary_sidecar_path(doc_id):
    source = read_json(doc_dir(doc_id) / "source.json", {}) or {}
    source_path = source.get("path")
    if not source_path:
        return None
    pdf_path = Path(source_path)
    return pdf_path.with_name(f"{pdf_path.stem}.AI-Reflow-论文总结.md")


def write_summary_files(doc_id, text):
    target_dir = doc_dir(doc_id)
    summary_path = target_dir / "summary.md"
    summary_path.write_text(text, encoding="utf-8")
    saved_path = None
    sidecar = summary_sidecar_path(doc_id)
    if sidecar:
        try:
            sidecar.write_text(text, encoding="utf-8")
            saved_path = str(sidecar)
        except OSError as exc:
            sys.stderr.write(f"[reflow] could not write summary sidecar: {exc}\n")
    write_json(target_dir / "summary.json", {
        "path": str(summary_path),
        "sidecar": saved_path,
        "updated": now(),
    })
    return saved_path


def build_summary_context(blocks):
    chunks = []
    for block in blocks:
        typ = block.get("type")
        if typ in {"heading", "paragraph"}:
            text = block.get("text", "").strip()
            zh = block.get("translation", "").strip()
            if text:
                chunks.append(f"[{typ}] EN: {text}")
            if zh:
                chunks.append(f"[{typ}] ZH: {zh}")
        elif typ in {"figure", "table"}:
            caption = block.get("caption", "").strip()
            caption_zh = block.get("caption_translation", "").strip()
            if caption:
                chunks.append(f"[{typ} caption] EN: {caption}")
            if caption_zh:
                chunks.append(f"[{typ} caption] ZH: {caption_zh}")
        elif typ == "formula":
            formula = block.get("latex") or block.get("text")
            if formula:
                chunks.append(f"[formula] {formula}")
    context = "\n".join(chunks)
    return context[:SUMMARY_CONTEXT_CHARS]


def clean_summary_text(text):
    text = str(text or "").strip()
    match = re.search(r"###\s*一[、,，]", text)
    if match and match.start() > 0:
        text = text[match.start():].strip()
    elif text.find("###") > 0:
        text = text[text.find("###"):].strip()
    return text


def ensure_summary(doc_id, force=False):
    if not force:
        cached = get_summary(doc_id)
        if cached:
            return cached

    blocks = get_blocks(doc_id)
    if not blocks:
        raise ValueError("Document blocks are not ready")
    if translation_cache_complete(doc_id, blocks) and not blocks_have_translations(blocks):
        blocks = translate_blocks(doc_id, blocks)
        write_json(doc_dir(doc_id) / "blocks.json", blocks)
        (doc_dir(doc_id) / "article.html").write_text(render_article(blocks), encoding="utf-8")

    set_status(doc_id, status="summarizing", stage="DeepSeek summary", progress=96)
    context = build_summary_context(blocks)
    text = call_deepseek([
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "下面是论文解析后的正文、图表标题、公式和已缓存译文。"
                "请基于这些内容完成结构化精读总结：\n\n" + context
            ),
        },
    ], max_tokens=6200).strip()
    text = clean_summary_text(text)
    write_summary_files(doc_id, text)
    return text


def compact_text(text):
    return re.sub(r"\s+", " ", clean_pdf_text(text)).strip(" .,:;|-")


def clean_source_title(source):
    title = compact_text(source.get("title") or "")
    if not title and source.get("path"):
        title = Path(source["path"]).stem
    title = re.sub(r"\.pdf$", "", title, flags=re.I)
    title = title.replace("_", " ")
    return compact_text(title)


def bad_title_candidate(text):
    text = compact_text(text)
    low = text.lower()
    if len(text) < 8 or len(text) > 260:
        return True
    if re.fullmatch(r"\d{4}\.\d{4,}(v\d+)?", text, re.I):
        return True
    if re.match(r"^(abstract|keywords|ccs concepts|references|appendix|index terms)\b", low):
        return True
    if re.search(r"\b(university|institute|department|school|laboratory|lab)\b", text, re.I):
        return True
    if text.count(",") >= 2 and len(text.split()) < 26:
        return True
    return False


def extract_paper_title(blocks, fallback=""):
    candidates = []
    before_abstract = []
    for block in blocks[:30]:
        text = compact_text(block.get("text") or "")
        if not text:
            continue
        if re.match(r"^abstract\b", text, re.I):
            break
        if block.get("type") == "heading":
            candidates.append(text)
        elif not before_abstract and block.get("type") == "paragraph":
            candidates.append(text)
        before_abstract.append(text)

    for candidate in candidates:
        if not bad_title_candidate(candidate):
            return candidate

    if len(before_abstract) >= 2:
        joined = compact_text(" ".join(before_abstract[:2]))
        if not bad_title_candidate(joined):
            return joined

    fallback = compact_text(fallback)
    return "" if bad_title_candidate(fallback) else fallback


def parse_json_object(text):
    raw = str(text or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("DeepSeek response is not a JSON object")
    return data


def normalize_ccf(value):
    text = compact_text(value).upper()
    if not text or text in {"UNKNOWN", "N/A", "NA", "NONE", "未知", "不详"}:
        return "未知"
    match = re.search(r"\b([ABC])\b|CCF[-\s]*([ABC])", text)
    return (match.group(1) or match.group(2)) if match else "未知"


def normalize_quartile(value):
    text = compact_text(value).upper()
    if not text or text in {"UNKNOWN", "N/A", "NA", "NONE", "未知", "不详"}:
        return "未知"
    if "一区" in text:
        return "Q1"
    if "二区" in text:
        return "Q2"
    if "三区" in text:
        return "Q3"
    if "四区" in text:
        return "Q4"
    match = re.search(r"\bQ([1-4])\b", text)
    return f"Q{match.group(1)}" if match else "未知"


def metadata_rank_score(meta):
    ccf = normalize_ccf(meta.get("ccf"))
    sci = normalize_quartile(meta.get("sci"))
    jcr = normalize_quartile(meta.get("jcr"))
    if ccf == "A" or sci == "Q1" or jcr == "Q1":
        return 4
    if ccf == "B" or sci == "Q2" or jcr == "Q2":
        return 3
    if ccf == "C" or sci == "Q3" or jcr == "Q3":
        return 2
    if sci == "Q4" or jcr == "Q4":
        return 1
    return 0


def normalize_publication_name(name):
    name = compact_text(name)
    if re.search(r"Proceedings of the National Academy of Sciences", name, re.I):
        return "Proceedings of the National Academy of Sciences of the United States of America"
    return name


def query_easyscholar(publication_name):
    secret_key = get_secret("EASYSCHOLAR_SECRET_KEY", ("EASYSCHOLAR_SECRETKEY", "EASYSCHOLAR_KEY"))
    publication_name = normalize_publication_name(publication_name)
    if not secret_key or not publication_name or publication_name == "未知":
        return None
    query = urllib.parse.urlencode({
        "secretKey": secret_key,
        "publicationName": publication_name,
    })
    url = f"https://easyscholar.cc/open/getPublicationRank?{query}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data") or {}
    official = (((data.get("officialRank") or {}).get("all")) or {})
    if not isinstance(official, dict) or not official:
        return None
    return official


def metadata_from_easyscholar(publication_name):
    ranks = query_easyscholar(publication_name)
    if not ranks:
        return None
    ccf = normalize_ccf(ranks.get("ccf") or ranks.get("ccf_c"))
    jcr = normalize_quartile(ranks.get("sci") or ranks.get("ssci"))
    sci = normalize_quartile(ranks.get("sci") or ranks.get("ssci") or ranks.get("sciUp") or ranks.get("sciBase"))
    meta = {
        "venue": normalize_publication_name(publication_name),
        "ccf": ccf,
        "sci": sci,
        "jcr": jcr,
        "rankSource": "easyScholar",
        "rankRaw": ranks,
    }
    meta["rankScore"] = metadata_rank_score(meta)
    pieces = []
    for key in ("ccf", "sci", "ssci", "sciUp", "sciBase", "sciif", "sciif5", "eii"):
        if ranks.get(key):
            pieces.append(f"{key}={ranks[key]}")
    meta["evidence"] = "easyScholar: " + ("; ".join(pieces[:8]) if pieces else "已返回官方数据")
    return meta


def ensure_metadata(doc_id, force=False):
    target_dir = doc_dir(doc_id)
    cache_path = target_dir / "metadata.json"
    if not force:
        cached = read_json(cache_path, None)
        if cached:
            return cached

    blocks = get_blocks(doc_id)
    if not blocks:
        raise ValueError("Document blocks are not ready")
    source = read_json(target_dir / "source.json", {}) or {}
    fallback_title = clean_source_title(source)
    source_venue = compact_text(source.get("venue") or "")
    local_title = extract_paper_title(blocks, fallback_title) or fallback_title
    context = build_summary_context(blocks)[:METADATA_CONTEXT_CHARS]
    parsed = {}
    error = ""
    try:
        result = call_deepseek([
            {
                "role": "system",
                "content": (
                    "你是计算机领域论文元数据识别助手。请只基于用户提供的论文标题和正文片段判断论文题名、录用刊物或会议、CCF 等级、SCI 分区、JCR 分区。"
                    "如果正文没有可靠证据，字段填“未知”。只输出严格 JSON，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "titleCandidate": local_title,
                    "sourceTitle": fallback_title,
                    "paperContext": context,
                    "schema": {
                        "title": "论文正式英文标题",
                        "venue": "会议或期刊名称，未知则填未知",
                        "ccf": "A/B/C/未知",
                        "sci": "Q1/Q2/Q3/Q4/未知",
                        "jcr": "Q1/Q2/Q3/Q4/未知",
                        "evidence": "一句话说明判断依据",
                    },
                }, ensure_ascii=False),
            },
        ], max_tokens=1400)
        parsed = parse_json_object(result)
    except Exception as exc:
        error = str(exc)

    meta = {
        "title": compact_text(parsed.get("title") or local_title or fallback_title),
        "venue": compact_text(source_venue or parsed.get("venue") or "未知") or "未知",
        "ccf": normalize_ccf(parsed.get("ccf")),
        "sci": normalize_quartile(parsed.get("sci")),
        "jcr": normalize_quartile(parsed.get("jcr")),
        "evidence": compact_text(parsed.get("evidence") or ""),
        "rankSource": "DeepSeek",
        "updated": now(),
    }
    publication_candidates = [
        source_venue,
        meta.get("venue"),
    ]
    for publication_name in publication_candidates:
        try:
            easy_meta = metadata_from_easyscholar(publication_name)
        except Exception as exc:
            meta["rankError"] = str(exc)
            easy_meta = None
        if easy_meta:
            meta.update(easy_meta)
            break
    if not meta["title"]:
        meta["title"] = fallback_title or "Untitled PDF"
    meta["rankScore"] = metadata_rank_score(meta)
    if error:
        meta["error"] = error
    write_json(cache_path, meta)
    return meta


def answer_paper_question(doc_id, question):
    question = compact_text(question)
    if not question:
        raise ValueError("Question is empty")
    blocks = get_blocks(doc_id)
    if not blocks:
        raise ValueError("Document blocks are not ready")
    context = build_summary_context(blocks)[:CHAT_CONTEXT_CHARS]
    summary = get_summary(doc_id)
    try:
        meta = ensure_metadata(doc_id)
    except Exception:
        meta = {}
    result = call_deepseek([
        {
            "role": "system",
            "content": (
                "你是论文阅读问答助手。请用中文回答用户关于这篇论文的问题，优先依据提供的正文、译文、图表标题、公式和本地摘要。"
                "如果材料中没有答案，直接说明没有在当前论文内容中找到可靠依据。涉及公式时使用可由 MathJax 编译的 LaTeX。"
            ),
        },
        {
            "role": "user",
            "content": (
                "论文元数据：\n"
                + json.dumps(meta, ensure_ascii=False)
                + "\n\n本地摘要：\n"
                + (summary[:6000] if summary else "暂无")
                + "\n\n论文内容：\n"
                + context
                + "\n\n问题：\n"
                + question
            ),
        },
    ], max_tokens=2600)
    return result.strip()


def loading_page(title, doc_id, source_path):
    safe_title = html.escape(title or Path(source_path).name)
    escaped_path = html.escape(str(source_path))
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} - AI Reflow</title>
<style>
body {{ margin: 0; background: #f5f7fa; color: #1d2433; font: 16px/1.7 "Segoe UI", system-ui, sans-serif; }}
.panel {{ max-width: 760px; margin: 12vh auto; background: #fff; border: 1px solid #d9dee7; border-radius: 8px; padding: 28px 32px; }}
.bar {{ height: 8px; background: #edf1f7; border-radius: 999px; overflow: hidden; }}
.fill {{ width: 4%; height: 100%; background: #246bfe; transition: width .35s ease; }}
.muted {{ color: #667085; font-size: 13px; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<div class="panel">
  <h2>AI Reflow 正在本地解析</h2>
  <p id="stage">任务已进入后台队列，可以关闭此页面，稍后重新打开会继续读取本地缓存。</p>
  <div class="bar"><div id="fill" class="fill"></div></div>
  <p class="muted">{escaped_path}</p>
</div>
<script>
const docID = {json.dumps(doc_id)};
async function tick() {{
  const r = await fetch('/api/status?id=' + encodeURIComponent(docID));
  const s = await r.json();
  document.getElementById('stage').textContent = (s.status || 'working') + ' · ' + (s.stage || '');
  document.getElementById('fill').style.width = Math.max(4, s.progress || 0) + '%';
  if (s.status === 'ready') {{
    location.reload();
    return;
  }}
  setTimeout(tick, 1400);
}}
tick();
</script>
</body>
</html>"""


def html_page(title, doc_id, article, source_path):
    safe_title = html.escape(title or Path(source_path).name)
    escaped_path = html.escape(str(source_path))
    assets = get_assets(doc_id)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} - AI Reflow</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f5f6f8;
  --paper: #ffffff;
  --ink: #161b22;
  --muted: #667085;
  --line: #d8dde6;
  --accent: #2f6fed;
  --soft: #eef4ff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 17px/1.74 Georgia, "Times New Roman", "Noto Serif SC", serif;
}}
body.reader-fullscreen {{
  overflow: hidden;
  background: #fff;
}}
.topbar {{
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--line);
  background: rgba(255,255,255,.95);
  backdrop-filter: blur(10px);
  font-family: "Segoe UI", system-ui, sans-serif;
}}
.brand {{ color: #b42318; font-size: 20px; font-weight: 800; letter-spacing: 0; }}
.source {{
  min-width: 0;
  flex: 1;
  color: var(--muted);
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}}
button {{
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 6px;
  padding: 7px 11px;
  cursor: pointer;
  color: #1d2433;
  font: 14px/1.2 "Segoe UI", system-ui, sans-serif;
}}
button.primary {{
  color: #fff;
  border-color: var(--accent);
  background: var(--accent);
}}
.fullscreen-toggle {{
  min-width: 108px;
  font-weight: 650;
}}
.wrap {{
  max-width: 1060px;
  margin: 0 auto;
  padding: 18px 22px 52px;
}}
body.reader-fullscreen .topbar {{
  position: fixed;
  left: 0;
  right: 0;
}}
body.reader-fullscreen .source {{
  display: none;
}}
body.reader-fullscreen .wrap {{
  max-width: none;
  height: 100vh;
  overflow: auto;
  padding: 58px 0 0;
}}
article {{
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 30px 44px;
  box-shadow: 0 8px 24px rgba(16,24,40,.05);
}}
body.reader-fullscreen article {{
  width: 100%;
  min-height: calc(100vh - 58px);
  border: 0;
  border-radius: 0;
  box-shadow: none;
  padding: 34px max(34px, calc((100vw - 1120px) / 2));
}}
.block {{ margin: 0 0 20px; }}
h1,h2,h3 {{ line-height: 1.28; margin: 0 0 12px; font-family: Georgia, "Times New Roman", "Noto Serif SC", serif; }}
h1 {{ font-size: 29px; text-align: center; }}
h2 {{ font-size: 22px; margin-top: 30px; padding-top: 12px; border-top: 1px solid #eef1f5; }}
h3 {{ font-size: 18px; margin-top: 22px; }}
p {{ margin: 0; }}
.en {{ color: #101828; }}
.zh {{
  margin-top: 10px;
  padding-top: 9px;
  border-top: 2px dotted #d3d8df;
  color: #111827;
  font-family: "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif;
  font-size: 18px;
  line-height: 1.9;
}}
.heading-zh {{
  margin-top: -4px;
  border-top: 0;
  color: #4b5563;
  font-size: 15px;
}}
.pending {{ color: #98a2b3; }}
.formula-block {{
  margin: 24px auto;
  padding: 12px 0;
  overflow-x: auto;
  text-align: center;
}}
.formula-tex {{
  min-height: 34px;
  font-size: 18px;
}}
.formula-raw {{
  margin-top: 8px;
  color: var(--muted);
  font: 12px/1.45 Consolas, "SFMono-Regular", monospace;
}}
.media-block {{
  position: relative;
  margin: 28px auto 30px;
  text-align: center;
}}
.media-block img {{
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0 auto 12px;
}}
figcaption {{
  color: #344054;
  text-align: left;
  font-size: 16px;
  line-height: 1.62;
}}
.cap-en, .cap-zh {{ display: block; }}
.cap-zh {{
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dotted #d0d5dd;
  font-family: "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif;
}}
.explain {{
  position: absolute;
  right: 0;
  top: 6px;
  background: rgba(255,255,255,.94);
  font-weight: 650;
}}
.ai-panel {{
  position: fixed;
  right: 22px;
  bottom: 22px;
  width: min(680px, calc(100vw - 44px));
  max-height: 70vh;
  overflow: auto;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 16px 36px rgba(16,24,40,.16);
  padding: 0;
  font: 14px/1.65 "Microsoft YaHei", "Segoe UI", sans-serif;
}}
.ai-panel.empty {{ display: none; }}
.ai-head {{
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}}
.ai-close {{
  width: 28px;
  height: 28px;
  padding: 0;
  line-height: 1;
  font-size: 18px;
}}
.ai-body {{
  padding: 14px;
  white-space: normal;
}}
.ai-body h3 {{
  margin: 14px 0 8px;
  font: 700 17px/1.35 "Microsoft YaHei", "Segoe UI", sans-serif;
}}
.ai-body p {{
  margin: 0 0 12px;
  line-height: 1.78;
}}
.ai-body hr {{
  border: 0;
  border-top: 1px solid var(--line);
  margin: 12px 0;
}}
.chat-box {{
  display: grid;
  gap: 8px;
  padding: 0 14px 14px;
}}
.chat-box[hidden] {{
  display: none;
}}
.chat-box textarea {{
  width: 100%;
  min-height: 86px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 11px;
  font: 14px/1.6 "Microsoft YaHei", "Segoe UI", sans-serif;
}}
.chat-actions {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}}
.chat-hint {{
  color: var(--muted);
  font-size: 12px;
}}
.config-grid {{
  display: grid;
  gap: 9px;
  padding: 0 14px 14px;
}}
.config-grid[hidden] {{
  display: none;
}}
.config-grid label {{
  display: grid;
  gap: 4px;
  color: #344054;
  font-size: 12px;
  font-weight: 650;
}}
.config-grid input {{
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  font: 13px/1.5 Consolas, "SFMono-Regular", monospace;
}}
@media (max-width: 760px) {{
  body {{ font-size: 15px; }}
  .topbar {{ flex-wrap: wrap; }}
  .wrap {{ padding: 10px 10px 36px; }}
  article {{ padding: 22px 18px; }}
  h1 {{ font-size: 23px; }}
  .zh {{ font-size: 16px; }}
  .explain {{ position: static; margin-top: 8px; }}
}}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">Z</div>
  <button class="primary" onclick="summarize()">DeepSeek 摘要</button>
  <button onclick="openChat()">DeepSeek 问答</button>
  <button onclick="openConfig()">接口设置</button>
  <div class="source" title="{escaped_path}">{escaped_path}</div>
  <button id="fullscreenBtn" class="fullscreen-toggle" onclick="toggleFullscreen()" title="全屏阅读">⛶ 全屏阅读</button>
</div>
<div class="wrap">
  <article id="article">{article}</article>
</div>
<div id="ai" class="ai-panel empty">
  <div class="ai-head"><strong id="aiTitle">DeepSeek</strong><button class="ai-close" onclick="closeAI()" title="关闭">×</button></div>
  <div id="aiBody" class="ai-body"></div>
  <div id="chatBox" class="chat-box" hidden>
    <textarea id="chatInput" placeholder="询问这篇论文的方法、实验、公式、局限或某张图表..."></textarea>
    <div class="chat-actions">
      <span class="chat-hint">Ctrl+Enter 发送</span>
      <button id="chatSend" class="primary" onclick="askDeepSeek()">发送</button>
    </div>
  </div>
  <div id="configBox" class="config-grid" hidden>
    <label>DeepSeek API Key
      <input id="deepseekKeyInput" type="password" autocomplete="off" placeholder="sk-...">
    </label>
    <label>easyScholar SecretKey
      <input id="easyScholarKeyInput" type="password" autocomplete="off" placeholder="easyScholar SecretKey">
    </label>
    <div class="chat-actions">
      <span id="configHint" class="chat-hint">密钥只保存到本地缓存，不会显示在页面上。</span>
      <button class="primary" onclick="saveConfig()">保存</button>
    </div>
  </div>
</div>
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']] }},
  options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }}
}};
</script>
<script defer src="/static/mathjax/tex-chtml.js"></script>
<script>
const docID = {json.dumps(doc_id)};
const assets = {json.dumps(assets, ensure_ascii=False)};
const ai = document.getElementById('ai');
const aiTitle = document.getElementById('aiTitle');
const aiBody = document.getElementById('aiBody');
const chatBox = document.getElementById('chatBox');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');
const configBox = document.getElementById('configBox');
const deepseekKeyInput = document.getElementById('deepseekKeyInput');
const easyScholarKeyInput = document.getElementById('easyScholarKeyInput');
const configHint = document.getElementById('configHint');

function escapeHTML(text) {{
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}}

function inlineMarkdown(text) {{
  return escapeHTML(text).replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
}}

function markdownToHTML(text) {{
  const lines = String(text || '').replace(/\\r\\n/g, '\\n').split('\\n');
  const html = [];
  let paragraph = [];
  function flushParagraph() {{
    if (!paragraph.length) return;
    html.push('<p>' + inlineMarkdown(paragraph.join(' ')) + '</p>');
    paragraph = [];
  }}
  for (const line of lines) {{
    const trimmed = line.trim();
    if (!trimmed) {{
      flushParagraph();
      continue;
    }}
    if (/^---+$/.test(trimmed)) {{
      flushParagraph();
      html.push('<hr>');
      continue;
    }}
    const heading = trimmed.match(/^###\\s+(.+)$/);
    if (heading) {{
      flushParagraph();
      html.push('<h3>' + inlineMarkdown(heading[1]) + '</h3>');
      continue;
    }}
    paragraph.push(trimmed);
  }}
  flushParagraph();
  return html.join('');
}}

function typesetAI() {{
  if (window.MathJax && MathJax.typesetPromise) {{
    MathJax.typesetPromise([aiBody]).catch(() => {{}});
  }}
}}

function showAI(text, title = 'DeepSeek', options = {{}}) {{
  const chat = !!options.chat;
  aiTitle.textContent = title;
  aiBody.innerHTML = markdownToHTML(text || '');
  if (chatBox) {{
    chatBox.hidden = !chat;
  }}
  if (configBox) {{
    configBox.hidden = true;
  }}
  ai.classList.toggle('empty', !text && !chat);
  if (text) {{
    setTimeout(typesetAI, 0);
  }}
  if (chat && chatInput) {{
    setTimeout(() => chatInput.focus(), 0);
  }}
}}

function closeAI() {{
  showAI('', 'DeepSeek', {{ chat: false }});
}}

function openChat() {{
  showAI('可以直接询问这篇论文的核心方法、实验结论、公式含义、图表内容或局限性。回答会基于本地解析和已缓存的译文。', 'DeepSeek 问答', {{ chat: true }});
}}

async function openConfig() {{
  aiTitle.textContent = '接口设置';
  aiBody.innerHTML = '<p>输入或更新本地 API Key。密码框不会回显，留空表示保持原配置不变。</p>';
  if (chatBox) chatBox.hidden = true;
  if (configBox) configBox.hidden = false;
  ai.classList.remove('empty');
  if (deepseekKeyInput) deepseekKeyInput.value = '';
  if (easyScholarKeyInput) easyScholarKeyInput.value = '';
  try {{
    const r = await fetch('/api/config');
    const data = await r.json();
    configHint.textContent = `DeepSeek：${{data.deepseekConfigured ? '已配置' : '未配置'}}；easyScholar：${{data.easyScholarConfigured ? '已配置' : '未配置'}}`;
  }}
  catch (err) {{
    configHint.textContent = '读取配置状态失败';
  }}
}}

async function saveConfig() {{
  const body = {{
    deepseekKey: deepseekKeyInput && deepseekKeyInput.value || '',
    easyScholarKey: easyScholarKeyInput && easyScholarKeyInput.value || ''
  }};
  const r = await fetch('/api/config', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body)
  }});
  const data = await r.json();
  if (deepseekKeyInput) deepseekKeyInput.value = '';
  if (easyScholarKeyInput) easyScholarKeyInput.value = '';
  configHint.textContent = data.error
    ? ('保存失败：' + data.error)
    : `已保存。DeepSeek：${{data.deepseekConfigured ? '已配置' : '未配置'}}；easyScholar：${{data.easyScholarConfigured ? '已配置' : '未配置'}}`;
}}

function nativeFullscreenElement() {{
  return document.fullscreenElement
    || document.webkitFullscreenElement
    || document.mozFullScreenElement
    || document.msFullscreenElement;
}}

function setReaderFullscreen(enabled) {{
  document.body.classList.toggle('reader-fullscreen', enabled);
  const button = document.getElementById('fullscreenBtn');
  if (button) {{
    button.textContent = enabled ? '退出全屏' : '⛶ 全屏阅读';
  }}
}}

async function requestNativeFullscreen() {{
  const el = document.documentElement;
  const request = el.requestFullscreen
    || el.webkitRequestFullscreen
    || el.mozRequestFullScreen
    || el.msRequestFullscreen;
  if (request) {{
    await request.call(el);
  }}
}}

async function exitNativeFullscreen() {{
  const exit = document.exitFullscreen
    || document.webkitExitFullscreen
    || document.mozCancelFullScreen
    || document.msExitFullscreen;
  if (exit && nativeFullscreenElement()) {{
    await exit.call(document);
  }}
}}

async function toggleFullscreen() {{
  const entering = !document.body.classList.contains('reader-fullscreen') && !nativeFullscreenElement();
  setReaderFullscreen(entering);
  try {{
    if (entering) {{
      await requestNativeFullscreen();
      try {{
        window.fullScreen = true;
        window.moveTo(0, 0);
        window.resizeTo(screen.availWidth, screen.availHeight);
      }}
      catch (ignored) {{}}
    }}
    else {{
      await exitNativeFullscreen();
      try {{
        window.fullScreen = false;
      }}
      catch (ignored) {{}}
    }}
  }}
  catch (err) {{
    // Zotero's embedded browser can block native fullscreen. The CSS reader mode above still applies.
  }}
}}

document.addEventListener('fullscreenchange', () => {{
  setReaderFullscreen(!!nativeFullscreenElement());
}});
document.addEventListener('webkitfullscreenchange', () => {{
  setReaderFullscreen(!!nativeFullscreenElement());
}});
document.addEventListener('keydown', (event) => {{
  if (event.key === 'Escape' && document.body.classList.contains('reader-fullscreen') && !nativeFullscreenElement()) {{
    setReaderFullscreen(false);
  }}
}});
setReaderFullscreen(true);

async function summarize() {{
  showAI('DeepSeek 正在生成结构化精读摘要，完成后会写入本地缓存文件...', 'DeepSeek 摘要');
  const r = await fetch('/api/summary?id=' + encodeURIComponent(docID));
  const data = await r.json();
  if (r.status === 202) {{
    showAI(`后台仍在处理：${{data.status || 'working'}} · ${{data.stage || ''}}，进度 ${{data.progress || 0}}%。稍后再点摘要会直接读缓存。`, 'DeepSeek 摘要');
    return;
  }}
  let text = data.error || data.text || '没有返回内容';
  if (data.savedPath) {{
    text += '\\n\\n---\\n已保存到本地：' + data.savedPath;
  }}
  showAI(text, 'DeepSeek 摘要');
}}

async function askDeepSeek() {{
  const question = (chatInput && chatInput.value || '').trim();
  if (!question) {{
    return;
  }}
  chatSend.disabled = true;
  showAI('DeepSeek 正在结合本地解析正文和译文回答...', 'DeepSeek 问答', {{ chat: true }});
  try {{
    const r = await fetch('/api/chat', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ id: docID, question }})
    }});
    const data = await r.json();
    const answer = data.error || data.text || '没有返回内容';
    showAI('**问题：** ' + question + '\\n\\n' + answer, 'DeepSeek 问答', {{ chat: true }});
  }}
  catch (err) {{
    showAI('请求失败：' + err, 'DeepSeek 问答', {{ chat: true }});
  }}
  finally {{
    chatSend.disabled = false;
  }}
}}

if (chatInput) {{
  chatInput.addEventListener('keydown', (event) => {{
    if (event.key === 'Enter' && event.ctrlKey) {{
      event.preventDefault();
      askDeepSeek();
    }}
  }});
}}

async function explainAsset(kind, index) {{
  showAI('DeepSeek 正在解读图表...', 'AI 解释');
  const r = await fetch('/api/explain-asset', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ id: docID, kind, index }})
  }});
  const data = await r.json();
  showAI(data.error || data.text || '没有返回内容', 'AI 解释');
}}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def send_text(self, status, body, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, obj):
        self.send_text(status, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                return self.send_json(200, {"ok": True, "time": now()})
            if parsed.path == "/api/config":
                return self.send_json(200, config_status())
            if parsed.path == "/api/ingest":
                path = safe_pdf_path(qs.get("path", [""])[0])
                title = qs.get("title", [path.name])[0]
                venue = qs.get("venue", [""])[0]
                item_id = qs.get("itemID", [""])[0] or None
                translate = qs.get("translate", ["1"])[0] != "0"
                force = qs.get("force", ["0"])[0] == "1"
                doc_id, status = ingest_pdf(path, title=title, item_id=item_id, venue=venue, translate=translate, force=force)
                return self.send_json(200, {"id": doc_id, **status})
            if parsed.path == "/reflow":
                path = safe_pdf_path(qs.get("path", [""])[0])
                title = qs.get("title", [path.name])[0]
                venue = qs.get("venue", [""])[0]
                item_id = qs.get("itemID", [""])[0] or None
                doc_id = file_id(path)
                status = get_status(doc_id)
                article = get_article(doc_id)
                if article and status.get("status") == "ready" and AUTO_TRANSLATE:
                    blocks = get_blocks(doc_id)
                    if blocks:
                        if not translation_cache_complete(doc_id, blocks):
                            doc_id, status = ingest_pdf(path, title=title, item_id=item_id, venue=venue, translate=True)
                            return self.send_text(200, loading_page(title, doc_id, path))
                        if not blocks_have_translations(blocks):
                            blocks = translate_blocks(doc_id, blocks)
                            write_json(doc_dir(doc_id) / "blocks.json", blocks)
                            article = render_article(blocks)
                            (doc_dir(doc_id) / "article.html").write_text(article, encoding="utf-8")
                if not article or status.get("status") != "ready":
                    doc_id, status = ingest_pdf(path, title=title, item_id=item_id, venue=venue, translate=AUTO_TRANSLATE)
                    article = get_article(doc_id)
                if not article or status.get("status") != "ready":
                    return self.send_text(200, loading_page(title, doc_id, path))
                return self.send_text(200, html_page(title, doc_id, article, path))
            if parsed.path == "/api/status":
                return self.send_json(200, get_status(qs.get("id", [""])[0]))
            if parsed.path == "/api/assets":
                return self.send_json(200, get_assets(qs.get("id", [""])[0]))
            if parsed.path == "/api/blocks":
                return self.send_json(200, get_blocks(qs.get("id", [""])[0]))
            if parsed.path == "/api/translation":
                return self.send_text(200, get_article(qs.get("id", [""])[0]))
            if parsed.path == "/api/metadata":
                doc_id = qs.get("id", [""])[0]
                force = qs.get("force", ["0"])[0] == "1"
                cache_path = doc_dir(doc_id) / "metadata.json"
                cached = None if force else read_json(cache_path, None)
                if cached:
                    return self.send_json(200, cached)
                status = get_status(doc_id)
                job = JOBS.get(doc_id)
                if job and not job.done() and not get_blocks(doc_id):
                    return self.send_json(202, {"status": status.get("status"), "stage": status.get("stage"), "progress": status.get("progress", 0)})
                meta = ensure_metadata(doc_id, force=force)
                return self.send_json(200, meta)
            if parsed.path.startswith("/cache/"):
                return self.serve_cache(parsed.path)
            if parsed.path.startswith("/static/mathjax/"):
                return self.serve_mathjax(parsed.path)
            if parsed.path == "/api/summary":
                doc_id = qs.get("id", [""])[0]
                force = qs.get("force", ["0"])[0] == "1"
                cached = "" if force else get_summary(doc_id)
                if cached:
                    meta = read_json(doc_dir(doc_id) / "summary.json", {}) or {}
                    return self.send_json(200, {"text": cached, "cached": True, "savedPath": meta.get("sidecar")})
                status = get_status(doc_id)
                job = JOBS.get(doc_id)
                if job and not job.done():
                    return self.send_json(202, {"status": status.get("status"), "stage": status.get("stage"), "progress": status.get("progress", 0)})
                text = ensure_summary(doc_id, force=force)
                meta = read_json(doc_dir(doc_id) / "summary.json", {}) or {}
                set_status(doc_id, status="ready", stage="done", progress=100, error="")
                return self.send_json(200, {"text": text, "cached": False, "savedPath": meta.get("sidecar")})
            return self.send_text(404, "Not found", "text/plain; charset=utf-8")
        except Exception as exc:
            return self.send_json(500, {"error": str(exc)})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size).decode("utf-8") if size else "{}"
            data = json.loads(body)
            if parsed.path == "/api/explain-asset":
                doc_id = str(data.get("id", ""))
                kind = str(data.get("kind", ""))
                index = str(data.get("index", ""))
                assets = get_assets(doc_id)
                collection = assets["figures"] if kind == "figure" else assets["tables"]
                asset = None
                for candidate in collection:
                    values = {str(candidate.get("index", "")), str(candidate.get("number", "")), str(candidate.get("label", ""))}
                    if index in values:
                        asset = candidate
                        break
                if not asset:
                    return self.send_json(404, {"error": "Asset not found"})
                content = asset.get("caption") or json.dumps(asset, ensure_ascii=False)
                result = call_deepseek([
                    {
                        "role": "system",
                        "content": "你是论文图表解读助手。请用中文说明这个图或表在论文中的实验含义、变量、结论和需要注意的点。",
                    },
                    {"role": "user", "content": content[:12000]},
                ], max_tokens=1600)
                return self.send_json(200, {"text": result})
            if parsed.path == "/api/chat":
                doc_id = str(data.get("id", ""))
                question = str(data.get("question", ""))
                result = answer_paper_question(doc_id, question)
                return self.send_json(200, {"text": result})
            if parsed.path == "/api/config":
                updates = {}
                if data.get("deepseekKey"):
                    updates["DEEPSEEK_API_KEY"] = data.get("deepseekKey")
                if data.get("easyScholarKey"):
                    updates["EASYSCHOLAR_SECRET_KEY"] = data.get("easyScholarKey")
                if data.get("deepseekModel"):
                    updates["DEEPSEEK_MODEL"] = data.get("deepseekModel")
                save_config(updates)
                return self.send_json(200, config_status())
            return self.send_text(404, "Not found", "text/plain; charset=utf-8")
        except Exception as exc:
            return self.send_json(500, {"error": str(exc)})

    def serve_cache(self, request_path):
        parts = request_path.split("/")
        if len(parts) < 5 or parts[1] != "cache" or parts[3] != "images":
            return self.send_text(404, "Not found", "text/plain; charset=utf-8")
        doc_id = parts[2]
        name = urllib.parse.unquote(parts[4])
        if not re.match(r"^[A-Za-z0-9_. -]+$", name):
            return self.send_text(400, "Invalid file name", "text/plain; charset=utf-8")
        path = doc_dir(doc_id) / "images" / name
        if not path.exists():
            return self.send_text(404, "Not found", "text/plain; charset=utf-8")
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_mathjax(self, request_path):
        name = urllib.parse.unquote(request_path.removeprefix("/static/mathjax/"))
        parts = Path(name).parts
        if not name or any(part in {"", ".", ".."} for part in parts):
            return self.send_text(400, "Invalid file name", "text/plain; charset=utf-8")

        root = Path(__file__).resolve().parent / "node_modules" / "mathjax" / "es5"
        root = root.resolve()
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return self.send_text(400, "Invalid file name", "text/plain; charset=utf-8")
        if not path.exists() or path.is_dir():
            return self.send_text(404, "Not found", "text/plain; charset=utf-8")

        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("[reflow] " + fmt % args + "\n")


def main():
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Reflow service listening on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
