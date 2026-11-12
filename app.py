import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "clef-flash:latest")
PORT = int(os.environ.get("PORT", "8080"))


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clef Decisions</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100">
  <main class="mx-auto max-w-6xl px-4 py-10 sm:px-6">
    <header class="mb-8">
      <p class="mb-2 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">Ollama decision model</p>
      <h1 class="text-4xl font-bold tracking-tight">Clef Flash</h1>
      <p class="mt-3 max-w-2xl text-slate-400">Describe a state, define the decisions you need, and receive calibrated probabilities in one request.</p>
    </header>

    <div class="grid gap-6 lg:grid-cols-[1.1fr_.9fr]">
      <form id="decision-form" class="space-y-6 rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl shadow-cyan-950/20 sm:p-7">
        <section>
          <label for="state" class="text-sm font-semibold text-slate-200">State</label>
          <p class="mt-1 text-sm text-slate-400">Text or JSON describing the situation to evaluate.</p>
          <textarea id="state" required autofocus rows="7" placeholder="Checkout has been failing for every customer for the last hour." class="mt-3 w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"></textarea>
        </section>

        <section>
          <div class="flex items-center justify-between gap-4">
            <div>
              <h2 class="text-sm font-semibold text-slate-200">Decision questions</h2>
              <p class="mt-1 text-sm text-slate-400">Use a typed question instead of hand-writing the API schema.</p>
            </div>
            <button type="button" id="add-question" class="rounded-lg border border-cyan-400/50 px-3 py-2 text-sm font-semibold text-cyan-300 hover:bg-cyan-400/10">Add question</button>
          </div>
          <div id="questions" class="mt-4 space-y-4"></div>
        </section>

        <p id="form-error" class="hidden rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200"></p>
        <button id="submit" type="submit" class="w-full rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-wait disabled:opacity-60">Make decisions</button>
      </form>

      <section class="rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl shadow-cyan-950/20 sm:p-7">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold">Results</h2>
            <p class="mt-1 text-sm text-slate-400">Clef's chosen answer and probability distribution.</p>
          </div>
          <span id="status" class="rounded-full bg-slate-800 px-3 py-1 text-xs font-medium text-slate-300">Ready</span>
        </div>
        <div id="metrics" class="mt-5 hidden grid-cols-2 gap-3"></div>
        <div id="answers" class="mt-5 space-y-4">
          <div class="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">Submit a decision to see results.</div>
        </div>
        <details class="mt-5 rounded-xl border border-slate-700 bg-slate-950/60 p-4">
          <summary class="cursor-pointer text-sm font-semibold text-slate-300">Developer debug data</summary>
          <p class="mt-2 text-xs text-slate-500">Exact SystemOne request generated from the form and the raw Ollama response.</p>
          <pre id="debug" class="mt-3 overflow-x-auto text-xs leading-5 text-slate-300"></pre>
        </details>
      </section>
    </div>
  </main>

  <template id="question-template">
    <article class="question rounded-xl border border-slate-700 bg-slate-950/50 p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="grid flex-1 gap-3 sm:grid-cols-2">
          <label class="text-xs font-medium text-slate-400">Question ID
            <input data-field="id" required class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-cyan-400">
          </label>
          <label class="text-xs font-medium text-slate-400">Type
            <select data-field="type" class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-cyan-400">
              <option value="noul">Yes / no</option>
              <option value="choice">Choice</option>
              <option value="score">Score</option>
            </select>
          </label>
        </div>
        <button type="button" data-action="remove-question" class="rounded-lg p-2 text-slate-500 hover:bg-rose-500/10 hover:text-rose-300" aria-label="Remove question">×</button>
      </div>
      <label class="mt-3 block text-xs font-medium text-slate-400">Instructions
        <input data-field="instructions" required class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-cyan-400">
      </label>
      <div data-field="criteria" class="mt-3"></div>
    </article>
  </template>

  <script>
    const form = document.querySelector("#decision-form");
    const questions = document.querySelector("#questions");
    const state = document.querySelector("#state");
    const submit = document.querySelector("#submit");
    const error = document.querySelector("#form-error");
    const answers = document.querySelector("#answers");
    const metrics = document.querySelector("#metrics");
    const status = document.querySelector("#status");
    const debug = document.querySelector("#debug");
    let questionNumber = 0;

    function input(label, value = "", placeholder = "") {
      return `<label class="block text-xs text-slate-400">${label}<input value="${value}" placeholder="${placeholder}" class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-cyan-400"></label>`;
    }

    function criteriaMarkup(type) {
      if (type === "noul") {
        return `<p class="text-xs text-slate-400">Optional criteria descriptions</p><div class="mt-2 grid gap-2 sm:grid-cols-2"><div data-criterion="true">${input("True")}</div><div data-criterion="false">${input("False")}</div></div>`;
      }
      if (type === "choice") {
        return `<div class="flex items-center justify-between"><p class="text-xs text-slate-400">Options</p><button type="button" data-action="add-option" class="text-xs font-semibold text-cyan-300">Add option</button></div><div data-options class="mt-2 space-y-2"></div>`;
      }
      return `<div class="flex items-center justify-between"><p class="text-xs text-slate-400">Levels, lowest to highest</p><button type="button" data-action="add-level" class="text-xs font-semibold text-cyan-300">Add level</button></div><div data-levels class="mt-2 space-y-2"></div>`;
    }

    function optionRow(name = "", description = "") {
      return `<div data-option class="grid grid-cols-[1fr_1.5fr_auto] gap-2">${input("Name", name, "technical")}${input("Description", description, "Outages and errors")}<button type="button" data-action="remove-option" class="mt-5 rounded-lg px-2 text-slate-500 hover:text-rose-300">×</button></div>`;
    }

    function levelRow(description = "") {
      return `<div data-level class="grid grid-cols-[1fr_auto] gap-2">${input("Level description", description, "Low impact")}<button type="button" data-action="remove-level" class="mt-5 rounded-lg px-2 text-slate-500 hover:text-rose-300">×</button></div>`;
    }

    function renderCriteria(card) {
      const type = card.querySelector('[data-field="type"]').value;
      const criteria = card.querySelector('[data-field="criteria"]');
      criteria.innerHTML = criteriaMarkup(type);
      if (type === "choice") {
        const options = criteria.querySelector("[data-options]");
        options.insertAdjacentHTML("beforeend", optionRow("billing", "Payments, invoices, and refunds"));
        options.insertAdjacentHTML("beforeend", optionRow("technical", "Outages, errors, and configuration"));
      } else if (type === "score") {
        const levels = criteria.querySelector("[data-levels]");
        levels.insertAdjacentHTML("beforeend", levelRow("Low impact"));
        levels.insertAdjacentHTML("beforeend", levelRow("High impact"));
      }
    }

    function addQuestion(values = {}) {
      const card = document.querySelector("#question-template").content.firstElementChild.cloneNode(true);
      questionNumber += 1;
      card.querySelector('[data-field="id"]').value = values.id || `decision_${questionNumber}`;
      card.querySelector('[data-field="instructions"]').value = values.instructions || "Is this request urgent?";
      card.querySelector('[data-field="type"]').value = values.type || "noul";
      renderCriteria(card);
      questions.append(card);
    }

    function collectQuestion(card) {
      const id = card.querySelector('[data-field="id"]').value.trim();
      const type = card.querySelector('[data-field="type"]').value;
      const instructions = card.querySelector('[data-field="instructions"]').value.trim();
      if (!id || !instructions) throw new Error("Every question needs an ID and instructions.");
      const question = { type, instructions };
      if (type === "noul") {
        const criteria = {};
        card.querySelectorAll("[data-criterion]").forEach((item) => {
          const value = item.querySelector("input").value.trim();
          if (value) criteria[item.dataset.criterion] = value;
        });
        if (Object.keys(criteria).length) question.criteria = criteria;
      } else if (type === "choice") {
        question.criteria = {};
        card.querySelectorAll("[data-option]").forEach((item) => {
          const [name, description] = [...item.querySelectorAll("input")].map((field) => field.value.trim());
          if (!name) throw new Error("Every choice option needs a name.");
          question.criteria[name] = description || null;
        });
        if (Object.keys(question.criteria).length < 2) throw new Error("Choice questions need at least two options.");
      } else {
        question.criteria = [...card.querySelectorAll("[data-level] input")].map((field) => field.value.trim());
        if (question.criteria.length < 2 || question.criteria.some((level) => !level)) throw new Error("Score questions need at least two named levels.");
      }
      return [id, question];
    }

    function percent(value) {
      return `${(value * 100).toFixed(1)}%`;
    }

    function probabilityRows(probabilities) {
      const wrapper = document.createElement("div");
      wrapper.className = "mt-3 space-y-2";
      Object.entries(probabilities).forEach(([name, value]) => {
        const row = document.createElement("div");
        row.innerHTML = `<div class="mb-1 flex justify-between text-xs text-slate-400"><span></span><strong class="text-slate-200"></strong></div><div class="h-1.5 overflow-hidden rounded-full bg-slate-800"><div class="h-full rounded-full bg-cyan-400"></div></div>`;
        row.querySelector("span").textContent = name;
        row.querySelector("strong").textContent = percent(value);
        row.querySelector(".bg-cyan-400").style.width = percent(value);
        wrapper.append(row);
      });
      return wrapper;
    }

    function renderAnswers(decision) {
      answers.replaceChildren();
      Object.entries(decision.answers).forEach(([id, answer]) => {
        const card = document.createElement("article");
        card.className = "rounded-xl border border-slate-700 bg-slate-950/60 p-4";
        const title = document.createElement("p");
        title.className = "text-sm font-semibold text-slate-100";
        title.textContent = id;
        const summary = document.createElement("p");
        summary.className = "mt-1 text-sm text-cyan-300";
        if (answer.type === "noul") {
          summary.textContent = `Yes probability: ${percent(answer.noul)}`;
          card.append(title, summary, probabilityRows({ Yes: answer.noul, No: 1 - answer.noul }));
        } else if (answer.type === "choice") {
          summary.textContent = `Selected: ${answer.choice} · Confidence: ${percent(answer.confidence)}`;
          card.append(title, summary, probabilityRows(answer.probabilities));
        } else {
          summary.textContent = `Score: ${answer.score.toFixed(2)} · Confidence: ${percent(answer.confidence)}`;
          card.append(title, summary, probabilityRows(answer.probabilities));
        }
        answers.append(card);
      });
    }

    document.querySelector("#add-question").addEventListener("click", () => addQuestion());
    questions.addEventListener("change", (event) => {
      if (event.target.matches('[data-field="type"]')) renderCriteria(event.target.closest(".question"));
    });
    questions.addEventListener("click", (event) => {
      const card = event.target.closest(".question");
      if (!card) return;
      if (event.target.matches('[data-action="remove-question"]')) card.remove();
      if (event.target.matches('[data-action="add-option"]')) card.querySelector("[data-options]").insertAdjacentHTML("beforeend", optionRow());
      if (event.target.matches('[data-action="add-level"]')) card.querySelector("[data-levels]").insertAdjacentHTML("beforeend", levelRow());
      if (event.target.matches('[data-action="remove-option"]')) event.target.closest("[data-option]").remove();
      if (event.target.matches('[data-action="remove-level"]')) event.target.closest("[data-level]").remove();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.classList.add("hidden");
      try {
        const stateValue = state.value.trim();
        if (!stateValue) throw new Error("State is required.");
        const entries = [...questions.querySelectorAll(".question")].map(collectQuestion);
        const questionMap = Object.fromEntries(entries);
        if (!entries.length || Object.keys(questionMap).length !== entries.length) throw new Error("Add at least one question and use unique question IDs.");
        submit.disabled = true;
        status.textContent = "Deciding...";
        status.className = "rounded-full bg-cyan-400/20 px-3 py-1 text-xs font-medium text-cyan-200";
        const startedAt = performance.now();
        const response = await fetch("/decide", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: stateValue, questions: JSON.stringify(questionMap) }) });
        const data = await response.json();
        const roundTripMs = performance.now() - startedAt;
        if (!response.ok) throw new Error(data.error || "Decision request failed.");
        metrics.replaceChildren();
        [["Ollama decision", `${data.metrics.ollama_duration_ms} ms`], ["Round trip", `${roundTripMs.toFixed(0)} ms`], ["Input tokens", data.decision.usage.input_tokens], ["Output tokens", data.decision.usage.output_tokens]].forEach(([label, value]) => {
          const metric = document.createElement("div");
          metric.className = "rounded-lg bg-slate-950 p-3";
          metric.innerHTML = `<p class="text-xs text-slate-500"></p><p class="mt-1 text-lg font-semibold text-slate-100"></p>`;
          metric.querySelectorAll("p")[0].textContent = label;
          metric.querySelectorAll("p")[1].textContent = value;
          metrics.append(metric);
        });
        metrics.classList.remove("hidden");
        metrics.classList.add("grid");
        renderAnswers(data.decision);
        debug.textContent = JSON.stringify(
          { request: data.request, response: data.decision },
          null,
          2,
        );
        status.textContent = "Complete";
        status.className = "rounded-full bg-emerald-400/20 px-3 py-1 text-xs font-medium text-emerald-200";
      } catch (exception) {
        error.textContent = exception.message;
        error.classList.remove("hidden");
        status.textContent = "Needs attention";
        status.className = "rounded-full bg-rose-400/20 px-3 py-1 text-xs font-medium text-rose-200";
      } finally {
        submit.disabled = false;
      }
    });

    addQuestion({ id: "urgent", type: "noul", instructions: "Is this request urgent?" });
  </script>
