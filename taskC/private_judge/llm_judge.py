#!/usr/bin/env python3
# Blind aesthetic LLM-judge for Task C, using an OpenAI model (e.g. GPT-5.5).
# Pairs with ONE human judge; final aesthetic = average of human + this LLM.
# Randomized A/B (kills order bias), anchored rubric, K trials, variance report.
#
# Requires: OPENAI_API_KEY in env ; pip install openai
# Usage: python3 llm_judge.py <dirX> <dirY> --labelX glm --labelY opus -k 8 --model gpt-5.5
#   each dir holds: desktop.png, mobile.png  (optionally states.png, interaction.png)
import os, sys, json, base64, random, argparse, statistics

DIMENSIONS = {"typography":12,"color":10,"layout":10,"originality":12,"motion":10,"polish":6}

RUBRIC = """You are a senior product designer judging two web submissions BLIND.
Score each on six dimensions. Use the FULL range; reserve top marks for top-studio work.
Penalize generic/templated output (default Tailwind/Bootstrap/shadcn look,
centered-hero + 3 cards, emoji icons, stock gradients).
Integers 0..MAX per dimension:
- typography 0..12  - color 0..10  - layout 0..10
- originality 0..12 (the OPPOSITE of templated defaults)
- motion 0..10  - polish 0..6
Originality anchors: 0-3 untouched UI kit; 4-7 competent-but-familiar SaaS;
8-10 clearly art-directed; 11-12 memorable, gallery-grade.
Return STRICT JSON only with this exact shape:
{"A":{"typography":int,"color":int,"layout":int,"originality":int,"motion":int,"polish":int,"note":"<=20 words"},
 "B":{"typography":int,"color":int,"layout":int,"originality":int,"motion":int,"polish":int,"note":"<=20 words"}}"""

def data_url(path):
    with open(path,"rb") as f: b=base64.standard_b64encode(f.read()).decode()
    ext = "png" if path.lower().endswith("png") else "jpeg"
    return f"data:image/{ext};base64,{b}"

def collect(d):
    blocks=[]
    for fn in ("desktop.png","mobile.png","states.png","interaction.png"):
        p=os.path.join(d,fn)
        if os.path.exists(p):
            blocks.append({"type":"text","text":f"[{fn}]"})
            blocks.append({"type":"image_url","image_url":{"url":data_url(p)}})
    return blocks

def call_judge(dirA, dirB, model):
    # ISOLATED side-effecting call. Returns parsed dict {"A":{...},"B":{...}}.
    from openai import OpenAI
    client = OpenAI()
    content = [{"type":"text","text":RUBRIC},
               {"type":"text","text":"=== SUBMISSION A ==="}, *collect(dirA),
               {"type":"text","text":"=== SUBMISSION B ==="}, *collect(dirB)]
    # GPT-5 family uses max_completion_tokens; json_object mode makes parsing robust.
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":content}],
        max_completion_tokens=700,
        response_format={"type":"json_object"})
    return json.loads(resp.choices[0].message.content)

def aggregate(trials, labelX, labelY):
    out={}
    for label, side in ((labelX,"X"),(labelY,"Y")):
        out[label]={}
        for dim in DIMENSIONS:
            vals=[t[side][dim] for t in trials]
            out[label][dim]=(round(statistics.mean(vals),2),
                             round(statistics.pstdev(vals),2) if len(vals)>1 else 0.0)
        totals=[sum(t[side][dim] for dim in DIMENSIONS) for t in trials]
        out[label]["TOTAL"]=(round(statistics.mean(totals),2),
                             round(statistics.pstdev(totals),2) if len(totals)>1 else 0.0)
    return out

def run(dirX, dirY, labelX, labelY, k, model):
    trials=[]
    for i in range(k):
        swap = random.random()<0.5
        dA,dB = (dirY,dirX) if swap else (dirX,dirY)
        res = call_judge(dA,dB,model)
        X = res["B"] if swap else res["A"]; Y = res["A"] if swap else res["B"]
        trials.append({"X":X,"Y":Y}); print(f"  trial {i+1}/{k} (swap={swap})")
    return aggregate(trials, labelX, labelY)

def combine_with_human(llm_total, human_total, cap=60, flag_at=12):
    # final aesthetic = equal-weight average of the two judges; flag big divergence
    final = round(0.5*llm_total + 0.5*human_total, 2)
    diverged = abs(llm_total - human_total) > flag_at
    return final, diverged

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("dirX"); ap.add_argument("dirY")
    ap.add_argument("--labelX",default="X"); ap.add_argument("--labelY",default="Y")
    ap.add_argument("-k",type=int,default=8)
    ap.add_argument("--model",default="gpt-5.5")  # set exact OpenAI model string
    ap.add_argument("--humanX",type=float,default=None, help="human /60 total for X")
    ap.add_argument("--humanY",type=float,default=None, help="human /60 total for Y")
    a=ap.parse_args()
    rep=run(a.dirX,a.dirY,a.labelX,a.labelY,a.k,a.model)
    print("\n=== LLM AESTHETIC (mean ± std over %d blind trials) ===" % a.k)
    for label,dims in rep.items():
        print(f"\n[{label}]")
        for dim,cap in {**DIMENSIONS,"TOTAL":60}.items():
            m,s=dims[dim]; print(f"  {dim:12s} {m:5.2f} ± {s:4.2f} / {cap}")
    if a.humanX is not None and a.humanY is not None:
        print("\n=== FINAL AESTHETIC (50% human + 50% LLM, /60) ===")
        for label, hv in ((a.labelX,a.humanX),(a.labelY,a.humanY)):
            fin, flag = combine_with_human(rep[label]["TOTAL"][0], hv)
            print(f"  {label:6s} final={fin}/60  (LLM {rep[label]['TOTAL'][0]}, human {hv})"
                  + ("   ⚠ judges diverge >12, review" if flag else ""))

if __name__=="__main__": main()