# Batch

This project includes `extract_batch.py`, a scraper that pulls course topics, lectures, and PDF links from `vipcw.vercel.app` (Next.js App Router Flight payload format).

## Features

- Batch topic discovery from `/batch/{batchId}`
- Per-topic details from `/topic/{batchId}/{topicId}`
- Lecture titles and video IDs
- Video playback links (CloudFront HLS & MPD via player redirect)
- Notes/PDF links
- Optional JSON output

## Run locally

1. Ensure dependencies:
   - Python 3.8+
   - `requests` library

   Install with:
   ```bash
   pip install -r requirements.txt
   # or
   pip install requests
   ```

2. Run the script on a batch URL:
   ```bash
   cd /workspaces/Batch
   python3 extract_batch.py https://vipcw.vercel.app/batch/3289
   ```

3. Save results as JSON:
   ```bash
   python3 extract_batch.py https://vipcw.vercel.app/batch/3289 -o output.json
   ```

4. Quiet mode:
   ```bash
   python3 extract_batch.py https://vipcw.vercel.app/batch/3289 -q
   ```

## How to extract additional batches (step-by-step)

1. Find `batchId` from the URL you want (e.g., `https://vipcw.vercel.app/batch/1234`).
2. Run extraction:
   ```bash
   python3 extract_batch.py https://vipcw.vercel.app/batch/1234 -o batch_1234.json
   ```
3. Check `batch_1234.json` for `topics` array. Each topic includes classes and notes.
4. If authentication is required for your site, modify `extract_batch.py` `fetch_url()` to add cookies/headers.
5. Optionally, add batch loop script:
   ```bash
   for batch in 3289 3290 3291; do
     python3 extract_batch.py https://vipcw.vercel.app/batch/$batch -o batch_${batch}.json
   done
   ```

## Inspect output

- `output.json` fields:
  - `batch_url`
  - `topics[]`: `id`, `name`, `classes[]`, `notes[]`
  - `classes[]`: `title`, `video_id`, `video_url`
  - `notes[]`: `title`, `url`

## Troubleshooting

- `404` from a URL means wrong `batchId` or inaccessible resource.
- `ConnectionError` may require proxy/credentials.
- If you see zero topics, verify that the URL is valid and has data in Flight payload (in browser page source search for `self.__next_f.push`).
