"""STEP 1: Anthropic prompt-cache semantics probe (raw Messages API, same models,
same thinking/effort request shapes, same key and base URL as the provider-anthropic
module the campaign sessions used). Prints and stores only usage, timings, status,
and HASHES of org ids. Never prints keys or prompt text.

Every test uses its own nonce at the very start of the system prompt, so no test can
read another test's cache entries.
"""
import hashlib, json, os, threading, time, uuid
import httpx

BASE = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
K1 = os.environ["ANTHROPIC_PROVIDER_ANTHROPIC_API_KEY"]   # what provider-anthropic uses
K2 = os.environ.get("ANTHROPIC_API_KEY")                  # second key, if different
KEYS = {"K1_provider": K1, "K2_other": K2}
OUT = os.path.dirname(os.path.abspath(__file__))
RUN = uuid.uuid4().hex[:10]
CAP = 8.0
PRICE = {  # $/M: uncached, read, write(5m), output -- list prices, from the caching README fit
    "claude-fable-5-1": (10, 0.25, 12.5, 50), "claude-opus-5-5": (4, 0.20, 5, 20), "claude-sonnet-5": (3, 0.30, 3.75, 15)}
SON, OPUS, FABLE = "claude-sonnet-5", "claude-opus-5-5", "claude-fable-5-1"
ADAPT = {"type": "adaptive", "display": "summarized"}
# shape the campaign sessions actually sent per model
DEFAULT_THINK = {SON: ADAPT, OPUS: ADAPT, FABLE: None}

SRC = os.path.expanduser("~/dev/fd-judge-realistic/docs/evidence/2026-10-01-caching/caching_survey.py")
PROV = os.path.expanduser("~/.amplifier/cache/amplifier-module-provider-anthropic-5181591dcf06d076/"
                          "amplifier_module_provider_anthropic/__init__.py")
_a, _b = open(SRC).read(), open(PROV).read()
P = "You are reviewing this Python file.\n\n" + _a[:26000]          # ~7k tokens
X = "Second file, part 1:\n\n" + _b[20000:32000]                    # ~3k tokens
X2 = "Second file, alternative part:\n\n" + _b[60000:72000]          # diverging branch
Y = "Second file, part 2:\n\n" + _b[32000:38000]
Z = "Second file, part 3:\n\n" + _b[38000:44000]
Q = "Reply with exactly the word OK and nothing else."

lock = threading.Lock()
LOG, SPEND = [], [0.0]
T0 = time.time()


def cc():
    return {"type": "ephemeral"}


def sysblk(nonce, bp=True):
    b = {"type": "text", "text": f"[probe {RUN} {nonce}]\n" + P}
    if bp:
        b["cache_control"] = cc()
    return [b]


def txt(t, bp=False):
    b = {"type": "text", "text": t}
    if bp:
        b["cache_control"] = cc()
    return b


def call(test, label, model, system, messages, key="K1_provider", thinking="default", effort=None, max_tokens=3000):
    if SPEND[0] > CAP:
        raise RuntimeError("spend cap reached")
    body = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
    th = DEFAULT_THINK[model] if thinking == "default" else thinking
    if th:
        body["thinking"] = th
    if effort:
        body["output_config"] = {"effort": effort}
    t = time.time()
    rec = dict(test=test, label=label, model=model, key=key, thinking=th, effort=effort, t_rel_s=round(t - T0, 1))
    try:
        r = httpx.post(f"{BASE}/v1/messages", json=body, timeout=300, headers={
            "x-api-key": KEYS[key], "anthropic-version": "2023-06-01", "content-type": "application/json"})
        rec["status"] = r.status_code
        rec["org_hash"] = hashlib.sha256((r.headers.get("anthropic-organization-id") or "").encode()).hexdigest()[:10]
        rec["request_id"] = r.headers.get("request-id")
        j = r.json()
        if r.status_code != 200:
            rec["error"] = (j.get("error") or {}).get("message", "")[:300]
        else:
            u = j["usage"]
            rec["usage"] = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens", "output_tokens", "cache_creation")}
            pu, pr, pw, po = PRICE[model]
            rec["cost_usd"] = round((u["input_tokens"] * pu + (u.get("cache_read_input_tokens") or 0) * pr
                                     + (u.get("cache_creation_input_tokens") or 0) * pw + u["output_tokens"] * po) / 1e6, 6)
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)[:300]
    rec["latency_s"] = round(time.time() - t, 2)
    with lock:
        SPEND[0] += rec.get("cost_usd", 0)
        LOG.append(rec)
        u = rec.get("usage") or {}
        print(f"{rec['t_rel_s']:>6} {test:<4} {label:<34} {model:<17} {key:<11} st={rec.get('status')} "
              f"in={u.get('input_tokens')} W={u.get('cache_creation_input_tokens')} R={u.get('cache_read_input_tokens')} "
              f"out={u.get('output_tokens')} ${rec.get('cost_usd', 0):.4f} {rec.get('error', '')[:120]}", flush=True)
    return rec