</body>
</html>"""


class ClefHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content = PAGE.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != "/decide":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers["Content-Length"])
            data = json.loads(self.rfile.read(length))
            state = data["state"].strip()
            questions = json.loads(data["questions"])
            if not state:
                raise ValueError("State is required.")
            if not isinstance(questions, dict) or not questions:
                raise ValueError("Questions must be a non-empty JSON object.")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return

        try:
            state = json.loads(state)
        except json.JSONDecodeError:
            pass

        ollama_payload = {
            "model": OLLAMA_MODEL,
            "state": state,
            "questions": questions,
        }
        request = Request(
            f"{OLLAMA_HOST}/v1/systemone",
            data=json.dumps(ollama_payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            started_at = time.monotonic()
            with urlopen(request, timeout=300) as response:
                decision = json.load(response)
            ollama_duration_ms = round((time.monotonic() - started_at) * 1000)
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as error:
            self.respond_json(
                HTTPStatus.BAD_GATEWAY, {"error": f"Ollama request failed: {error}"}
            )
            return

        self.respond_json(
            HTTPStatus.OK,
            {
                "request": ollama_payload,
                "decision": decision,
                "metrics": {"ollama_duration_ms": ollama_duration_ms},
            },
        )

    def respond_json(self, status, data):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), ClefHandler).serve_forever()
