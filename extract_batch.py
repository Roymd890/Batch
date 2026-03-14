#!/usr/bin/env python3
import argparse
import json
import re
import sys
from urllib.parse import urljoin, urlparse

import requests


def fetch_url(url, session=None):
    if session is None:
        session = requests.Session()
    res = session.get(url, timeout=30)
    res.raise_for_status()
    return res.text


def decode_next_f_scripts(script):
    decoded = []
    token = 'self.__next_f.push([1,"'
    pos = 0
    while True:
        start = script.find(token, pos)
        if start == -1:
            break
        i = start + len(token)
        buf = []
        escaped = False
        while i < len(script):
            ch = script[i]
            if escaped:
                buf.append('\\' + ch)
                escaped = False
                i += 1
                continue
            if ch == '\\':
                escaped = True
                i += 1
                continue
            if ch == '"':
                break
            buf.append(ch)
            i += 1

        txt = ''.join(buf)
        try:
            raw = bytes(txt, 'utf-8').decode('unicode_escape')
            decoded.append(raw)
        except Exception:
            pass

        pos = i + 1
    return decoded


def extract_script_payloads(html):
    # Extract script contents and any embedded Flight payload strings
    payloads = []
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE):
        content = m.group(1)
        if "__next_f" in content or "self.__next_f" in content or "next_f" in content:
            payloads.append(content)
            payloads.extend(decode_next_f_scripts(content))
    return payloads