def u1(*blocks):
    return {"role": "user", "content": list(blocks)}


def a1(t="OK"):
    return {"role": "assistant", "content": [txt(t)]}


# ---------------------------------------------------------------- tests
def test_a():
    for model in (SON, OPUS, FABLE):
        n = f"a1-{model}"
        call("a1", "W P+X (bp X only)", model, sysblk(n, bp=False), [u1(txt(X, True), txt(Q))])
        call("a1", "P alone (bp P)", model, sysblk(n, bp=True), [u1(txt(Q))])
        call("a1", "P alone again (bp P)", model, sysblk(n, bp=True), [u1(txt(Q))])
    m = SON
    call("a2", "W P+X (bp X)", m, sysblk("a2", False), [u1(txt(X, True), txt(Q))])
    call("a2", "P+X+Y (bp Y) extension", m, sysblk("a2", False), [u1(txt(X), txt(Q)), a1(), u1(txt(Y, True), txt(Q))])
    call("a3", "W P+X (bp X)", m, sysblk("a3", False), [u1(txt(X, True), txt(Q))])
    call("a3", "P+X' (bp X') branch, no P bp", m, sysblk("a3", False), [u1(txt(X2, True), txt(Q))])
    call("a4", "W P+X (bp P and X)", m, sysblk("a4", True), [u1(txt(X, True), txt(Q))])
    call("a4", "P+X' (bp P and X') branch", m, sysblk("a4", True), [u1(txt(X2, True), txt(Q))])


def test_b():
    if not K2 or K2 == K1:
        LOG.append(dict(test="b", label="not testable: no second distinct Anthropic key"))
        return
    call("b", "W with K1", SON, sysblk("b1"), [u1(txt(X, True), txt(Q))], key="K1_provider")
    call("b", "same request with K2", SON, sysblk("b1"), [u1(txt(X, True), txt(Q))], key="K2_other")
    call("b", "same request with K1 again", SON, sysblk("b1"), [u1(txt(X, True), txt(Q))], key="K1_provider")
    call("b", "W with K2 (reverse)", SON, sysblk("b2"), [u1(txt(X, True), txt(Q))], key="K2_other")
    call("b", "same request with K1", SON, sysblk("b2"), [u1(txt(X, True), txt(Q))], key="K1_provider")


