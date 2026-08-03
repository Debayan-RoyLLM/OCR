#!/usr/bin/env python3
"""
Upload-a-PDF -> extract text, using local "Unlimited OCR".

Mixed-PDF strategy: for each page we first read the born-digital text layer with
PyMuPDF (fast, exact, free). Only pages with little or no extractable text are
rendered to an image and sent to the OCR model -- so a searchable PDF costs no
OCR at all, and a scanned page still comes through.

The OCR engine is the `baidu/Unlimited-OCR` vision model served locally by vLLM
behind an OpenAI-compatible API. Start it (separate terminal) with:

    vllm serve baidu/Unlimited-OCR \
        --trust-remote-code \
        --logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor \
        --no-enable-prefix-caching \
        --mm-processor-cache-gb 0 \
        --tensor-parallel-size 1

Then:

    python ocr_app.py swimming.pdf                 # -> swimming.txt
    python ocr_app.py scan.pdf -o scan.txt         # choose output
    python ocr_app.py scan.pdf --force-ocr         # OCR every page, ignore text layer
    python ocr_app.py scan.pdf --pages 1-3,7       # only these pages
    python ocr_app.py scan.pdf --per-page          # one .txt per page next to output

Requires: pymupdf, openai   (both already installed)
"""

import argparse
import base64
import os
import sys

import fitz  # PyMuPDF


DEFAULT_PROMPT = (
    "You are an OCR engine. Transcribe ALL text visible in this image exactly, "
    "preserving the natural reading order and line breaks. Output only the "
    "transcribed text, with no commentary, labels, or markdown fences."
)


def parse_pages(spec, n):
    """'1-3,7' (1-based, inclusive) -> sorted 0-based page indices within [0, n)."""
    if not spec:
        return list(range(n))
    picked = set()
    for chunk in spec.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        if '-' in chunk:
            a, b = chunk.split('-', 1)
            for p in range(int(a), int(b) + 1):
                picked.add(p - 1)
        else:
            picked.add(int(chunk) - 1)
    return sorted(p for p in picked if 0 <= p < n)


def ocr_image(client, model, prompt, png_bytes, max_tokens):
    """Send one page image to the vLLM OCR server and return its transcription."""
    data_uri = 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')
    resp = client.chat.completions.create(
        model=model,
        messages=[{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': data_uri}},
            ],
        }],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return (resp.choices[0].message.content or '').strip()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf', help='path to the PDF to read')
    ap.add_argument('-o', '--out', help='output .txt (default: <pdf name>.txt)')
    ap.add_argument('--per-page', action='store_true',
                    help='also write one <out stem>.pNN.txt file per page')
    ap.add_argument('--force-ocr', action='store_true',
                    help='OCR every page even if it has a text layer')
    ap.add_argument('--min-chars', type=int, default=20,
                    help='a page with fewer extractable chars is sent to OCR (default 20)')
    ap.add_argument('--pages', help="pages to process, e.g. '1-3,7' (1-based)")
    ap.add_argument('--dpi', type=int, default=200,
                    help='render resolution for OCR pages (default 200)')
    ap.add_argument('--base-url', default=os.environ.get('OCR_BASE_URL', 'http://localhost:8000/v1'),
                    help='vLLM OpenAI-compatible endpoint (default http://localhost:8000/v1)')
    ap.add_argument('--model', default=os.environ.get('OCR_MODEL', 'baidu/Unlimited-OCR'),
                    help='served model name (default baidu/Unlimited-OCR)')
    ap.add_argument('--api-key', default=os.environ.get('OCR_API_KEY', 'EMPTY'),
                    help='API key for the server (vLLM ignores it; default EMPTY)')
    ap.add_argument('--max-tokens', type=int, default=8192,
                    help='max output tokens per OCR page (default 8192)')
    ap.add_argument('--prompt', default=DEFAULT_PROMPT, help='OCR instruction prompt')
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f'error: no such file: {args.pdf}')

    out_path = args.out or (os.path.splitext(args.pdf)[0] + '.txt')

    doc = fitz.open(args.pdf)
    indices = parse_pages(args.pages, doc.page_count)
    if not indices:
        sys.exit('error: no pages selected')

    client = None  # created lazily, only if a page actually needs OCR
    zoom = args.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    page_texts = []
    used_ocr = 0
    for idx in indices:
        page = doc[idx]
        text = '' if args.force_ocr else (page.get_text() or '').strip()

        if len(text) >= args.min_chars:
            source = 'text'
        else:
            if client is None:
                from openai import OpenAI, APIConnectionError
                global _APIConnectionError
                _APIConnectionError = APIConnectionError
                client = OpenAI(base_url=args.base_url, api_key=args.api_key)
            png = page.get_pixmap(matrix=matrix).tobytes('png')
            try:
                text = ocr_image(client, args.model, args.prompt, png, args.max_tokens)
            except _APIConnectionError:
                sys.exit(f"error: cannot reach OCR server at {args.base_url}\n"
                         f"       start it with the `vllm serve baidu/Unlimited-OCR ...` "
                         f"command (see the header of this file).")
            source = 'ocr'
            used_ocr += 1

        print(f'  page {idx + 1:>3}/{doc.page_count}  [{source}]  {len(text):>6} chars',
              file=sys.stderr)
        page_texts.append((idx, text))

        if args.per_page:
            stem = os.path.splitext(out_path)[0]
            with open(f'{stem}.p{idx + 1:02d}.txt', 'w', encoding='utf-8') as f:
                f.write(text + '\n')

    doc.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        for i, (idx, text) in enumerate(page_texts):
            if i:
                f.write('\n\n')
            f.write(f'===== Page {idx + 1} =====\n{text}\n')

    print(f'\nWrote {out_path}  ({len(page_texts)} pages, {used_ocr} via OCR)',
          file=sys.stderr)


if __name__ == '__main__':
    main()
