// se's trusted answers bundle for a decision deck: `scripts/deck.py build` embeds it in every deck
// (obs-html's --trusted-runtime-bundle). It registers obs-html's answers sink `obsHtml.answers` whenever it
// runs and looks for the Claude app's runtime (`claude.use`) only at Send, so a runtime that appears after
// the bundle's first run still takes the answers. scripts/deck.py's docstring owns the capabilities a deck
// is published with, the decision skill (src/skills/decision/SKILL.md) how the session reads what arrives.
//
// At Send, in the Claude app, the answers leave two ways, started in this order and both awaited:
//   (a) `answers.json` through the `artifact` capability's files form: the record the session reads;
//   (b) a comment to Claude through the `comments` capability's `sendToClaude`, anchored to the page:
//       each decision's verdict and comment, which wakes the watching session even where (a) is refused.
// (b) starts without waiting for (a), since sendToClaude needs the person's recent gesture. Send succeeds
// when either way does; the result names each way and the error code of each that failed. Where neither
// does, it rejects, so obs-html shows the answers as text, and a notice beside Send says so with the codes.
// Without the Claude app it posts to obs-html serve where that served the page, else it rejects with
// "sending is not available here" and obs-html shows the text to copy.
//
// Nothing is lost on a reload: every change of a verdict or comment is kept in sessionStorage per chapter
// version, and a chapter's draft comes back when the person opens that chapter again.
(root => {
    "use strict";
    const artifact = root.obsArtifact;
    const document = root.document;
    artifact.registerApplication({id: "se-answers", actions: []});

    let data = {};
    try { data = JSON.parse(document.querySelector("[data-artifact-data]")?.textContent || "{}"); } catch { data = {}; }
    const asking = new Map((data.notes || []).filter(note => note.bless && !note.bless.answer)
        .map(note => [note.slug, {version: note.bless.version, title: note.title || note.slug}]));
    const deckTitle = data.document?.title ?? document.title;

    // The draft: chapter -> {version, verdict, comment, pick}, this tab only (sessionStorage).
    const DRAFT = `se-answers-draft:${deckTitle}`;
    const readDraft = () => {
        try { return JSON.parse(root.sessionStorage.getItem(DRAFT) || "{}") || {}; } catch { return {}; }
    };
    const touched = new Set();  // Chapters whose verdict in obsBless is the draft's truth in this load.
    let restoring = false;
    const saveDraft = () => {
        const bless = root.obsBless;
        if (!bless || restoring) return;
        const verdicts = bless.verdicts(), draft = readDraft();
        for (const slug of touched) {
            const verdict = verdicts[slug];
            if (verdict?.verdict && asking.has(slug)) {
                draft[slug] = {version: asking.get(slug).version, verdict: verdict.verdict,
                    ...(verdict.comment ? {comment: verdict.comment} : {}), ...(verdict.pick ? {pick: verdict.pick} : {})};
            } else delete draft[slug];
        }
        try { root.sessionStorage.setItem(DRAFT, JSON.stringify(draft)); } catch { /* No storage here: nothing to keep. */ }
    };
    const activeSlug = () => document.querySelector("[data-active-chapter]")?.dataset.chapter;
    // Bring back the active chapter's draft through obs-html's own controls (bless.js), once per load.
    const restore = slug => {
        const bless = root.obsBless;
        if (!bless || !asking.has(slug) || touched.has(slug)) return;
        touched.add(slug);
        const saved = readDraft()[slug];
        if (!saved || saved.version !== asking.get(slug).version || bless.verdicts()[slug]) return;
        restoring = true;
        try {
            if (saved.verdict === "pick" && saved.pick) bless.pick(saved.pick.figure, saved.pick.option);
            else document.querySelector(`[data-bless-key="${saved.verdict}"]`)?.click();
            const comment = document.querySelector("[data-bless-comment]");
            if (saved.comment && comment) {
                comment.value = saved.comment;
                comment.dispatchEvent(new root.Event("input", {bubbles: true}));
                comment.dispatchEvent(new root.KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
                comment.blur();
            }
        } finally {
            restoring = false;
        }
    };
    document.addEventListener("obs-chapter-change", ({detail}) => restore(detail?.slug));
    document.addEventListener("obs-bless-change", ({detail}) => {
        if (detail?.chapter) touched.add(detail.chapter);
        saveDraft();
        warm();
    });
    document.addEventListener("input", event => {
        if (!event.target?.matches?.("[data-bless-comment]")) return;
        const slug = activeSlug();
        if (slug) touched.add(slug);
        saveDraft();
    });
    Promise.resolve(artifact.whenChapterReady?.()).then(() => restore(activeSlug()), () => {});

    // The Claude app's runtime, looked up now: it may appear after this bundle first ran.
    const claude = () => (typeof root.claude?.use === "function" ? root.claude : null);
    // Resolve the namespaces once the person starts deciding, so Send loses no time (use() is memoized).
    const warm = () => {
        const runtime = claude();
        if (runtime) for (const name of ["artifact", "comments"]) Promise.resolve(runtime.use(name)).catch(() => {});
    };
    const code = error => error?.code || error?.name || "error";
    const describe = error => `${code(error)}${error?.message && error.message !== code(error) ? ` (${error.message})` : ""}`;

    // The comment to Claude: a short line per decision, then the payload itself where it fits.
    const LIMIT = 4096;  // The comments capability's text bound, UTF-8 bytes.
    const bytes = text => new TextEncoder().encode(text).length;
    const clean = text => String(text).replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, " ");
    const commentText = payload => {
        const lines = [`Answers from the decision deck "${deckTitle}" (se-answers):`];
        for (const item of payload.verdicts || []) {
            const pick = item.pick ? ` ${item.pick.option === "none" ? "none of the above" : item.pick.option}` : "";
            lines.push(`- ${item.chapter}: ${item.verdict}${pick}${item.comment ? `: ${item.comment}` : ""}`);
        }
        lines.push("The full payload is answers.json in this artifact where it could be saved.");
        let text = clean(lines.join("\n"));
        const full = `${text}\n\nanswers.json:\n${JSON.stringify(payload)}`;
        if (bytes(clean(full)) <= LIMIT) return clean(full);
        while (bytes(text) > LIMIT) text = `${text.slice(0, -2)}…`;
        return text;
    };

    const viaFiles = async (runtime, payload) => {
        const files = await runtime.use("artifact");
        if (!files) throw Object.assign(new Error("the artifact capability is not granted to this view"), {code: "not_granted"});
        const result = await files.publish({"answers.json": `${JSON.stringify(payload, null, 2)}\n`});
        return {version: result?.version};
    };
    const viaComment = async (runtime, payload) => {
        const comments = await runtime.use("comments");
        if (!comments) throw Object.assign(new Error("the comments capability is not granted to this view"), {code: "not_granted"});
        const target = document.querySelector("[data-bless]") || document.body;
        const anchor = await comments.anchorFor(target);
        const result = await comments.sendToClaude({anchor, text: commentText(payload)});
        return {threadId: result?.threadId};
    };

    // Where obs-html serve served the page: its own address (obs-html answers.js decides).
    const viaServer = async (address, payload) => {
        let response;
        try {
            response = await root.fetch(address, {method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload, null, 2)});
        } catch (error) {
            throw new Error(`obs-html serve cannot be reached (${error?.message || error}); start it again and open its URL`);
        }
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(`obs-html serve refused the answers with HTTP ${response.status}: ${body.error || ""}`);
        return {ways: ["server"], written: body.written};
    };

    // The notice beside Send: what happened, in plain words; on a failure the answers to copy.
    const notice = (message, text) => {
        const send = document.querySelector("[data-bless-send]");
        let box = document.querySelector("[data-se-answers-notice]");
        if (!box) {
            box = document.createElement("div");
            box.dataset.seAnswersNotice = "";
            box.setAttribute("role", "status");
            box.style.cssText = "flex-basis:100%;max-width:100%;font-size:.85em;white-space:normal";
            if (send) send.after(box); else document.body.prepend(box);
        }
        const line = document.createElement("p");
        line.textContent = message;
        const parts = [line];
        if (text) {
            const answers = document.createElement("textarea");
            answers.readOnly = true;
            answers.rows = 4;
            answers.style.cssText = "width:100%;box-sizing:border-box;font:inherit";
            answers.value = text;
            answers.dataset.seAnswersText = "";
            answers.addEventListener("focus", () => answers.select());
            parts.push(answers);
        }
        box.dataset.seAnswersNotice = text ? "failed" : "sent";
        box.replaceChildren(...parts);
    };

    artifact.trustedExtension("obsHtml.answers").register({
        id: "claude-artifact",
        send: async payload => {
            saveDraft();
            const runtime = claude();
            if (!runtime) {
                const address = root.ObsHtmlAnswers?.server?.();
                if (address) return await viaServer(address, payload);
                throw new Error("sending is not available here: this view has no Claude app runtime and was not " +
                    "opened through obs-html serve. Copy the answers and hand them over");
            }
            const files = viaFiles(runtime, payload);
            const comment = viaComment(runtime, payload);
            const [saved, sent] = await Promise.allSettled([files, comment]);
            const ways = [...(saved.status === "fulfilled" ? ["answers.json"] : []),
                ...(sent.status === "fulfilled" ? ["comment"] : [])];
            const failed = {...(saved.status === "rejected" ? {"answers.json": code(saved.reason)} : {}),
                ...(sent.status === "rejected" ? {comment: code(sent.reason)} : {})};
            if (!ways.length) {
                const why = `saving answers.json failed with ${describe(saved.reason)}; ` +
                    `the comment to Claude failed with ${describe(sent.reason)}`;
                notice(`Not sent: ${why}. Your answers are kept on this page. Copy them below and paste them ` +
                    "into the chat.", JSON.stringify(payload, null, 2));
                throw Object.assign(new Error(`not sent: ${why}`), {code: "not_sent", failed});
            }
            notice(`Sent: ${ways.map(way => (way === "answers.json" ? "answers.json saved" : "comment sent to Claude"))
                .join(" and ")}.${Object.keys(failed).length
                ? ` Not ${Object.keys(failed)[0] === "comment" ? "sent as a comment" : "saved as answers.json"} ` +
                  `(${Object.values(failed)[0]}).` : ""}`);
            return {ways, failed, ...(saved.status === "fulfilled" ? {written: "answers.json", version: saved.value.version} : {}),
                ...(sent.status === "fulfilled" ? {comment: sent.value} : {})};
        },
    });
})(globalThis);
