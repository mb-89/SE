// The browser half of `scripts/deck_look.py look`: it opens one built page in headless Chromium through
// Playwright, at each view the request names, visits each chapter and prints what it measured as one JSON
// line. It judges nothing: scripts/deck_look.py's docstring owns the findings and the measurement fields,
// and its `judge` reads them.
//
// Request (argv[2], JSON): {url, views: [{name, width, height, theme}], declared: [capability], shots: dir|null}.
// Reply (stdout): {views: [<view>]}, or {skip: reason} where Playwright or its browser is missing.
//
// Chapters: an obs-html page's navigation chapters, each opened with obsArtifact.activateChapter; otherwise
// every [data-chapter] element, else every <section>, else the body as one chapter called "page". The page
// runs beside a stand-in for the Claude app's runtime (`claude.use`), as in the app: a declared capability
// resolves to a namespace whose calls do nothing, any other rejects with code `not_granted`, and each
// request is recorded with the chapter open at the time.
"use strict";

let chromium;
try {
    ({chromium} = require("playwright"));
} catch (error) {
    console.log(JSON.stringify({skip: "node has no playwright"}));
    process.exit(0);
}

const request = JSON.parse(process.argv[2]);

// Runs in the page before any of its scripts: the stand-in runtime and the request log.
const runtime = declared => {
    const log = globalThis.__deckLook = {requests: [], chapter: "page"};
    const namespace = new Proxy({}, {get: () => async () => ({})});
    globalThis.claude = {
        use: async name => {
            log.requests.push({capability: String(name), chapter: log.chapter});
            if (declared.includes(name)) return namespace;
            throw Object.assign(new Error("not_granted"), {code: "not_granted"});
        },
    };
};

// Runs in the page: the chapters to visit, each {name, obs}.
const chapters = () => {
    const artifact = globalThis.obsArtifact;
    if (typeof artifact?.navigationChapters === "function" && typeof artifact.activateChapter === "function") {
        return artifact.navigationChapters().map(chapter => ({name: chapter.slug, obs: true}));
    }
    const marked = [...document.querySelectorAll("[data-chapter]")];
    const found = marked.length ? marked : [...document.querySelectorAll("section")];
    if (!found.length) return [{name: "page", obs: false}];
    return found.map((element, index) => ({
        name: element.dataset.chapter || element.id || `section ${index + 1}`, obs: false,
    }));
};

