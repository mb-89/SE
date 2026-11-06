// se's trusted answers bundle for a decision deck: `scripts/deck.py build` embeds it in every deck
// (obs-html's --trusted-runtime-bundle). Opened in the Claude app, it registers obs-html's answers sink
// `obsHtml.answers` and saves the payload as answers.json through the artifact runtime's files form, so
// the new version wakes the session that published the deck. Elsewhere it registers no sink, and obs-html's
// own sinks (`obs-html serve`, else the text to copy) take the answers.
(root => {
    "use strict";
    const artifact = root.obsArtifact;
    artifact.registerApplication({id: "se-answers", actions: []});
    if (typeof root.claude?.use !== "function") return;
    artifact.trustedExtension("obsHtml.answers").register({
        id: "claude-artifact",
        send: async payload => {
            const runtime = await root.claude.use("artifact");
            if (!runtime) {
                throw new Error("the Claude artifact runtime is not available in this view; " +
                    "publish the deck with the artifact capability");
            }
            const result = await runtime.publish({"answers.json": `${JSON.stringify(payload, null, 2)}\n`});
            return {written: "answers.json", version: result.version};
        },
    });
})(globalThis);