def extract_json_object(text, start_idx):
    # Parse a JSON object from start_idx where text[start_idx] == '{'.
    depth = 0
    in_string = False
    escape = False
    string_char = None

    for i in range(start_idx, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
            continue

        if ch == '"' or ch == "'":
            in_string = True
            string_char = ch
            continue

        if ch == '{':
            depth += 1
            if depth == 1:
                # mark beginning
                begin = i
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[begin:i + 1]

    return None


def find_json_objects_with_key(html, key):
    # Find JSON object snippets that include a specific property key
    objects = []
    for m in re.finditer(re.escape(key), html):
        # find preceding '{' that probably begins object
        start = html.rfind('{', 0, m.start())
        if start == -1:
            continue

        obj_text = extract_json_object(html, start)
        if not obj_text:
            continue

        if obj_text in objects:
            continue

        # additional check: key present in object text
        if key not in obj_text:
            continue

        objects.append(obj_text)
    return objects


def parse_json_object(text):
    # Try direct JSON parsing, then fallback by cleaning trailing commas
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Remove trailing commas in objects/arrays (lenient-ish)
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(cleaned)


def collect_topics(batch_html):
    payloads = extract_script_payloads(batch_html)
    topics = []

    for payload in payloads:
        # try both topic wrapper and direct topic objects
        for key in ['"topic"', '"topicName"']:
            for obj_text in find_json_objects_with_key(payload, key):
                try:
                    obj = parse_json_object(obj_text)
                except Exception:
                    continue

                if isinstance(obj, dict) and 'topic' in obj and isinstance(obj['topic'], dict):
                    topic = obj['topic']
                elif isinstance(obj, dict) and 'id' in obj and 'topicName' in obj:
                    topic = obj
                else:
                    continue

                if 'id' in topic and 'topicName' in topic:
                    topics.append({'id': topic['id'], 'topicName': topic.get('topicName'), 'cls_count': topic.get('cls_count'), 'notes_count': topic.get('notes_count')})

    # Deduplicate by id while preserving insertion order
    uniq = {}
    for t in topics:
        uniq[t['id']] = t
    return list(uniq.values())


def collect_topic_details(topic_html):
    payloads = extract_script_payloads(topic_html)

    for payload in payloads:
        # find details object
        for obj_text in find_json_objects_with_key(payload, '"details"'):
            try:
                obj = parse_json_object(obj_text)
            except Exception:
                continue

            if isinstance(obj, dict) and 'details' in obj and isinstance(obj['details'], dict):
                details = obj['details']
            elif isinstance(obj, dict) and 'classes' in obj and 'notes' in obj:
                details = obj
            else:
                continue

            classes = details.get('classes') if isinstance(details.get('classes'), list) else []
            notes = details.get('notes') if isinstance(details.get('notes'), list) else []
            return classes, notes

    # fallback in entire html, in case details at top-level
    for obj_text in find_json_objects_with_key(topic_html, '"classes"'):
        try:
            obj = parse_json_object(obj_text)
        except Exception:
            continue

        if isinstance(obj, dict) and 'classes' in obj:
            return obj.get('classes', []), obj.get('notes', [])

    return [], []


def resolve_video_url(raw, base_url, session):
    if not raw:
        return None

    if raw.startswith('http://') or raw.startswith('https://'):
        return raw

    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidate = raw
    # sometimes it can be an object or the actual field name maybe video_id
    if isinstance(raw, dict):
        candidate = raw.get('videoId') or raw.get('id') or raw.get('video_url')

    if candidate is None:
        return None

    endpoint = urljoin(base, f"/api/video-redirect?videoId={candidate}")
    try:
        resp = session.get(endpoint, allow_redirects=False, timeout=30)
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp.headers.get('Location')
    except requests.RequestException:
        pass

    return candidate


def run(batch_url, output_json=None, quiet=False):
    session = requests.Session()
    batch_html = fetch_url(batch_url, session)

    topics = collect_topics(batch_html)
    if not quiet:
        print(f"Found {len(topics)} topics in batch")

    batch_data = {
        'batch_url': batch_url,
        'topics': []
    }

    for t in topics:
        topic_id = t['id']
        topic_name = t['topicName']
        if not topic_id:
            continue

        # we assume topic pages are /topic/{batchId}/{topicId} or by route in the batch link
        # If topic item provides URL, use it; otherwise try a scheme.
        topic_url = t.get('topicUrl') or t.get('href')
        if not topic_url:
            # fallback from batch URL if possible
            parsed = urlparse(batch_url)
            if parsed.path.startswith('/batch/'):
                batch_id = parsed.path.split('/')[2] if len(parsed.path.split('/')) > 2 else None
                if batch_id:
                    topic_url = urljoin(batch_url, f"/topic/{batch_id}/{topic_id}")

        if not topic_url:
            if not quiet:
                print(f"Skip topic {topic_name} ({topic_id}) no URL")
            continue

        if not quiet:
            print(f"Fetching topic: {topic_name} ({topic_id}) -> {topic_url}")

        topic_html = fetch_url(topic_url, session)
        classes, notes = collect_topic_details(topic_html)

        entries = []
        for c in classes:
            lecture_title = c.get('title') or c.get('class') or c.get('lecture')
            raw_video = c.get('video_url') or c.get('videoId') or c.get('video_id')
            video_url = resolve_video_url(raw_video, batch_url, session)
            entries.append({'type': 'lecture', 'title': lecture_title, 'video_id': raw_video, 'video_url': video_url})

        pdfs = []
        for n in notes:
            pdf_title = n.get('title') or n.get('name')
            pdf_url = n.get('download_url') or n.get('url')
            pdfs.append({'title': pdf_title, 'url': pdf_url})

        batch_data['topics'].append({
            'id': topic_id,
            'name': topic_name,
            'classes': entries,
            'notes': pdfs,
        })

    if output_json:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        if not quiet:
            print(f"Saved output to {output_json}")
    else:
        # print formatted
        print(f"Batch: {batch_url}")
        for t in batch_data['topics']:
            print(f"\n  Topic: {t['name']} ({t['id']})")
            for c in t['classes']:
                print(f"  - Lecture: {c['title']} -> {c['video_url']}")
            for p in t['notes']:
                print(f"  - PDF: {p['title']} -> {p['url']}")

    return batch_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extract batch topics, lectures, and PDF links from Next.js Flight payloads')
    parser.add_argument('batch_url', help='Batch page URL (e.g., https://example.com/batch/3289)')
    parser.add_argument('--output', '-o', help='Write JSON output to file')
    parser.add_argument('--quiet', '-q', action='store_true', help='Lower verbosity')
    args = parser.parse_args()

    try:
        run(args.batch_url, output_json=args.output, quiet=args.quiet)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
