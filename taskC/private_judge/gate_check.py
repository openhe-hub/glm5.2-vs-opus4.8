#!/usr/bin/env python3
# Objective auto-gate for Task C (40 pts). Pairs with Lighthouse + axe.
# Requires: pip install playwright && playwright install chromium
# Usage: python3 gate_check.py <url_or_file> [--js-budget-kb 30]
import sys, json, gzip, argparse, pathlib, re
from playwright.sync_api import sync_playwright

BREAKPOINTS = [(320, 720), (768, 1024), (1024, 768), (1440, 900)]
STATES = ["default","hover","focus","active","disabled","loading","empty","error"]

def gzip_kb(text: str) -> float:
    return len(gzip.compress(text.encode())) / 1024.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target"); ap.add_argument("--js-budget-kb", type=float, default=30.0)
    a = ap.parse_args()
    url = a.target if a.target.startswith("http") else pathlib.Path(a.target).resolve().as_uri()
    result = {"overflow":{}, "console_errors":[], "js_kb":None, "focus_visible":False,
              "reduced_motion_ok":None, "prefers_dark_ok":None, "score":0, "notes":[]}
    with sync_playwright() as p:
        browser = p.chromium.launch(); ctx = browser.new_context(); page = ctx.new_page()
        js_bytes = {"n":0}
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "javascript" in ct or resp.url.endswith(".js"):
                    js_bytes["n"] += len(gzip.compress(resp.body()))
            except Exception: pass
        page.on("response", on_response)
        page.on("console", lambda m: result["console_errors"].append(m.text) if m.type=="error" else None)
        page.goto(url, wait_until="networkidle")
        inline = page.eval_on_selector_all("script:not([src])","els => els.map(e=>e.textContent).join('')")
        result["js_kb"] = round(js_bytes["n"]/1024.0 + gzip_kb(inline or ""), 1)
        for w,h in BREAKPOINTS:
            page.set_viewport_size({"width":w,"height":h}); page.wait_for_timeout(150)
            sw = page.evaluate("document.documentElement.scrollWidth")
            result["overflow"][f"{w}x{h}"] = {"scrollWidth":sw, "ok": sw <= w+1}
        result["focus_visible"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.selectorText&&r.selectorText.includes(':focus-visible'))return true;}catch(e){}}return false;}"""))
        result["reduced_motion_ok"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.media&&String(r.media.mediaText).includes('prefers-reduced-motion'))return true;}catch(e){}}return false;}"""))
        result["prefers_dark_ok"] = bool(page.evaluate("""()=>{for(const s of document.styleSheets){try{for(const r of s.cssRules)if(r.media&&String(r.media.mediaText).includes('prefers-color-scheme'))return true;}catch(e){}}return false;}"""))
        out = pathlib.Path("gate_shots"); out.mkdir(exist_ok=True)
        page.set_viewport_size({"width":1440,"height":900}); page.screenshot(path=str(out/"desktop.png"), full_page=True)
        page.set_viewport_size({"width":390,"height":844});  page.screenshot(path=str(out/"mobile.png"),  full_page=True)
        browser.close()
    s=0; notes=result["notes"]
    if not result["console_errors"]: s+=5
    else: notes.append(f"{len(result['console_errors'])} console errors")
    ovf_ok = sum(1 for v in result["overflow"].values() if v["ok"]); s += round(8*ovf_ok/len(BREAKPOINTS))
    if ovf_ok < len(BREAKPOINTS): notes.append("horizontal overflow at some breakpoints")
    if result["js_kb"] is not None and result["js_kb"] <= a.js_budget_kb: s+=8
    else: notes.append(f"JS {result['js_kb']}KB > budget {a.js_budget_kb}KB")
    if result["focus_visible"]: s+=5
    else: notes.append("no :focus-visible")
    if result["reduced_motion_ok"]: s+=3
    else: notes.append("prefers-reduced-motion not handled")
    result["score_partial_of_29"]=s
    print(json.dumps(result, indent=2))
    print(f"\nObjective sub-score (excl. Lighthouse): {s}/29  (+11 from Lighthouse -> 40)")

if __name__ == "__main__": main()