// Runs in the page: opens one chapter, waits until its DOM is quiet and returns its measurements.
const measure = async ({name, obs, index}) => {
    globalThis.__deckLook.chapter = name;
    const settle = () => new Promise(resolve => {
        let timer;
        const quiet = () => { observer.disconnect(); clearTimeout(limit); resolve(); };
        const observer = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(quiet, 150); });
        observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
        const limit = setTimeout(quiet, 3000);
        timer = setTimeout(quiet, 150);
    });
    let root;
    if (obs) {
        await Promise.resolve(globalThis.obsArtifact.activateChapter(name));
        root = document.querySelector(`[data-chapter="${CSS.escape(name)}"]`) || document.body;
    } else {
        const marked = [...document.querySelectorAll("[data-chapter]")];
        const found = marked.length ? marked : [...document.querySelectorAll("section")];
        root = found[index] || document.body;
        root.scrollIntoView({block: "start"});
    }
    await settle();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    const describe = element => {
        let label = element.tagName.toLowerCase();
        if (element.id) label += `#${element.id}`;
        else if (typeof element.className === "string" && element.className.trim()) {
            label += `.${element.className.trim().split(/\s+/)[0]}`;
        }
        const text = (element.innerText || element.textContent || "").trim().replace(/\s+/g, " ");
        return text ? `${label} "${text.length > 40 ? `${text.slice(0, 40)}…` : text}"` : label;
    };
    const ownText = element => [...element.childNodes].some(node => node.nodeType === 3 && node.textContent.trim());
    const MEDIA = "img, svg, canvas, video, picture, iframe";
    const FIGURES = "figure, img, svg, canvas, video, [data-artifact-figure]";
    // What the reader can see of an element: its box cut to every ancestor that clips its overflow
    // (a collapsed section is a box of no height that clips its content away), or null.
    const shown = (element, clip) => {
        if (element.checkVisibility && !element.checkVisibility({checkVisibilityCSS: true})) return null;
        const box = element.getBoundingClientRect();
        const cut = {left: Math.max(box.left, clip.left), right: Math.min(box.right, clip.right),
                     top: Math.max(box.top, clip.top), bottom: Math.min(box.bottom, clip.bottom)};
        return cut.right - cut.left > 0 && cut.bottom - cut.top > 0 ? cut : null;
    };
    const visible = element => shown(element, EVERYWHERE) !== null;
    const EVERYWHERE = {left: -Infinity, right: Infinity, top: -Infinity, bottom: Infinity};

    const positions = new Map();
    const elements = [];
    // `scroller`: an ancestor handles sideways overflow itself (it scrolls or clips), so the page does not.
    const walk = (element, parent, scroller, clip) => {
        const style = getComputedStyle(element);
        if (style.display === "contents") {
            for (const child of element.children) walk(child, parent, scroller, clip);
            return;
        }
        const box = shown(element, clip);
        if (!box) return;
        const entry = {
            name: describe(element), parent, scroller, ...box,
            clip_x: /hidden|clip/.test(style.overflowX), clip_y: /hidden|clip/.test(style.overflowY),
            scroll_width: element.scrollWidth, client_width: element.clientWidth,
            scroll_height: element.scrollHeight, client_height: element.clientHeight,
            text: ownText(element),
        };
        positions.set(element, elements.length);
        elements.push(entry);
        const own = element.getBoundingClientRect();
        const clipsX = style.overflowX !== "visible";
        const clipsY = style.overflowY !== "visible";
        const inner = {
            left: clipsX ? Math.max(clip.left, own.left) : clip.left, right: clipsX ? Math.min(clip.right, own.right) : clip.right,
            top: clipsY ? Math.max(clip.top, own.top) : clip.top, bottom: clipsY ? Math.min(clip.bottom, own.bottom) : clip.bottom,
        };
        for (const child of element.children) walk(child, positions.get(element), scroller || clipsX, inner);
    };
    walk(root, -1, false, EVERYWHERE);

    // The outermost figures the reader is shown: rendered, inside what the walk saw (a figure of no
    // size is one of the findings, so its own size does not hide it).
    const outer = [...root.querySelectorAll(FIGURES)].filter(figure => !figure.parentElement.closest(FIGURES)
        && figure.getClientRects().length && positions.has(figure.parentElement));
    const figures = outer.map(figure => {
        const box = figure.getBoundingClientRect();
        const media = [figure, ...figure.querySelectorAll(MEDIA)].filter(item => item.matches(MEDIA) && visible(item));
        return {
            name: describe(figure), width: box.width, height: box.height,
            text: (figure.innerText || "").trim().length, media: media.length,
            broken: media.some(item => item.tagName === "IMG" && (!item.complete || item.naturalWidth === 0)),
        };
    });
    return {
        name, text: (root.innerText || "").trim().length,
        media: [...root.querySelectorAll(MEDIA)].filter(visible).length,
        height: root.getBoundingClientRect().height, elements, figures,
        scroll_width: document.documentElement.scrollWidth,
    };
};

(async () => {
    let browser;
    try {
        browser = await chromium.launch();
    } catch (error) {
        console.log(JSON.stringify({skip: `playwright has no browser to launch (${String(error.message).split("\n")[0]})`}));
        return;
    }
    const path = require("path");
    try {
        const views = [];
        for (const view of request.views) {
            const context = await browser.newContext({
                viewport: {width: view.width, height: view.height}, colorScheme: view.theme,
            });
            await context.addInitScript(runtime, request.declared);
            const page = await context.newPage();
            const errors = [];
            let current = "page";
            page.on("pageerror", error => errors.push({message: String(error.message).split("\n")[0], chapter: current}));
            await page.goto(request.url);
            // A page that themes itself by data-theme (obs-html, the artifact convention) follows the view's scheme.
            await page.evaluate(theme => {
                if (document.documentElement.hasAttribute("data-theme")) document.documentElement.dataset.theme = theme;
            }, view.theme);
            await page.waitForFunction(() => !("artifactStatus" in document.documentElement.dataset) ||
                document.documentElement.dataset.artifactStatus === "ready", null, {timeout: 15000}).catch(() => {});
            const visited = [];
            const list = await page.evaluate(chapters);
            for (const [index, chapter] of list.entries()) {
                current = chapter.name;
                visited.push(await page.evaluate(measure, {...chapter, index}));
                if (request.shots && view.theme === "light") {
                    const file = path.join(request.shots, `${chapter.name.replace(/[^\w.-]+/g, "_")}-${view.name}.png`);
                    if (chapter.obs || list.length === 1) await page.screenshot({path: file, fullPage: true});
                    else {
                        const marked = page.locator("[data-chapter]");
                        const roots = (await marked.count()) ? marked : page.locator("section");
                        await roots.nth(index).screenshot({path: file});
                    }
                }
            }
            const requests = await page.evaluate(() => globalThis.__deckLook.requests);
            views.push({...view, chapters: visited, errors, requests});
            await context.close();
        }
        console.log(JSON.stringify({views}));
    } finally {
        await browser.close();
    }
})().catch(error => {
    console.error(String((error && error.stack) || error));
    process.exit(2);
});
