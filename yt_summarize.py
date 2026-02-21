#!/usr/bin/env python3
"""YouTube Summarizer Dashboard — paste a link, get a summary."""

import json
import math
import re
import urllib.request
import webbrowser
from collections import Counter

from flask import Flask, jsonify, render_template_string, request
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)

STOP_WORDS = frozenset(
    "a about above after again against all am an and any are aren't as at be because been "
    "before being below between both but by can can't cannot could couldn't did didn't do does "
    "doesn't doing don't down during each few for from further get got had hadn't has hasn't "
    "have haven't having he he'd he'll he's her here here's hers herself him himself his how "
    "how's i i'd i'll i'm i've if in into is isn't it it's its itself just let's me more most "
    "mustn't my myself no nor not of off on once one only or other ought our ours ourselves out "
    "over own really right said same say she she'd she'll she's should shouldn't so some such "
    "than that that's the their theirs them themselves then there there's these they they'd "
    "they'll they're they've this those through to too under until up us very want was wasn't we "
    "we'd we'll we're we've were weren't what what's when when's where where's which while who "
    "who's whom why why's will with won't would wouldn't you you'd you'll you're you've your "
    "yours yourself yourselves going go know like well also got thing things think gonna "
    "yeah yes okay oh actually um uh ah hey hi sort kind way basically".split()
)


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


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling poorly-punctuated transcripts."""
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    sentences = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part.split()) > 40:
            clauses = re.split(r",\s+(?=[A-Z])| and (?=[A-Z])| but (?=[A-Z])| so (?=[A-Z])", part)
            sentences.extend(c.strip() for c in clauses if len(c.strip().split()) >= 4)
        else:
            if len(part.split()) >= 4:
                sentences.append(part)
    return sentences


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def score_sentences(sentences: list[str]) -> list[float]:
    """Score sentences using TF-IDF plus position bias."""
    sent_tokens = []
    for s in sentences:
        tokens = [t for t in tokenize(s) if t not in STOP_WORDS and len(t) > 2]
        sent_tokens.append(tokens)

    num_sents = len(sentences)
    df = Counter()
    for tokens in sent_tokens:
        for t in set(tokens):
            df[t] += 1

    scores = []
    for idx, tokens in enumerate(sent_tokens):
        if not tokens:
            scores.append(0.0)
            continue
        tf = Counter(tokens)
        tfidf = sum(
            (1 + math.log(tf[t])) * math.log(num_sents / df[t])
            for t in tf
        )
        tfidf /= math.sqrt(len(tokens))

        pos = idx / num_sents
        if pos < 0.10:
            tfidf *= 1.3
        elif pos > 0.95:
            tfidf *= 1.15

        scores.append(tfidf)
    return scores


def summarize(text: str, mode: str = "medium") -> str:
    """Chunked extractive summarization.

    mode: "brief" (~125 words), "medium" (~400 words), "long" (~600 words)
    """
    sentences = split_sentences(text)
    if len(sentences) <= 8:
        return "\n\n".join(sentences)

    scores = score_sentences(sentences)
    pick_per_chunk = {"brief": 1, "medium": 2, "long": 3}.get(mode, 2)
    num_divisions = {"brief": 7, "medium": 10, "long": 10}.get(mode, 10)

    chunk_size = max(8, len(sentences) // num_divisions)
    chunks = []
    for i in range(0, len(sentences), chunk_size):
        chunks.append(list(range(i, min(i + chunk_size, len(sentences)))))

    selected = []
    for chunk_indices in chunks:
        ranked = sorted(chunk_indices, key=lambda i: scores[i], reverse=True)
        best = sorted(ranked[:pick_per_chunk])
        selected.extend(best)

    paragraphs = []
    current = [sentences[selected[0]]]
    for i in range(1, len(selected)):
        gap = selected[i] - selected[i - 1]
        if gap > chunk_size // 2:
            paragraphs.append(" ".join(current))
            current = []
        current.append(sentences[selected[i]])
    paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


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
  <p class="subtitle">Paste a YouTube link to get a transcript summary.</p>
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
