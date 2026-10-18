// Presentation mode, for screenshots, the film and a projector: the striped ribbon becomes a small
// "simulated demo data" badge in the top bar, the Demo button hides, and small text grows.
// Turn it on with ?present=1 (off with ?present=0), Shift+P, or the switch in the Demo drawer.

const KEY = "jalsakhi.present";

export function isPresenting(): boolean {
  return document.documentElement.classList.contains("present");
}

export function setPresenting(on: boolean) {
  document.documentElement.classList.toggle("present", on);
  try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* private window: this page only */ }
  window.dispatchEvent(new Event("jalsakhi:present"));
}

export function initPresentation() {
  const q = new URLSearchParams(window.location.search).get("present");
  let on = false;
  try { on = (q ?? localStorage.getItem(KEY)) === "1"; } catch { on = q === "1"; }
  setPresenting(on);
  window.addEventListener("keydown", (e) => {
    const t = e.target as HTMLElement;
    if (e.shiftKey && (e.key === "P" || e.key === "p") && !e.ctrlKey && !e.metaKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) && !t.isContentEditable) {
      setPresenting(!isPresenting());
    }
  });
}
