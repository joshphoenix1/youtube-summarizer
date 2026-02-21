#!/usr/bin/env python3
"""YouTube Summarizer Dashboard — paste a link, get an AI summary."""

import json
import os
import re
import urllib.request
import webbrowser

from flask import Flask, jsonify, render_template_string, request
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)


def extract_video_id(url: str) -> str:
    """Extract the video ID from various YouTube URL formats."""
    patterns = [
        r"(?:v=|/v/)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from '{url}'")


def fetch_title(video_id: str) -> str:
    """Fetch the video title via YouTube's oEmbed endpoint."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(oembed_url, timeout=5) as resp:
            return json.loads(resp.read()).get("title", "")
    except Exception:
        return ""


def fetch_transcript(video_id: str, lang: str = "en") -> str:
    """Fetch and join the transcript for a YouTube video."""
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=[lang])
        return " ".join(snippet.text for snippet in transcript.snippets)
    except Exception as e:
        raise RuntimeError(f"Error fetching transcript: {e}") from e


def summarize(text: str, mode: str = "medium") -> str:
    """Summarize text using Groq's LLM API."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set. Get a free key at console.groq.com")

    word_targets = {"brief": "125", "medium": "400", "long": "600"}
    target = word_targets.get(mode, "400")

    payload = json.dumps({
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": f"You are a helpful summarizer. Summarize the following video transcript in about {target} words. Write clear, well-structured paragraphs. Do not use bullet points or lists."},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "yt-summarizer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Groq API error ({e.code}): {body}") from e


# ── Routes ────────────────────────────────────────────────────────────────────

PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Summarizer</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    max-width: 720px; margin: 60px auto; padding: 0 20px;
    background: #f8f9fa; color: #212529;
  }
  h1 { margin-bottom: 4px; }
  .subtitle { color: #6c757d; margin-bottom: 28px; }
  form { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  input[type="text"] {
    flex: 1 1 300px; padding: 10px 14px; font-size: 15px;
    border: 1px solid #ced4da; border-radius: 6px; outline: none;
  }
  input[type="text"]:focus { border-color: #4a90d9; box-shadow: 0 0 0 3px rgba(74,144,217,.15); }
  button {
    padding: 10px 22px; font-size: 15px; font-weight: 600;
    background: #4a90d9; color: #fff; border: none; border-radius: 6px; cursor: pointer;
  }
  button:hover { background: #3a7bc8; }
  button:disabled { background: #a0c4e8; cursor: not-allowed; }
  .mode-row { width: 100%; display: flex; align-items: center; gap: 6px; margin-top: 2px; }
  .mode-row span { font-size: 14px; color: #495057; }
  .mode-row label { font-size: 14px; color: #495057; cursor: pointer; margin-left: 4px; }
  .mode-row input[type="radio"] { margin: 0 2px 0 10px; }
  #spinner {
    display: none; margin: 30px 0; text-align: center; color: #6c757d; font-size: 15px;
  }
  #spinner .dot { animation: blink 1.4s infinite both; }
  #spinner .dot:nth-child(2) { animation-delay: 0.2s; }
  #spinner .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes blink { 0%,80%,100%{ opacity:0; } 40%{ opacity:1; } }
  #error {
    display: none; margin: 24px 0; padding: 14px 18px;
    background: #fff0f0; border-left: 4px solid #e74c3c; border-radius: 4px;
    color: #c0392b; font-size: 14px;
  }
  #title {
    display: none; margin: 28px 0 0 0; font-size: 20px; font-weight: 600; color: #212529;
  }
  #summary {
    display: none; margin: 12px 0 28px 0; padding: 20px 24px;
    background: #fff; border: 1px solid #dee2e6; border-radius: 8px;
    line-height: 1.7; font-size: 15px; white-space: pre-line;
  }
</style>
</head>
<body>
  <h1>YouTube Summarizer</h1>
  <p class="subtitle">Paste a YouTube link to get an AI-powered summary.</p>
  <form id="form">
    <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=..." required>
    <button type="submit" id="btn">Summarize</button>
    <div class="mode-row">
      <span>Length:</span>
      <input type="radio" name="mode" id="brief" value="brief">
      <label for="brief">Brief</label>
      <input type="radio" name="mode" id="medium" value="medium" checked>
      <label for="medium">Medium</label>
      <input type="radio" name="mode" id="long" value="long">
      <label for="long">Long</label>
    </div>
  </form>
  <div id="spinner">Summarizing<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></div>
  <div id="error"></div>
  <h2 id="title"></h2>
  <div id="summary"></div>
<script>
document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("btn");
  const spinner = document.getElementById("spinner");
  const errorDiv = document.getElementById("error");
  const titleDiv = document.getElementById("title");
  const summaryDiv = document.getElementById("summary");
  const url = document.getElementById("url").value.trim();
  if (!url) return;

  btn.disabled = true;
  spinner.style.display = "block";
  errorDiv.style.display = "none";
  titleDiv.style.display = "none";
  summaryDiv.style.display = "none";

  try {
    const resp = await fetch("/summarize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url, mode: document.querySelector('input[name="mode"]:checked').value}),
    });
    const data = await resp.json();
    if (data.error) {
      errorDiv.textContent = data.error;
      errorDiv.style.display = "block";
    } else {
      if (data.title) {
        titleDiv.textContent = data.title;
        titleDiv.style.display = "block";
      }
      summaryDiv.textContent = data.summary;
      summaryDiv.style.display = "block";
    }
  } catch (err) {
    errorDiv.textContent = "Request failed: " + err.message;
    errorDiv.style.display = "block";
  } finally {
    btn.disabled = false;
    spinner.style.display = "none";
  }
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE_HTML)


@app.route("/summarize", methods=["POST"])
def summarize_route():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    mode = data.get("mode", "medium")
    if mode not in ("brief", "medium", "long"):
        mode = "medium"

    if not url:
        return jsonify(error="No URL provided."), 400

    try:
        video_id = extract_video_id(url)
        title = fetch_title(video_id)
        transcript = fetch_transcript(video_id)
        summary = summarize(transcript, mode=mode)
        return jsonify(summary=summary, title=title)
    except (ValueError, RuntimeError) as e:
        return jsonify(error=str(e)), 422
    except Exception as e:
        return jsonify(error=f"Unexpected error: {e}"), 500


PORT = 5006

if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print(f" * Starting on {url}")
    webbrowser.open(url)
    app.run(port=PORT)