def test_c():
    for trial in range(3):
        n = f"c{trial}"
        bar = threading.Barrier(2)

        def go(i):
            bar.wait()
            call("c", f"simultaneous #{i} trial {trial}", SON, sysblk(n), [u1(txt(X, True), txt(Q))])
        ts = [threading.Thread(target=go, args=(i,)) for i in (1, 2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        call("c", f"follow-up trial {trial}", SON, sysblk(n), [u1(txt(X, True), txt(Q))])


def test_d():
    def at(t0, s):
        time.sleep(max(0, t0 + s - time.time()))
    t0 = time.time()
    req = lambda n: (sysblk(n), [u1(txt(X, True), txt(Q))])
    call("d", "A: write t=0", SON, *req("dA"))
    call("d", "B(control): write t=0", SON, *req("dB"))
    call("d", "C(control): write t=0", SON, *req("dC"))
    at(t0, 240); call("d", "A: read t=240", SON, *req("dA"))
    at(t0, 280); call("d", "C: read t=280 (<300, no refresh before)", SON, *req("dC"))
    at(t0, 420); call("d", "A: read t=420 (needs refresh at 240)", SON, *req("dA"))
    call("d", "B: read t=420 (no refresh, expect miss)", SON, *req("dB"))


def test_e():
    def seq(model, variants):
        n = f"e-{model}"
        for label, th, ef in variants:
            call("e", label, model, sysblk(n), [u1(txt(X, True), txt(Q))], thinking=th, effort=ef)
    seq(SON, [("base adaptive", ADAPT, None), ("base adaptive repeat", ADAPT, None),
              ("adaptive + effort medium", ADAPT, "medium"), ("adaptive + effort medium repeat", ADAPT, "medium"),
              ("adaptive + effort low", ADAPT, "low"), ("no thinking", None, None),
              ("base adaptive again", ADAPT, None)])
    seq(OPUS, [("base adaptive", ADAPT, None), ("adaptive + effort low", ADAPT, "low"),
               ("no thinking", None, None), ("base adaptive again", ADAPT, None)])
    seq(FABLE, [("base (no thinking param)", None, None), ("effort low", None, "low"),
                ("adaptive", ADAPT, None), ("base again", None, None)])


def test_f():
    req = (sysblk("f"), [u1(txt(X, True), txt(Q))])
    call("f", "W on sonnet", SON, *req)
    call("f", "same prefix on opus", OPUS, *req)
    call("f", "same prefix on fable", FABLE, *req)
    call("f", "sonnet again", SON, *req)
    call("f", "opus again", OPUS, *req)


def test_g():
    """Skipped call: does the next call find an entry? + 20-block lookback limit."""
    m = SON
    # g1 with the intermediate call; g2 skips it. Each request: rolling bp on its last block (provider-like).
    h1 = [u1(txt(X, True), txt(Q))]
    h2 = [u1(txt(X), txt(Q)), a1(), u1(txt(Y, True), txt(Q))]
    h3 = [u1(txt(X), txt(Q)), a1(), u1(txt(Y), txt(Q)), a1(), u1(txt(Z, True), txt(Q))]
    call("g1", "turn1 W P+X", m, sysblk("g1"), h1)
    call("g1", "turn2 P+X+Y (made)", m, sysblk("g1"), h2)
    call("g1", "turn3 P+X+Y+Z", m, sysblk("g1"), h3)
    call("g2", "turn1 W P+X", m, sysblk("g2"), h1)
    call("g2", "turn3 P+X+Y+Z (turn2 skipped)", m, sysblk("g2"), h3)
    # lookback: 30 small blocks between the written bp and the new bp
    small = [txt(f"note {i}: " + "lorem ipsum " * 8) for i in range(30)]
    call("g3", "W P+X (bp X)", m, sysblk("g3"), [u1(txt(X, True), txt(Q))])
    call("g3", "P+X + 30 blocks (bp last)", m, sysblk("g3"), [u1(txt(X), txt(Q)), a1(), u1(*small[:-1], dict(small[-1], cache_control=cc()))])
    call("g4", "W P+X (bp X)", m, sysblk("g4"), [u1(txt(X, True), txt(Q))])
    call("g4", "P+X + 10 blocks (bp last)", m, sysblk("g4"), [u1(txt(X), txt(Q)), a1(), u1(*small[:9], dict(small[9], cache_control=cc()))])


def main():
    print(f"run={RUN} base_host={httpx.URL(BASE).host} K2_distinct={bool(K2 and K2 != K1)}", flush=True)
    td = threading.Thread(target=test_d)
    td.start()
    for f in (test_f, test_a, test_b, test_c, test_e, test_g):
        try:
            f()
        except Exception as e:  # noqa: BLE001
            LOG.append(dict(test=f.__name__, error=repr(e)[:300]))
            print("ERR", f.__name__, repr(e)[:200], flush=True)
    td.join()
    out = dict(run=RUN, base_host=httpx.URL(BASE).host, prices_usd_per_mtok=PRICE,
               note="raw /v1/messages; usage.input_tokens here EXCLUDES cache reads and writes (raw API convention)",
               total_cost_usd=round(SPEND[0], 4), requests=LOG)
    with open(os.path.join(OUT, "step1_cache_probe.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"TOTAL ${SPEND[0]:.4f} over {len([r for r in LOG if 'usage' in r])} ok requests")


if __name__ == "__main__":
    main()
