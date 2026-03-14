#!/usr/bin/env python3
import json
import argparse


from urllib.parse import unquote, urlparse, parse_qs


def transform_video_url(vurl):
    if not vurl:
        return ''

    parsed = urlparse(vurl)
    if parsed.netloc == 'cw-player.netlify.app' and parsed.path == '/play':
        q = parse_qs(parsed.query)
        video_values = q.get('video') or q.get('video_url') or q.get('v')
        if video_values:
            return unquote(video_values[0])
    # if direct cloudfront URL already, keep as is
    return vurl


def format_text(data):
    lines = []
    lines.append(f"Batch: {data.get('batch_url', '')}")

    for t in data.get('topics', []):
        lines.append(f"\nTopic: {t.get('name', '')} ({t.get('id', '')})")

        for c in t.get('classes', []):
            title = c.get('title', '')
            vid = c.get('video_id', '')
            vurl_raw = c.get('video_url', '')
            vurl = transform_video_url(vurl_raw)
            lines.append(f"  Lecture: {title} | video_id: {vid} | video_url: {vurl}")

        for p in t.get('notes', []):
            pt = p.get('title', '')
            pu = p.get('url', '')
            lines.append(f"  PDF: {pt} | url: {pu}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Convert extracted batch JSON to text')
    parser.add_argument('--input', '-i', default='output.json', help='Input JSON file')
    parser.add_argument('--output', '-o', default='output.txt', help='Output text file')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text = format_text(data)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"Saved textual report to {args.output}")


if __name__ == '__main__':
    main()
