// se's trusted answers bundle for a decision deck: `scripts/deck.py build` embeds it in every deck
// (obs-html's --trusted-runtime-bundle). It sends the answers through the adapter of the host the deck was
// built for, `globalThis.seDeck.host` (deck.py's `--host`, HOSTS there), one adapter per host (ADAPTERS):
//
//   claude-app   the Claude app (cloud and mobile): the Claude app's runtime (`claude.use`) first, then
//                obs-html serve where that served the page; its sink's name is "Claude".
//   claude-code  Claude Code on the person's machine: obs-html serve first, then the Claude app's runtime
//                where the deck was published there after all; its sink's name is "Claude Code".
//   copilot      GitHub Copilot in VS Code: obs-html serve, which writes answers.json beside the deck for
//                the session to read; its sink's name is "Copilot".
//   local        any other host: no sink of its own, so obs-html's own sinks take the answers (its server
//                where it served the page, else the text to copy), as obs's answers contract asks of a
//                host's bundle where its host is not present.
//
// A deck whose data names no host is the Claude app's (decks built before the host was written); one that
// names a host the bundle does not know registers no sink and says so on the console. The adapter registers
// obs-html's answers sink `obsHtml.answers` when the bundle first runs and looks for the Claude app's
// runtime only at Send, so a runtime that appears after the bundle's first run still takes the answers.
// scripts/deck.py's docstring owns the capabilities a deck is published with, the decision skill
// (src/skills/decision/SKILL.md) how the session reads what arrives.
//
// Through the Claude app's runtime the answers leave two ways, one after the other:
//   (b) first, a comment to Claude through the `comments` capability's `sendToClaude`, anchored to the page:
//       each decision's verdict (or "comment" where it has none) and comment, which wakes the watching
//       session. It is sent only where `canSendToClaude()` answers "available"; another answer is its
//       failure's code. It goes first and alone, since it needs the person's recent gesture, and its
//       consent prompt must not compete with the publish's (on 24 Nov, started together, the comment
//       failed while answers.json was saved, and its code reached the console alone);
//   (a) then `answers.json` through the `artifact` capability's files form: the record the session reads,
//       saved even where (b) failed.
// Send succeeds when either way does; the result names each way and the error code of each that failed. Where neither the
// runtime nor obs-html serve is there, the adapter rejects with a message naming its host ("sending is not
// available here") and obs-html shows the text to copy.
//
// Telling the reader is obs-html's notice center's (obs's adapters/html/spec/capabilities/answers.md,
// Contract): this bundle draws nothing on the page. The sink's name is the adapter's, so on a confirmed send
// obs's entry says "1 verdict and 2 comments sent to Copilot." and its passing line, which deck.py turns on,
// "Sent to Copilot."; where obs-html serve served a Claude app deck (`ObsHtmlAnswers.server()` gives its
// address when this bundle first runs) the sink gives no name, as the answers go to whichever session
// serves the deck, and both say "sent." alone. A send where only one way worked posts one warning entry of
// its own, `se-answers-partly`, in plain words, revealed where the message to Claude failed, as the reader
// may have a step to take; a later send where both work, or where both fail, removes it. Where both fail it
// rejects with code `not_sent` and `failed`, and a message to copy the answers and paste them into the chat,
// which reaches the browser console in obs's warning, while obs's error entries tell the reader in their own
// words, with the answers to copy. The codes go to the console, as one `se-answers:` warning.
//
// The deck's title, decisions and host come from `globalThis.seDeck`, which deck.py writes in front of this
// file (scripts/deck.py's `_bundle` owns its fields), never from obs-html's embedded page data.
//
// The drafts are obs-html's: it keeps each chapter's verdict, pick and comment in sessionStorage and
// restores them at load, until a sink confirms the send (obs's adapters/html/spec/capabilities/bless.md,
// Drafts). This bundle keeps and restores none: its store would be the same tab's sessionStorage, so no
// scope remains (a new tab, a webview) where it could restore what obs-html cannot. It only confirms a
// send by resolving, and rejects where nothing was sent, so the drafts stay.
(root => {
    "use strict";
    const artifact = root.obsArtifact;
    const document = root.document;
    artifact.registerApplication({id: "se-answers", actions: []});

    // The deck's own data, which `scripts/deck.py build` writes in front of this bundle: its title and its
    // decisions (the chapter ids with a pugh fence). Without it the bundle says so once and keeps working,
    // with the page's title and no decisions.
    const deck = root.seDeck;
    const readable = typeof deck?.title === "string" && Array.isArray(deck?.decisions) &&
        deck.decisions.every(id => typeof id === "string");
    if (!readable) {
        root.console?.warn("se-answers: this deck carries no readable deck data (globalThis.seDeck); " +
            "the comment to Claude names the page's title and lists no unanswered decisions. " +
            "Build the deck with scripts/deck.py build.");
    }
    const deckTitle = readable ? deck.title : document.title;
    const decisions = readable ? deck.decisions : [];

    document.addEventListener("obs-bless-change", () => warm());

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
            // An entry may carry a comment and no verdict (obs's answers schema): it reads "comment".
            lines.push(`- ${item.chapter}: ${item.verdict ?? "comment"}${pick}${item.comment ? `: ${item.comment}` : ""}`);
        }
        const answered = new Set((payload.verdicts || []).map(item => item.chapter));
        for (const id of decisions) if (!answered.has(id)) lines.push(`- ${id}: no answer`);
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
    // The comment to Claude: only where the shell says a session can take it (`canSendToClaude`), whose
    // answer other than "available" is the failure's code (writers_only, no_session, off).
    const viaComment = async (runtime, payload) => {
        const comments = await runtime.use("comments");
        if (!comments) throw Object.assign(new Error("the comments capability is not granted to this view"), {code: "not_granted"});
        if (typeof comments.canSendToClaude === "function") {
            const state = await comments.canSendToClaude();
            if (state !== "available") {
                throw Object.assign(new Error(`the shell cannot send to Claude here (${state})`), {code: String(state)});
            }
        }
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

    // The partial send's entry in obs-html's notice center, in plain words (no file, command, code or id).
    const PARTLY = "se-answers-partly";
    const notices = () => root.obsNotices;
    // Why the message to Claude did not go through, by its code, in the reader's words; none for another code.
    const REASONS = {
        no_session: "No Claude session is listening to this page right now.",
        writers_only: "Only an editor of this page can send a message to Claude from it.",
        off: "This view does not offer messages to Claude.",
        consent_required: "This page was not allowed to comment as you.",
        claude_unavailable: "Claude could not take the message just now.",
    };
    const partly = (failedWay, reason) => {
        if (failedWay === "comment") {
            const why = REASONS[reason] ? `${REASONS[reason]} ` : "";
            notices()?.post({id: PARTLY, severity: "warning", title: "No message to Claude",
                details: [`Your answers are saved with this page, where Claude reads them, but the message to ` +
                    `Claude did not go through. ${why}If Claude does not answer, say in the chat that you sent them.`]});
            notices()?.reveal(PARTLY);
        } else {
            notices()?.post({id: PARTLY, severity: "warning", title: "Not saved with the page",
                details: ["Claude got your answers as a message, but they could not be saved with this page."]});
        }
    };

    // Through the Claude app's runtime: the comment to Claude first, alone, while the person's gesture is fresh
    // and no other consent prompt competes with its own; then answers.json (the header's (b), then (a)).
    const settled = promise => promise.then(value => ({status: "fulfilled", value}), reason => ({status: "rejected", reason}));
    const viaClaude = async (runtime, payload) => {
        const sent = await settled(viaComment(runtime, payload));
        const saved = await settled(viaFiles(runtime, payload));
        const ways = [...(saved.status === "fulfilled" ? ["answers.json"] : []),
            ...(sent.status === "fulfilled" ? ["comment"] : [])];
        const failed = {...(saved.status === "rejected" ? {"answers.json": code(saved.reason)} : {}),
            ...(sent.status === "rejected" ? {comment: code(sent.reason)} : {})};
        if (!ways.length) {
            notices()?.remove(PARTLY);
            root.console?.warn(`se-answers: nothing was sent: saving answers.json failed with ${describe(saved.reason)}; ` +
                `the comment to Claude failed with ${describe(sent.reason)}`);
            throw Object.assign(new Error("nothing reached Claude; copy your answers and paste them into the chat"),
                {code: "not_sent", failed});
        }
        const [failedWay] = Object.keys(failed);
        if (failedWay) {
            root.console?.warn(`se-answers: sent, but ${failedWay === "comment" ? "the comment to Claude" : "saving answers.json"} ` +
                `failed with ${describe(failedWay === "comment" ? sent.reason : saved.reason)}`);
            partly(failedWay, failed[failedWay]);
        } else {
            notices()?.remove(PARTLY);
        }
        return {ways, failed, ...(saved.status === "fulfilled" ? {written: "answers.json", version: saved.value.version} : {}),
            ...(sent.status === "fulfilled" ? {comment: sent.value} : {})};
    };

    // Where neither way is there: the adapter's host named, so the reader is never told of another host.
    const unavailable = (host, how) => new Error(`sending is not available here: this view ${how}, so nothing ` +
        `reached ${host}. Copy the answers and hand them over`);
    const address = () => root.ObsHtmlAnswers?.server?.();
    // Where obs-html serve served the page: its address, given from the bundle's first run.
    const served = Boolean(address());

    // One adapter per host (the header's table): its sink's id, its name in the reader's words, and its send.
    const ADAPTERS = {
        "claude-app": {
            id: "claude-artifact",
            // Where obs-html serve served the page, the answers go to whichever session serves it, so the
            // sink names no reader.
            name: served ? null : "Claude",
            send: async payload => {
                const runtime = claude();
                if (runtime) return await viaClaude(runtime, payload);
                if (address()) return await viaServer(address(), payload);
                throw unavailable("Claude", "has no Claude app runtime and was not opened through obs-html serve");
            },
        },
        "claude-code": {
            id: "claude-code",
            name: "Claude Code",
            send: async payload => {
                if (address()) return await viaServer(address(), payload);
                const runtime = claude();
                if (runtime) return await viaClaude(runtime, payload);
                throw unavailable("Claude Code", "was not opened through deck.py serve");
            },
        },
        "copilot": {
            id: "copilot",
            name: "Copilot",
            send: async payload => {
                if (address()) return await viaServer(address(), payload);
                throw unavailable("Copilot", "was not opened through deck.py serve");
            },
        },
        // No sink: obs-html's own take the answers.
        "local": null,
    };
    const host = readable && typeof deck.host === "string" ? deck.host : "claude-app";
    if (!Object.hasOwn(ADAPTERS, host)) {
        root.console?.warn(`se-answers: this deck names the host "${host}", which has no adapter here ` +
            `(${Object.keys(ADAPTERS).join(", ")}); obs-html's own sinks take the answers. Build it with ` +
            "scripts/deck.py build --host.");
    }
    const adapter = ADAPTERS[host];
    if (adapter) {
        artifact.trustedExtension("obsHtml.answers").register({
            id: adapter.id, ...(adapter.name ? {name: adapter.name} : {}), send: adapter.send});
    }
})(globalThis);
